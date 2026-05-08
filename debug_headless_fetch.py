"""Debug : fetch une URL en Playwright headless EXACTEMENT comme le scraper.

Sauvegarde HTML + screenshot pour comparaison avec ce que ton vrai navigateur
voit pour la même URL. Permet de détecter :
- CAPTCHA / page "unusual traffic"
- Layout différent (sélecteur introuvable)
- Page consent qui bloque encore
- "No results" page (Google pense qu'il n'y a rien)

Usage :
    uv run python debug_headless_fetch.py "<URL>"
    uv run python debug_headless_fetch.py "<URL>" --visible   # pour voir la fenêtre

Files générés :
    /tmp/headless_debug.html   — ouvre dans ton navigateur
    /tmp/headless_debug.png    — screenshot full page
"""

import asyncio
import sys
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Garde la même config anti-détection que le scraper réel (single source of truth)
from fast_flights_patch import REALISTIC_UA


async def main(url: str, headless: bool = True):
    print(f"🤖 Mode : {'headless' if headless else 'visible (fenêtre Chromium)'}")
    print(f"📥 URL  : {url[:120]}{'...' if len(url) > 120 else ''}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=REALISTIC_UA,
            )
            await Stealth().apply_stealth_async(ctx)
            # Mêmes cookies que le scraper réel
            await ctx.add_cookies([
                {
                    "name": "CONSENT",
                    "value": "YES+cb.20210720-07-p0.en+FX+410",
                    "domain": ".google.com", "path": "/",
                },
                {
                    "name": "SOCS",
                    "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                    "domain": ".google.com", "path": "/",
                },
            ])
            page = await ctx.new_page()

            print("⏳ Goto (timeout 30s)...")
            await page.goto(url, timeout=30000)
            print(f"   ✅ Page chargée — URL finale : {page.url[:120]}")
            print()

            print("⏳ Attente sélecteur .eQ35Ce (max 30s — généreux pour diag)...")
            selector_found = False
            try:
                await page.locator(".eQ35Ce").wait_for(timeout=30000)
                selector_found = True
                print("   ✅ Sélecteur trouvé")
            except Exception as e:
                print(f"   ❌ Timeout : {type(e).__name__}")
            print()

            # Capture HTML + screenshot
            html = await page.content()
            with open("/tmp/headless_debug.html", "w", encoding="utf-8") as f:
                f.write(f"<!-- URL: {url} -->\n")
                f.write(f"<!-- selector_found: {selector_found} -->\n")
                f.write(html)
            print(f"💾 HTML  : /tmp/headless_debug.html ({len(html) // 1024} KB)")

            await page.screenshot(path="/tmp/headless_debug.png", full_page=True)
            print(f"📸 Image : /tmp/headless_debug.png\n")

            # Heuristiques de diagnostic
            html_low = html.lower()
            indicators = {
                "🚨 CAPTCHA / anti-bot": ["recaptcha", "g-recaptcha", "are you a robot", "unusual traffic", "/sorry/"],
                "⚠️  Page no-results": ["no results found", "no flights found", "aucun vol trouvé", "no_results"],
                "⚠️  Consent toujours là": ["consent.google.com", "before you continue"],
                "✅ Indicateurs de vols présents": ["currency", "$ ", "€ ", "duration", "stops"],
            }
            print("🔍 Heuristiques HTML :")
            for label, patterns in indicators.items():
                hits = [p for p in patterns if p in html_low]
                if hits:
                    print(f"   {label} : {hits[:3]}")
            print()

            # Compte différents sélecteurs candidats
            print("🔍 Sélecteurs candidats (occurrences) :")
            for sel, desc in [
                (".eQ35Ce", "wrapper résultats actuel"),
                (".pIav2d", "ancien wrapper"),
                ("[role='main']", "main role (toujours là)"),
                (".YMlIz", "prix"),
                ("li.pIav2d", "items vols"),
                ("[jsname='IWWDBc']", "best flights section"),
                ("[jsname='YdtKid']", "other flights section"),
            ]:
                try:
                    count = await page.locator(sel).count()
                    marker = "✅" if count > 0 else "❌"
                    print(f"   {marker} {sel:<30} ({desc:<25}) : {count}")
                except Exception:
                    pass

        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: debug_headless_fetch.py <URL> [--visible]")
        sys.exit(1)

    url = sys.argv[1]
    headless = "--visible" not in sys.argv

    asyncio.run(main(url, headless=headless))
