"""
Monkey-patch fast-flights pour :
1. Réduire le timeout (10s au lieu de 30s)
2. Bypass le consent RGPD Google (cause de 99% des timeouts en France)
3. Forcer la locale en-US pour éviter les variations régionales
4. Injecter `type=1` (IATA) dans chaque Airport du protobuf TFS — fast-flights v2
   sérialise `Airport{airport=code}` mais Google attend `Airport{type=1, airport=code}`.
   Pour les hubs majeurs (CDG/LIM/MAD) Google infère le type. Pour les exotiques
   (CUZ/AQP/...) sans le discriminateur, Google retombe sur "no results" → timeout.

À importer AVANT toute utilisation de fast-flights.
"""

import fast_flights.local_playwright as fl_pw
import fast_flights.flights_impl as fl_impl
from playwright_stealth import Stealth


GOTO_TIMEOUT_MS = 12000        # navigation : doit être rapide
WAIT_FOR_TIMEOUT_MS = 12000    # sélecteur de résultats : pages chargent en 3-5s
                               # quand stealth marche, et timeout = CAPTCHA quand
                               # stealth échoue (rallonger ne sauve rien).

# User-Agent Chrome récent réaliste (Windows 10 x64, le plus banal possible).
# Stealth lit cet UA depuis le context et patche `navigator.userAgent`,
# `navigator.userAgentData`, `Sec-CH-UA` headers en cohérence.
REALISTIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Configuration playwright-stealth : tous les patches activés par défaut sauf
# chrome_runtime (peut planter sur certains sites). Couvre :
# navigator.{webdriver,plugins,languages,permissions,platform,userAgent,
# userAgentData,vendor,hardwareConcurrency}, chrome.{app,csi,loadTimes},
# WebGL vendor/renderer, Sec-CH-UA, hairline detection, iframe.contentWindow,
# Error.prototype.toString, media codecs.
_stealth = Stealth()


def patch_fast_flights_timeout(
    goto_timeout_ms: int = GOTO_TIMEOUT_MS,
    wait_timeout_ms: int = WAIT_FOR_TIMEOUT_MS,
):
    """Patch fast-flights avec timeouts dissociés (navigation rapide, attente résultats longue)
    + bypass consent RGPD."""

    async def fetch_with_playwright_patched(url: str) -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            # Flag --disable-blink-features=AutomationControlled : enlève le tell
            # `navigator.webdriver=true` que Chromium expose par défaut.
            browser = await p.chromium.launch(
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = await browser.new_context(
                    locale="en-US",
                    timezone_id="America/New_York",
                    user_agent=REALISTIC_UA,
                )

                # Applique playwright-stealth : ~20 patches anti-détection
                # (webdriver, plugins, languages, WebGL, chrome runtime, etc.)
                await _stealth.apply_stealth_async(context)

                # Pré-positionne le cookie de consent pour bypass la page RGPD
                await context.add_cookies([
                    {
                        "name": "CONSENT",
                        "value": "YES+cb.20210720-07-p0.en+FX+410",
                        "domain": ".google.com",
                        "path": "/",
                    },
                    {
                        "name": "SOCS",
                        "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                        "domain": ".google.com",
                        "path": "/",
                    },
                ])

                page = await context.new_page()
                await page.goto(url, timeout=goto_timeout_ms)

                # Fallback : si le consent apparaît quand même, le cliquer
                try:
                    consent_selectors = [
                        'button:has-text("Accept all")',
                        'button:has-text("Tout accepter")',
                        'button[aria-label*="Accept"]',
                        'button[aria-label*="Accepter"]',
                    ]
                    for selector in consent_selectors:
                        btn = page.locator(selector)
                        if await btn.count() > 0:
                            await btn.first.click(timeout=2000)
                            await page.wait_for_load_state("networkidle", timeout=5000)
                            break
                except Exception:
                    pass

                # Attente du sélecteur de résultats Google Flights (timeout long
                # car AQP/CUZ peuvent demander 15-20s de compute serveur)
                await page.locator(".eQ35Ce").wait_for(timeout=wait_timeout_ms)
                body = await page.content()
                return body
            finally:
                await browser.close()

    fl_pw.fetch_with_playwright = fetch_with_playwright_patched
    print(
        f"⚙️  fast-flights patché : goto {goto_timeout_ms}ms + wait_for {wait_timeout_ms}ms "
        f"+ consent RGPD + locale en-US + playwright-stealth"
    )


# ============ Patch protobuf : Airport.type=1 (IATA) ============

def _parse_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _encode_varint(n: int) -> bytes:
    out = bytearray()
    while n > 127:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _patch_flight_data(fd_bytes: bytes) -> bytes:
    """Walk FlightData, préfixe \\x08\\x01 (type=1, IATA) à chaque Airport
    dans les fields 13 (from_flight) et 14 (to_flight)."""
    out = bytearray()
    pos = 0
    while pos < len(fd_bytes):
        tag, pos = _parse_varint(fd_bytes, pos)
        field_num = tag >> 3
        wire_type = tag & 7

        if wire_type == 2:  # length-delimited
            length, pos = _parse_varint(fd_bytes, pos)
            payload = fd_bytes[pos:pos + length]
            pos += length
            if field_num in (13, 14):
                payload = b"\x08\x01" + payload
            out += _encode_varint(tag)
            out += _encode_varint(len(payload))
            out += payload
        elif wire_type == 0:  # varint
            value, pos = _parse_varint(fd_bytes, pos)
            out += _encode_varint(tag)
            out += _encode_varint(value)
        else:
            raise ValueError(f"wire type {wire_type} non géré dans FlightData")
    return bytes(out)


def _patch_protobuf_add_airport_type(raw: bytes) -> bytes:
    """Top-level walk Info : pour chaque FlightData (field 3), patche ses Airports.
    Les autres fields (passengers, seat, trip) sont préservés tels quels."""
    out = bytearray()
    pos = 0
    while pos < len(raw):
        tag, pos = _parse_varint(raw, pos)
        field_num = tag >> 3
        wire_type = tag & 7

        if wire_type == 2:
            length, pos = _parse_varint(raw, pos)
            payload = raw[pos:pos + length]
            pos += length
            if field_num == 3:  # FlightData repeated
                payload = _patch_flight_data(payload)
            out += _encode_varint(tag)
            out += _encode_varint(len(payload))
            out += payload
        elif wire_type == 0:
            value, pos = _parse_varint(raw, pos)
            out += _encode_varint(tag)
            out += _encode_varint(value)
        else:
            raise ValueError(f"wire type {wire_type} non géré dans Info")
    return bytes(out)


def patch_fast_flights_protobuf():
    """Monkey-patche TFSData.to_string pour injecter type=1 (IATA) dans chaque Airport.

    Sans ce patch, le protobuf généré par fast-flights v2 manque le field
    discriminator que Google utilise pour résoudre IATA → city/airport. Pour les
    aéroports rares (Cusco CUZ, Arequipa AQP, etc.) le parser Google échoue et
    retourne "no results" → timeout sur le sélecteur `.eQ35Ce`.
    """
    _original_to_string = fl_impl.TFSData.to_string

    def to_string_patched(self):
        raw = _original_to_string(self)
        return _patch_protobuf_add_airport_type(raw)

    fl_impl.TFSData.to_string = to_string_patched
    print("⚙️  fast-flights patché : Airport.type=1 (IATA) injecté → fixe CUZ/AQP/exotiques")


# Application au moment de l'import
patch_fast_flights_timeout()
patch_fast_flights_protobuf()