# Moi :

⚙️ fast-flights patché : timeout 12000ms + consent RGPD bypass + locale en-US

════════════════════════════════════════════════════════════════════════════════
🛫 SCRAPER GOOGLE FLIGHTS (async + cache)
════════════════════════════════════════════════════════════════════════════════

════════════════════════════════════════════════════════════════════════════════
🔍 PRÉFILTRAGE DES ROUTES (hot zones)
════════════════════════════════════════════════════════════════════════════════

📦 18 routes en cache valide :
✅ CDG→LIM | 1 zone(s)
✅ CDG→CUZ | 1 zone(s)
✅ CDG→AQP | 1 zone(s)
✅ ORY→LIM | 1 zone(s)
✅ ORY→CUZ | 1 zone(s)
✅ ORY→AQP | 1 zone(s)
❌ BVA→LIM | —
❌ BVA→CUZ | —
❌ BVA→AQP | —
❌ CRL→LIM | —
❌ CRL→CUZ | —
❌ CRL→AQP | —
✅ BRU→LIM | 1 zone(s)
✅ BRU→CUZ | 2 zone(s)
✅ BRU→AQP | 1 zone(s)
✅ AMS→LIM | 1 zone(s)
✅ AMS→CUZ | 1 zone(s)
✅ AMS→AQP | 1 zone(s)

✨ Toutes les routes sont en cache, pas de test à faire

🔪 990 combinaisons éliminées par le préfiltrage (972 routes mortes + 18 hors hot zones)

🔍 1926 combinaisons | 4 workers
⏱️ Estimation initiale : ~64.2 min (raffinée en live)
📦 Cache : 0 round-trip + 0 one-way (0.0 KB)

🛫 [████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 233/1926 (12%) | écoulé 9m04s | ETA 1h05m
📦 0 cache 🌐 148 net ⚠️ 0 vides ❌ 85 err

[226/1926] 🌐 ✅ AMS→LIM 2026-07-16(Thu) → 2026-08-08(Sat) (23j) | min: €1551 (12 hr 30 min, 0esc)
[224/1926] 🌐 ✅ BRU→CUZ 2026-07-16(Thu) → 2026-08-08(Sat) (23j) | min: €2064 (20 hr 10 min, 2esc)
[229/1926] 🌐 ✅ CDG→LIM 2026-07-16(Thu) → 2026-08-09(Sun) (24j) | min: €1497 (18 hr 40 min, 1esc)
[225/1926] ❌ BRU→AQP 2026-07-16: TimeoutError: Locator.wait_for: Timeout 12000ms exceeded.
[227/1926] 🌐 ✅ AMS→CUZ 2026-07-16(Thu) → 2026-08-08(Sat) (23j) | min: €2061 (20 hr 5 min, 2esc)
[228/1926] 🌐 ✅ AMS→AQP 2026-07-16(Thu) → 2026-08-08(Sat) (23j) | min: €1909 (15 hr 50 min, 1esc)
[230/1926] 🌐 ✅ CDG→CUZ 2026-07-16(Thu) → 2026-08-09(Sun) (24j) | min: €4099 (21 hr 40 min, 2esc)
[232/1926] 🌐 ✅ ORY→LIM 2026-07-16(Thu) → 2026-08-09(Sun) (24j) | min: €1737 (16 hr, 1esc)
[235/1926] 🌐 ✅ BRU→LIM 2026-07-16(Thu) → 2026-08-09(Sun) (24j) | min: €1618 (14 hr 20 min, 1esc)
[231/1926] ❌ CDG→AQP 2026-07-16: TimeoutError: Locator.wait_for: Timeout 12000ms exceeded.

Problème : beaucoup d'erreurs.

Problème trouver :
debug_visual.py
-> Pas de vol sur l'url :
https://www.google.com/travel/flights?q=Flights+from+CDG+to+CUZ+on+2026-07-03+returning+2026-07-27

Par contre si de mon propre navigateur, je vais sur google flight, et que je rentre les me^mes paramètres, j'ai :
https://www.google.com/travel/flights/search?tfs=CBwQAhojEgoyMDI2LTA3LTAzagcIARIDQ0RHcgwIAxIIL20vMGpsZDMaIxIKMjAyNi0wNy0yN2oMCAMSCC9tLzBqbGQzcgcIARIDQ0RHQAFIAXABggELCP___________wGYAQE&tfu=EgYIABAAGAA&hl=fr&gl=FR
Et en plus de ça il y a des vols

# Claude :

🎯 **Voilà le vrai problème !**

L'URL utilisée par fast-flights (`?q=Flights+from+CDG+to+CUZ...`) est une **recherche en langage naturel** que Google parse de manière imparfaite — surtout pour les destinations exotiques comme Cusco. Souvent, Google ne reconnaît pas le code IATA `CUZ` dans cette URL et affiche "no results".

L'URL qui **marche** dans ton navigateur (`/travel/flights/search?tfs=CBwQAhojEgo...`) utilise un format protobuf encodé en base64 (`tfs=...`) qui spécifie sans ambiguïté :

- Aéroports par code IATA précis
- Dates exactes
- Type de voyage
- Etc.

C'est ce que **fast-flights v3** utilise (le tfs encodé), mais que **fast-flights v2** ne fait pas correctement pour certaines destinations.

**Vérifions ce que fast-flights envoie**

Pour confirmer, ajoute du debug dans le patch pour voir l'URL utilisée :

```python
# Dans fast_flights_patch.py, modifie la fonction patched
async def fetch_with_playwright_patched(url: str) -> str:
    print(f"      🔗 URL fast-flights : {url[:200]}")
    # ... reste du code
```

Lance un test minimal et tu verras l'URL réelle.

**3 solutions possibles**

🎯 **Solution A : Migrer vers fast-flights v3 (avec patch consent)**

La v3 utilise le format `tfs=` correct. On l'avait écartée car elle était en RC, mais on peut retenter.

```bash
uv pip install "fast-flights>=3.0rc0" --prerelease=allow
```

⚠️ Mais l'API v3 est différente (`FlightQuery`, `create_query`, `get_flights`), il faudrait adapter le code.

🎯 **Solution B : Patcher fast-flights v2 pour utiliser le format `tfs=`**

Plus complexe : il faut générer le protobuf encodé en base64 nous-même. C'est ce que fait la v3 en interne.

🎯 **Solution C : Forcer fast-flights à utiliser `Airport.PARIS_CHARLES_DE_GAULLE` au lieu de "CDG"**

Parfois le problème vient de l'utilisation des codes IATA bruts. fast-flights expose un enum `Airport` qui peut générer une URL plus propre. Mais ça ne résout pas pour CUZ qui n'est probablement pas dans l'enum.

🎯 **Solution D : Bypasser fast-flights et faire le scraping directement**

On utilise Playwright nous-même avec l'URL `tfs=...` qui marche, et on parse le DOM. Plus de boulot, mais on contrôle tout.

---

**Vérifions d'abord la v3**

Vu que tu as déjà investi dans le projet, la solution propre c'est d'aller en v3. L'API change un peu mais c'est bien plus robuste.

**Étape 1 : tester si la v3 marche maintenant**

```bash
# Backup actuel au cas où
cp -r .venv .venv.v2.backup

# Installer la v3
uv add "fast-flights==3.0rc0" --prerelease=allow

# Vérifier l'API exposée
uv run python -c "import fast_flights; print(dir(fast_flights))"
```

**Étape 2 : test minimal avec la v3**

```bash
uv run python -c "
from fast_flights import (
    FlightQuery,
    Passengers,
    create_query,
    get_flights,
)
import time

start = time.time()
try:
    query = create_query(
        flights=[
            FlightQuery(date='2026-07-03', from_airport='CDG', to_airport='CUZ'),
            FlightQuery(date='2026-07-27', from_airport='CUZ', to_airport='CDG'),
        ],
        seat='economy',
        trip='round-trip',
        passengers=Passengers(adults=1),
    )
    result = get_flights(query)
    elapsed = time.time() - start
    print(f'OK en {elapsed:.1f}s : {len(result.flights)} vols')
    if result.flights:
        for f in result.flights[:3]:
            print(f'  {f.name}: {f.price}')
except Exception as e:
    elapsed = time.time() - start
    print(f'Erreur après {elapsed:.1f}s : {type(e).__name__}: {str(e)[:200]}')
"
```

Si ça marche → on adapte le code pour la v3. Si ça plante → on reste en v2 et on fait la solution D.

**Si la v3 ne marche toujours pas**

Le problème est tel que **fast-flights ne supporte pas bien les destinations exotiques** dans sa version stable. Solution la plus pragmatique : **Solution D** (Playwright direct).

Voici un POC à essayer pour CUZ :

```python
"""POC : scraping direct avec l'URL tfs= qui marche"""

import asyncio
from playwright.async_api import async_playwright


async def fetch_cuz():
    # URL qui marche dans le navigateur
    url = "https://www.google.com/travel/flights/search?tfs=CBwQAhojEgoyMDI2LTA3LTAzagcIARIDQ0RHcgwIAxIIL20vMGpsZDMaIxIKMjAyNi0wNy0yN2oMCAMSCC9tLzBqbGQzcgcIARIDQ0RHQAFIAXABggELCP___________wGYAQE&tfu=EgYIABAAGAA&hl=en"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
            )
            await context.add_cookies([
                {
                    "name": "CONSENT",
                    "value": "YES+cb.20210720-07-p0.en+FX+410",
                    "domain": ".google.com",
                    "path": "/",
                },
            ])

            page = await context.new_page()
            await page.goto(url, timeout=15000)

            # Essai de plusieurs sélecteurs
            for selector in [".eQ35Ce", ".pIav2d", "[role='list']"]:
                try:
                    await page.locator(selector).first.wait_for(timeout=5000)
                    print(f"✅ Sélecteur trouvé : {selector}")
                    break
                except:
                    print(f"❌ Sélecteur absent : {selector}")

            html = await page.content()
            print(f"\n📄 HTML reçu : {len(html)} caractères")

            # Sauve dans un fichier pour inspection
            with open("/tmp/cuz_page.html", "w") as f:
                f.write(html)
            print(f"💾 HTML sauvé dans /tmp/cuz_page.html")

        finally:
            await browser.close()


asyncio.run(fetch_cuz())
```

```bash
uv run python poc_cuz.py
```

Si la page contient des vols (cherche "€" ou "$" dans le HTML), on saura qu'on peut bypasser fast-flights et scraper directement avec une URL tfs valide.

⚠️ Le piège : **l'URL tfs encode les paramètres de manière protobuf**. On peut pas juste copier-coller des URLs, il faudrait pouvoir les générer dynamiquement pour chaque combinaison. C'est exactement ce que fait la v3 en interne.

---

**Ma reco pragmatique**

Vu où tu en es :

1. **Stoppe le scan actuel** (au moins sauve les LIM qui marchent)
2. **Lance le test v3** ci-dessus
3. **Si v3 marche** : on migre, c'est 30 min de boulot pour adapter le code

**Une question clé**

Quand tu as vu que LIM, BRU→LIM, CDG→LIM marchent en v2, tu as quand même de bonnes données. Pour le Pérou, **Lima est de toute façon le hub principal** et la majorité des vols Europe→Pérou y atterrissent. Atterrir à CUZ ou AQP direct c'est rare et souvent peu intéressant (à cause de l'altitude pour CUZ).

Tu peux décider que **scanner uniquement LIM + planifier des vols intérieurs séparés à 60-80€ sur LATAM Perú ou Sky Airline** est la bonne stratégie. Tu économises des heures de debug pour un gain marginal.

**Action immédiate**

1. Stoppe le scan
2. Sauve le `data/google_flights.csv` actuel quelque part (`cp data/google_flights.csv data/google_flights_partial.csv`)
3. **Teste la v3** avec le snippet ci-dessus
4. Reviens-moi avec ce que retourne le test

Selon le résultat, on choisit la suite. Vu l'heure qu'il est et que tu pars dans plusieurs mois (septembre-octobre), tu n'es pas dans l'urgence. Mais on est proches de la solution.
