"""Phase 1 scraper : matrice calendaire Google Flights via XHR interception.

Endpoint cible :
    POST https://www.google.com/_/FlightsFrontendUi/data/
         travel.frontend.flights.FlightsFrontendService/GetCalendarGrid

Format de réponse : voir spec docs/superpowers/specs/2026-05-10-calendar-picker-design.md
"""

import asyncio
import json
import random
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

import fast_flights_patch  # noqa: F401  — DOIT être importé pour appliquer le monkey-patch protobuf type=1
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData

from config import (
    START_DATE, END_DATE, TRIP_DURATIONS,
    ALLOWED_DEPARTURE_WEEKDAYS, ALLOWED_RETURN_WEEKDAYS,
    MIN_PRICE, MAX_PRICE,
    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX,
    CALENDAR_GOTO_TIMEOUT_MS, CALENDAR_RESULTS_TIMEOUT_MS,
    CALENDAR_WAIT_FOR_MATRIX_MS,
    USE_CACHE,
    PARALLEL_WORKERS,
)
from cache import get_calendar_cache, save_calendar_cache


@dataclass(frozen=True)
class CalendarCell:
    """Une cellule de la matrice calendaire : un couple (aller, retour) avec son prix."""
    date_aller: date
    date_retour: date
    dep: str
    arrival: str
    prix: float
    deeplink_token: str = ""


def strip_xssi_prefix(text: str) -> str:
    """Retire le préfixe anti-XSSI de Google `)]}'` et les newlines en tête."""
    if text.startswith(")]}'"):
        text = text[4:]
    return text.lstrip("\n")


_DECODER = json.JSONDecoder()


def iter_frames(body: str) -> Iterator[object]:
    """Itère sur les frames JSON d'une réponse Google chunked.

    Format : `<size>\\n<json_frame>` répété, séparés par whitespace.
    On utilise `JSONDecoder.raw_decode` plutôt que de faire confiance au header
    de taille — Google peut renvoyer une taille qui couvre plus que le JSON
    (incluant des chars de framing). raw_decode trouve la fin réelle du JSON.

    Skip silencieusement les size non-numériques (fin de stream).
    """
    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in " \t\n\r":
            pos += 1
        if pos >= len(body):
            return

        nl = body.find("\n", pos)
        if nl == -1:
            return
        size_str = body[pos:nl].strip()
        if not size_str.isdigit():
            return
        pos = nl + 1
        try:
            obj, end = _DECODER.raw_decode(body, pos)
        except json.JSONDecodeError:
            return
        yield obj
        pos = end


def extract_wrb_payload(frame) -> object | None:
    """Extrait le payload JSON imbriqué d'une frame `wrb.fr`.

    Format frame : `[["wrb.fr", null, "<json_stringified>"]]`.
    Retourne None pour les frames non-`wrb.fr` ou malformées.
    """
    if not isinstance(frame, list) or not frame:
        return None
    head = frame[0]
    if not isinstance(head, list) or len(head) < 3 or head[0] != "wrb.fr":
        return None
    inner_str = head[2]
    if not isinstance(inner_str, str):
        return None
    try:
        return json.loads(inner_str)
    except json.JSONDecodeError:
        return None


def extract_cells(payload, dep: str, arrival: str) -> list[CalendarCell]:
    """Extrait les CalendarCell d'un payload wrb.fr (parsé via extract_wrb_payload).

    Format cellule : [date_aller_iso, date_retour_iso, [[null, prix_int], token], status]
    status == 1 → valide ; 2 → invalide (prix slot = null).
    """
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    cells_data = payload[1]
    if not isinstance(cells_data, list):
        return []

    out = []
    for entry in cells_data:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        date_aller_str, date_retour_str, price_data, status = entry[:4]
        if status != 1 or not price_data:
            continue
        try:
            prix = price_data[0][1]
        except (IndexError, TypeError):
            continue
        if prix is None:
            continue
        try:
            token = price_data[1] if len(price_data) > 1 else ""
        except (IndexError, TypeError):
            token = ""
        try:
            d_aller = date.fromisoformat(date_aller_str)
            d_retour = date.fromisoformat(date_retour_str)
        except (ValueError, TypeError):
            continue
        out.append(CalendarCell(
            date_aller=d_aller,
            date_retour=d_retour,
            dep=dep,
            arrival=arrival,
            prix=float(prix),
            deeplink_token=token if isinstance(token, str) else "",
        ))
    return out


def parse_calendar_response(raw: str, dep: str, arrival: str) -> list[CalendarCell]:
    """Parse une réponse complète `GetCalendarGrid` → liste de CalendarCell.

    Pipeline : strip XSSI → iter chunked frames → extract wrb.fr payload → extract cells.
    Skip silencieusement les frames di/e/af.httprm.
    """
    body = strip_xssi_prefix(raw)
    cells: list[CalendarCell] = []
    for frame in iter_frames(body):
        payload = extract_wrb_payload(frame)
        if payload is None:
            continue
        cells.extend(extract_cells(payload, dep=dep, arrival=arrival))
    return cells


def filter_and_select_top_n(
    cells: list[CalendarCell],
    top_n: int,
) -> list[tuple]:
    """Pipeline de filtrage côté Python sur les cellules de la matrice :

        1. weekday  : date_aller.weekday() ∈ ALLOWED_DEPARTURE_WEEKDAYS
                      date_retour.weekday() ∈ ALLOWED_RETURN_WEEKDAYS
        2. durée    : (date_retour - date_aller).days ∈ TRIP_DURATIONS
                      (convention de utils.generate_combinations)
        3. prix     : MIN_PRICE < prix < MAX_PRICE
        4. range    : date_aller >= START_DATE, date_retour <= END_DATE
        5. dédup    : par (dep, arr, date_aller, date_retour), garde le moins cher
        6. group by route, sort by prix asc, take [:top_n]

    Retourne : list[(date_aller, date_retour, duration, dep, arrival)]
    Format identique à `utils.generate_combinations()` / consommé par
    `fast_flights_scraper.process_combo()`.
    """
    # Étapes 1-4 : filtres
    valid: list[CalendarCell] = []
    for c in cells:
        if c.date_aller.weekday() not in ALLOWED_DEPARTURE_WEEKDAYS:
            continue
        if c.date_retour.weekday() not in ALLOWED_RETURN_WEEKDAYS:
            continue
        duration = (c.date_retour - c.date_aller).days
        if duration not in TRIP_DURATIONS:
            continue
        if not (MIN_PRICE < c.prix < MAX_PRICE):
            continue
        if c.date_aller < START_DATE or c.date_retour > END_DATE:
            continue
        valid.append(c)

    # Étape 5 : dédup par (dep, arr, da, dr) en gardant le moins cher
    dedup: dict[tuple, CalendarCell] = {}
    for c in valid:
        key = (c.dep, c.arrival, c.date_aller, c.date_retour)
        prev = dedup.get(key)
        if prev is None or c.prix < prev.prix:
            dedup[key] = c

    # Étape 6 : group by route, top-N par route
    by_route: dict[tuple, list[CalendarCell]] = defaultdict(list)
    for c in dedup.values():
        by_route[(c.dep, c.arrival)].append(c)

    out: list[tuple] = []
    for route_cells in by_route.values():
        route_cells.sort(key=lambda c: c.prix)
        for c in route_cells[:top_n]:
            duration = (c.date_retour - c.date_aller).days
            out.append((c.date_aller, c.date_retour, duration, c.dep, c.arrival))
    return out


# ============ Stealth Playwright setup (duplicated from fast_flights_patch.py) ============

REALISTIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_stealth = Stealth()


@asynccontextmanager
async def _stealth_browser_context():
    """Browser+context Chromium configuré identiquement à fast_flights_patch.py
    (UA, locale, timezone, cookies CONSENT/SOCS, stealth patches).

    Code dupliqué intentionnellement de fast_flights_patch.py — ne pas refactorer
    pour mutualiser, le module doit rester intact (cf spec : préférence
    duplication > refactor pour le code anti-détection qui marche).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=REALISTIC_UA,
            )
            await _stealth.apply_stealth_async(context)
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
            yield context
        finally:
            await browser.close()


async def _dismiss_consent_fallback(page):
    """Cliquer 'Accept all' si la page consent apparaît malgré les cookies préchargés."""
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Tout accepter")',
        'button[aria-label*="Accept"]',
        'button[aria-label*="Accepter"]',
    ]
    for sel in selectors:
        btn = page.locator(sel)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=2000)
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return


def build_google_flights_url(
    dep: str, arrival: str,
    date_aller: date, date_retour: date,
) -> str:
    """Construit l'URL Google Flights round-trip qu'on visite avant d'ouvrir Date grid.

    Réutilise le builder TFSData de fast-flights (avec son monkey-patch type=1
    qui répare CUZ/AQP). Locale en-US/FR pour cohérence avec l'exploration manuelle.
    """
    tfs = TFSData.from_interface(
        flight_data=[
            FlightData(date=date_aller.isoformat(), from_airport=dep, to_airport=arrival),
            FlightData(date=date_retour.isoformat(), from_airport=arrival, to_airport=dep),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1),
        max_stops=None,
    )
    tfs_b64 = tfs.as_b64().decode("utf-8")
    return (
        "https://www.google.com/travel/flights"
        f"?tfs={tfs_b64}&hl=en-US&gl=FR&curr=EUR"
    )


# Selectors confirmed via manual DOM exploration (cf. exploration.md at project root)
_SEL_RESULTS_LOADED = ".eQ35Ce"
_SEL_DATE_GRID_BUTTON = 'button[jsname="KqtnKd"]'
_SEL_MATRIX_CANVAS = 'canvas[jsname="qTwgI"]'
_SEL_SCROLL_RIGHT = 'button[aria-label="Scroll right"]'
_SEL_SCROLL_DOWN = 'button[aria-label="Scroll down"]'
_GET_CALENDAR_GRID_URL_FRAGMENT = "/GetCalendarGrid"


async def _scrape_calendar_for_route_uncached(
    dep: str,
    arrival: str,
    start_anchor: date,
    end_anchor: date,
    *,
    max_clicks: int = 250,
) -> list[CalendarCell]:
    """Scrape la matrice calendaire pour 1 route.

    Pattern :
      1. Build URL avec anchor (start_anchor, start_anchor + median_duration)
      2. Navigate, wait results, dismiss consent
      3. Set up page.on("response") qui filtre sur /GetCalendarGrid et stocke les bodies
      4. Click Date grid button (jsname=KqtnKd) → 1ère réponse
      5. Loop : alternate scroll_right + scroll_down clicks, capture chaque réponse,
         parse, jusqu'à atteindre end_anchor ou max_clicks
      6. Dédup les cellules par (date_aller, date_retour)
    """
    median_duration = sorted(TRIP_DURATIONS)[len(TRIP_DURATIONS) // 2]  # 24
    anchor_aller = start_anchor
    anchor_retour = start_anchor + timedelta(days=median_duration)
    url = build_google_flights_url(dep, arrival, anchor_aller, anchor_retour)

    captured: list[str] = []

    async def on_response(response):
        if _GET_CALENDAR_GRID_URL_FRAGMENT in response.url:
            try:
                captured.append(await response.text())
            except Exception:
                pass

    cells_by_key: dict[tuple, CalendarCell] = {}

    async with _stealth_browser_context() as context:
        page = await context.new_page()
        page.on("response", on_response)

        await page.goto(url, timeout=CALENDAR_GOTO_TIMEOUT_MS)
        await _dismiss_consent_fallback(page)
        await page.locator(_SEL_RESULTS_LOADED).wait_for(timeout=CALENDAR_RESULTS_TIMEOUT_MS)

        # Open Date grid → triggers initial GetCalendarGrid
        await page.locator(_SEL_DATE_GRID_BUTTON).click(timeout=5000)
        await page.locator(_SEL_MATRIX_CANVAS).wait_for(timeout=CALENDAR_WAIT_FOR_MATRIX_MS)
        # Wait a moment for the response listener to capture
        await asyncio.sleep(0.8)

        # Slide loop: alternate scroll_right and scroll_down (advance both axes by 1)
        clicks = 0
        max_aller = end_anchor  # we want date_aller to reach this

        while clicks < max_clicks:
            # Parse what we have so far to know our coverage
            for raw in captured:
                for cell in parse_calendar_response(raw, dep=dep, arrival=arrival):
                    key = (cell.date_aller, cell.date_retour)
                    prev = cells_by_key.get(key)
                    if prev is None or cell.prix < prev.prix:
                        cells_by_key[key] = cell
            captured.clear()

            # Termination: if we have at least one cell with date_aller >= max_aller, done
            if cells_by_key and max(c.date_aller for c in cells_by_key.values()) >= max_aller:
                break

            # Click pair: scroll right (advance date_aller) then scroll down (advance date_retour)
            try:
                await page.locator(_SEL_SCROLL_RIGHT).click(timeout=3000)
                await asyncio.sleep(random.uniform(
                    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX
                ))
                clicks += 1
                if clicks >= max_clicks:
                    break
                await page.locator(_SEL_SCROLL_DOWN).click(timeout=3000)
                await asyncio.sleep(random.uniform(
                    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX
                ))
                clicks += 1
            except Exception:
                # Buttons disabled (end of range) or vanished — break
                break

        # Final parse pass for any responses captured during the last sleep
        for raw in captured:
            for cell in parse_calendar_response(raw, dep=dep, arrival=arrival):
                key = (cell.date_aller, cell.date_retour)
                prev = cells_by_key.get(key)
                if prev is None or cell.prix < prev.prix:
                    cells_by_key[key] = cell

    return list(cells_by_key.values())


async def scrape_calendar_for_route(
    dep: str,
    arrival: str,
    start_anchor: date,
    end_anchor: date,
    *,
    max_clicks: int = 250,
) -> list[CalendarCell]:
    """Scrape la matrice calendaire pour 1 route. Cf docstring détaillé du module.

    Cache disque par (dep, arrival, start_anchor). TTL = CACHE_TTL_HOURS.
    """
    if USE_CACHE:
        cached = get_calendar_cache(dep, arrival, start_anchor)
        if cached is not None:
            return cached

    cells = await _scrape_calendar_for_route_uncached(
        dep, arrival, start_anchor, end_anchor, max_clicks=max_clicks,
    )

    if USE_CACHE and cells:
        save_calendar_cache(dep, arrival, start_anchor, cells)

    return cells


class _CalendarTracker:
    """Live tracker pour Phase 1 : barre + stats par route + 10 lignes roulantes."""
    MAX_RESULTS = 10
    BAR_WIDTH = 40

    def __init__(self, total_routes: int):
        self.total = total_routes
        self.done = 0
        self.cells_count = 0
        self.from_cache = 0
        self.from_network = 0
        self.errors = 0
        self.start_time = time.perf_counter()
        self.lock = asyncio.Lock()
        self.last_results: deque = deque(
            [Text(" ")] * self.MAX_RESULTS,
            maxlen=self.MAX_RESULTS,
        )

    async def record(self, *, line: Text, kind: str, n_cells: int):
        async with self.lock:
            self.done += 1
            self.cells_count += n_cells
            if kind == "cache":
                self.from_cache += 1
            elif kind == "network":
                self.from_network += 1
            elif kind == "error":
                self.errors += 1
            self.last_results.append(line)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"

    def __rich__(self):
        pct = self.done / self.total if self.total else 1.0
        filled = int(self.BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        elapsed = self._fmt_time(time.perf_counter() - self.start_time)
        header = Text.assemble(
            "📅 [", (bar, "magenta"), "] ",
            (f"{self.done}/{self.total}", "bold"),
            (f" ({pct * 100:.0f}%) ", "dim"),
            "| ", (f"écoulé {elapsed}", "yellow"),
        )
        stats = Text.assemble(
            "🧮 ", (f"{self.cells_count}", "bold green"), " cellules  ",
            "📦 ", (f"{self.from_cache}", "bold blue"), " cache  ",
            "🌐 ", (f"{self.from_network}", "bold cyan"), " net  ",
            "❌ ", (f"{self.errors}", "bold red"), " err",
        )
        return Group(header, stats, Text(""), *list(self.last_results))


async def _process_route(
    dep: str, arrival: str,
    start_anchor: date, end_anchor: date,
    semaphore: asyncio.Semaphore,
    tracker: _CalendarTracker,
    out: list,
    out_lock: asyncio.Lock,
):
    t0 = time.perf_counter()
    cached = get_calendar_cache(dep, arrival, start_anchor) if USE_CACHE else None
    if cached is not None:
        async with out_lock:
            out.extend(cached)
        elapsed = time.perf_counter() - t0
        await tracker.record(
            line=Text(f"📦 ✅ {dep}→{arrival}: {len(cached)} cellules ({elapsed:.1f}s)",
                      style="blue", no_wrap=True, overflow="ellipsis"),
            kind="cache", n_cells=len(cached),
        )
        return

    async with semaphore:
        try:
            cells = await _scrape_calendar_for_route_uncached(
                dep, arrival, start_anchor, end_anchor,
            )
            if USE_CACHE and cells:
                save_calendar_cache(dep, arrival, start_anchor, cells)
            async with out_lock:
                out.extend(cells)
            elapsed = time.perf_counter() - t0
            await tracker.record(
                line=Text(
                    f"🌐 ✅ {dep}→{arrival}: {len(cells)} cellules ({elapsed:.1f}s)",
                    style="green", no_wrap=True, overflow="ellipsis",
                ),
                kind="network", n_cells=len(cells),
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0
            err = f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:60]}"
            await tracker.record(
                line=Text(f"❌ {dep}→{arrival}: {err} ({elapsed:.1f}s)",
                          style="red", no_wrap=True, overflow="ellipsis"),
                kind="error", n_cells=0,
            )


async def run_calendar_picker_scraper_async(
    valid_routes: dict | None = None,
) -> list[CalendarCell]:
    """Orchestre Phase 1 sur toutes les routes (DEPARTURE × ARRIVAL),
    filtrées par valid_routes si fourni.
    """
    from config import DEPARTURE_AIRPORTS, ARRIVAL_AIRPORTS

    routes = []
    for d in DEPARTURE_AIRPORTS:
        for arr in ARRIVAL_AIRPORTS:
            if valid_routes is not None:
                info = valid_routes.get((d, arr))
                if info is not None and not info["is_valid"]:
                    continue
            routes.append((d, arr))

    print("\n" + "═" * 80)
    print(f"{'📅 PHASE 1 — CALENDAR PICKER':^80}")
    print("═" * 80 + "\n")
    print(f"🔍 {len(routes)} routes | {PARALLEL_WORKERS} workers\n")

    semaphore = asyncio.Semaphore(PARALLEL_WORKERS)
    tracker = _CalendarTracker(total_routes=len(routes))
    out: list[CalendarCell] = []
    out_lock = asyncio.Lock()

    # Walk anchors covering the full range. For each route, one (start_anchor=START_DATE)
    # call walks the matrix until END_DATE - min(TRIP_DURATIONS).
    end_anchor = END_DATE - timedelta(days=min(TRIP_DURATIONS))

    tasks = [
        _process_route(d, arr, START_DATE, end_anchor, semaphore, tracker, out, out_lock)
        for d, arr in routes
    ]

    console = Console()
    with Live(tracker, refresh_per_second=8, console=console):
        await asyncio.gather(*tasks)

    print(f"\n✅ Phase 1 terminée : {len(out)} cellules brutes pour {len(routes)} routes")
    return out


def run_calendar_picker_scraper(valid_routes=None) -> list[CalendarCell]:
    return asyncio.run(run_calendar_picker_scraper_async(valid_routes))
