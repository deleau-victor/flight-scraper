"""Debug visuel : voir ce qui se passe sur CDG→CUZ round-trip"""

import asyncio
from playwright.async_api import async_playwright


async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        context = await browser.new_context(
            locale="en-US",
            timezone_id="America/New_York",
        )
        
        # Pré-positionne les cookies de consent
        await context.add_cookies([
            {
                "name": "CONSENT",
                "value": "YES+cb.20210720-07-p0.en+FX+410",
                "domain": ".google.com",
                "path": "/",
            },
        ])
        
        page = await context.new_page()
        
        # URL similaire à ce que fast-flights génère
        url = "https://www.google.com/travel/flights?q=Flights%20from%20CDG%20to%20CUZ%20on%202026-07-03%20returning%202026-07-27"
        
        print(f"Navigation vers: {url}")
        await page.goto(url)
        
        print("\n⏸️  Observe la page :")
        print("   1. Y a-t-il des vols affichés ?")
        print("   2. Combien de temps prend le rendu complet ?")
        print("   3. Vérifie l'inspecteur (F12) : la classe '.eQ35Ce' existe-t-elle dans le DOM ?")
        print("\n   Pour vérifier '.eQ35Ce' : F12 → Console → tape :")
        print("   document.querySelector('.eQ35Ce')")
        print("\n   Si c'est null → le sélecteur n'existe pas sur cette page")
        print("   Appuie sur Ctrl+C pour fermer.\n")
        
        await asyncio.sleep(120)
        await browser.close()


asyncio.run(debug())