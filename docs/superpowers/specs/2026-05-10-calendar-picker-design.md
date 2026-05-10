# Design — Pivot Calendar Picker (Phase 1 + Phase 2 ciblée)

**Date** : 2026-05-10
**Statut** : design validé, prêt pour writing-plans

## Contexte et motivation

Le pipeline actuel scrape Google Flights via la lib `fast-flights` combo par combo. Avec ~12 routes valides × ~25 combos/route × ~123 jours de plage = **milliers de calls** Playwright. Coût : plusieurs heures de runtime, beaucoup de timeouts sur les routes exotiques (CUZ, AQP), fragilité globale.

**Pivot** : exploiter la matrice calendaire de Google Flights (bouton "Date grid" sur la page de résultats). Cette matrice est rendue dans un `<canvas>` (donc non parsable via DOM), mais elle est alimentée par un endpoint backend `POST .../FlightsFrontendService/GetCalendarGrid` qui retourne ~49 prix structurés par requête. On l'intercepte via Playwright `page.on("response")`, on parse, on slide via les boutons scroll (chaque click = 1 nouveau POST = 1 jour de décalage). Une session browser par route couvre toute la plage [START_DATE, END_DATE].

L'output de la phase 1 (matrices) sert d'**index de prix** pour sélectionner les top-N combos par route, qu'on re-scrape ensuite en détail avec `fast-flights` (phase 2) pour récupérer compagnies/durée/escales.

## Vue d'ensemble du pipeline

```
[main.py]
    │
    ▼
[prefilter] ──► routes valides + hot zones (existant, inchangé)
    │
    ▼
┌─────────────────────────────────────────────┐
│  PHASE 1 — Calendar Picker                  │
│  Pour chaque route valide (≤12) :           │
│   - 1 session Playwright (stealth+consent)  │
│   - URL Google Flights TFS                  │
│   - page.on("response") filtre              │
│       sur **/GetCalendarGrid                │
│   - Click "Date grid" → 1er POST capturé    │
│   - Click "Scroll right/down" en boucle     │
│       (1 click = 1 jour = 1 nouveau POST)   │
│   - Parse XSSI/wrb.fr → CalendarCell        │
│   - Dedup (matrices se chevauchent)         │
│  Cache disque par (route, anchor_date)      │
└─────────────────────────────────────────────┘
    │
    ▼  list[CalendarCell] (date_aller, date_retour, dep, arr, prix)
    │
[filter_and_select_top_n]
    │   Filtre weekday/durée/prix/range → top-N par route
    │
    ▼  list[(date_aller, date_retour, duration, dep, arr)]
    │
┌─────────────────────────────────────────────┐
│  PHASE 2 — fast_flights (existant, ciblé)   │
│  N'itère QUE sur les combos sélectionnés    │
│  par la phase 1 → produit FlightOffer       │
│  enrichis (compagnies, durée, escales).     │
└─────────────────────────────────────────────┘
    │
    ▼
[aggregator] ──► dédup + ranking + score (existant, inchangé)
    │
    ▼
data/final_ranking.csv
```

**Ce qui ne change pas** : `aggregator.py`, `models.py`, `reporting.py`, `display.py`, `self_transfer_builder.py`. Le `prefilter` reste utile en amont pour éliminer les routes mortes avant d'ouvrir des sessions Playwright pour rien.

## Décisions d'architecture clés

### Pas d'extraction du setup Playwright

`fast_flights_patch.py` est strictement **inchangé**. Le nouveau scraper duplique ~40 LOC de stealth/consent/cookies. Raison : le module actuel a résolu un problème difficile (99% des timeouts CUZ/AQP via patch protobuf type=1 + stealth + bypass RGPD), y toucher = risque de régression. Duplication explicite et grep-able > refactor risqué.

### CalendarCell séparé de FlightOffer

`CalendarCell` est de la **donnée intermédiaire** (un index de prix), pas un résultat final. Mélanger avec `FlightOffer` polluerait `models.py` avec des champs vides (compagnies, escale, durée) et brouillerait l'invariant "FlightOffer = vol scrapé en détail".

### Phase 2 reçoit ses combos par injection

`run_google_flights_scraper_async(combos_override=...)` accepte une liste explicite de combos. Si `combos_override is None` → comportement legacy (génère via `generate_combinations()` + prefilter). Si fourni → skip prefilter, scrape uniquement les combos passés. Aucun branching dans `process_combo()`.

### Cache par slide, pas par route

`data/cache/calendar/{dep}_{arr}_{anchor_date}.json` — 1 fichier = 1 slide de matrice (pas la route entière). Bénéfices :

- Étendre `END_DATE` ne re-scrape que les nouvelles slides
- Une slide ratée se retry sans tout reperdre
- Format cohérent avec `round_trip_cache` existant

## Modules

### Nouveau : `scrapers/calendar_picker_scraper.py`

```python
@dataclass
class CalendarCell:
    date_aller: date
    date_retour: date
    dep: str
    arrival: str
    prix: float  # EUR

async def scrape_calendar_for_route(
    dep: str, arrival: str,
    start_anchor: date, end_anchor: date,
) -> list[CalendarCell]:
    """1 session browser. Slide jusqu'à end_anchor. Cache hit/miss par anchor."""

async def run_calendar_picker_scraper_async(
    valid_routes: dict,  # {(dep, arr): {is_valid, hot_zones}}
) -> list[CalendarCell]:
    """Orchestre les routes en parallèle (semaphore PARALLEL_WORKERS).
    Tracker live Rich similaire à ScraperTracker de fast_flights_scraper."""

def run_calendar_picker_scraper(valid_routes) -> list[CalendarCell]:
    """Wrapper sync."""

def filter_and_select_top_n(
    cells: list[CalendarCell],
    top_n: int,
) -> list[tuple[date, date, int, str, str]]:
    """Pipeline :
      1. weekday : date_aller.weekday() ∈ ALLOWED_DEPARTURE_WEEKDAYS
                   date_retour.weekday() ∈ ALLOWED_RETURN_WEEKDAYS
      2. durée  : (date_retour - date_aller).days + 1 ∈ TRIP_DURATIONS
      3. prix   : MIN_PRICE < prix < MAX_PRICE
      4. range  : date_aller >= START_DATE, date_retour <= END_DATE
      5. group by route, sort by prix asc, take [:top_n]
    Retour : tuples au format consommé par fast_flights_scraper.process_combo()."""
```

**Code dupliqué de fast_flights_patch.py (intentionnel)** :

- `REALISTIC_UA`, `_stealth = Stealth()`
- `async_playwright()` + `chromium.launch(args=["--disable-blink-features=AutomationControlled"])`
- `new_context(locale="en-US", timezone_id="America/New_York", user_agent=REALISTIC_UA)`
- `_stealth.apply_stealth_async(context)`
- `add_cookies([CONSENT, SOCS])`
- Fallback consent : `consent_selectors = ["button:has-text('Accept all')", ...]`

**Sélecteurs DOM (confirmés par exploration manuelle)** :

- Bouton "Date grid" : `button[jsname="KqtnKd"]` (préféré, classes obfusquées) ; fallback `button:has(span:has-text("Date grid"))`
- Scroll right (date_aller +1) : `button[aria-label="Scroll right"]` ou `button[jsname="m4eCTc"]`
- Scroll left (date_aller -1) : `button[aria-label="Scroll left"]` ou `button[jsname="PU8vv"]`
- Scroll down (date_retour +1) : `button[aria-label="Scroll down"]` ou `button[jsname="ipHvib"]`
- Scroll up (date_retour -1) : `button[aria-label="Scroll up"]` ou `button[jsname="rFLB0"]`
- La matrice elle-même : `canvas[jsname="qTwgI"][role="grid"][aria-label="Date grid"]` — **non parsable** (canvas), sert uniquement de signal "matrice ouverte".

### Endpoint Google capturé (réseau)

```
POST https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGrid
?f.sid=<dynamic>&bl=<build>&hl=en-US&gl=FR&_reqid=<dynamic>&rt=c
```

Filtre côté Playwright : `if "/GetCalendarGrid" in response.url`.

**Format de réponse** (anti-XSSI + chunked frames) :

```
)]}'
<size_in_bytes>\n
[["wrb.fr", null, "<inner_json_stringified>"]]
<size_in_bytes>\n
[["wrb.fr", null, "<inner_json_stringified>"]]
...
<size_in_bytes>\n
[["di", N], ...]   <- frame metadata, à ignorer
```

**Parsing** (Python pur, ~30 LOC) :

1. Strip prefix `)]}'\n`
2. Lire `<size>\n<frame_text_of_size_bytes>` en boucle
3. Filtrer `frame[0][0] == "wrb.fr"` (skip `di`, `af.httprm`, `e`)
4. Le 3e élément du `wrb.fr` est une **string JSON** : la re-parser
5. La structure interne donne `inner[1]` = liste de cellules

**Format d'une cellule** :

```python
[
  "2026-08-30",                    # date_aller ISO
  "2026-08-31",                    # date_retour ISO
  [[null, 1107], "<deeplink_token>"],  # [[null, prix_eur_int], token_b64]
  1                                # status : 1=valide, 2=invalide
]
```

Pour `status == 2` : la 3e position est `null`, on skip. Le `deeplink_token` est conservé pour usage futur (booking URL Phase 2).

### Stratégie de sliding

Chaque click sur Scroll right/left/up/down déclenche **1 nouveau POST GetCalendarGrid** avec dates décalées de 1 jour dans l'axe correspondant.

Pattern de couverture : on anchor sur `(date_aller=START_DATE, date_retour=START_DATE+24)` (durée milieu de TRIP_DURATIONS), puis on alterne `scroll_right` (avance date_aller) + `scroll_down` (avance date_retour) pour avancer en diagonale. Chaque pair de clicks décale l'anchor de +1 jour dans les 2 axes simultanément, et les matrices de 7×7 produites se chevauchent largement.

Le scraper dédup les cellules par `(date_aller, date_retour)`. Boucle jusqu'à ce que `date_aller >= END_DATE - min(TRIP_DURATIONS)` (= `END_DATE - 21`).

Throttle entre clicks : `random.uniform(CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX)` (1-2.5s).

### Modifié : `scrapers/fast_flights_scraper.py`

Ajout du paramètre `combos_override` :

```python
async def run_google_flights_scraper_async(
    combos_override: list | None = None,
) -> list[FlightOffer]:
    if combos_override is not None:
        combos = combos_override
        # Skip prefilter + generate_combinations
    elif USE_PREFILTER:
        valid_routes = await prefilter_routes_async()
        ...

def run_google_flights_scraper(combos_override=None) -> list[FlightOffer]:
    return asyncio.run(run_google_flights_scraper_async(combos_override))
```

### Étendu : `cache.py`

```python
CALENDAR_CACHE = f"{CACHE_DIR}/calendar"

def _calendar_key(dep: str, arrival: str, anchor_date: date) -> str: ...
def get_calendar_cache(dep, arrival, anchor_date) -> list[dict] | None: ...
def save_calendar_cache(dep, arrival, anchor_date, cells: list[dict]): ...
```

`cache_stats()` étendu pour afficher aussi le compte calendar. `clear_cache()` couvre déjà tout `CACHE_DIR/` (rmtree).

### Étendu : `config.py`

```python
# ============ PHASE 1 — CALENDAR PICKER ============
USE_CALENDAR_PHASE = True
TOP_COMBOS_PHASE2 = 25
CALENDAR_SLIDE_THROTTLE_MIN = 1.0
CALENDAR_SLIDE_THROTTLE_MAX = 2.5
CALENDAR_WAIT_FOR_MATRIX_MS = 8000
```

### Modifié : `main.py`

`main()` réécrit pour orchestrer phase 1 → bridge → phase 2 quand `USE_CALENDAR_PHASE = True`. Nouveaux modes CLI :

```bash
python main.py                  # Run complet (calendar + fast-flights + self-transfer)
python main.py --calendar-only  # NOUVEAU : phase 1 seule, dump CSV des cellules
python main.py --legacy         # NOUVEAU : ancien pipeline (skip calendar phase)
# autres modes inchangés : --google-only, --self-transfer-only, --from-csv,
# --clear-cache, --force-prefilter, --cache-stats
```

`--calendar-only` produit `data/calendar_matrix.csv` (colonnes `dep, arrival, date_aller, date_retour, duration, prix, weekday_aller, weekday_retour`) — utile pour valider la phase 1 visuellement avant de lancer phase 2.

`--legacy` est une escape hatch si Google casse le DOM du Date grid. Le pipeline legacy reste à 100% fonctionnel.

## Gestion des erreurs (phase 1)

| Erreur                                 | Comportement                                                                                                                                                                                                   |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Timeout navigation URL initiale        | Retry 1× puis log + skip route                                                                                                                                                                                 |
| Timeout sur `.eQ35Ce`                  | Retry 1× puis skip route                                                                                                                                                                                       |
| Bouton "Date grid" introuvable         | Erreur fatale : abort phase 1 + log invitant à relancer en `--legacy` (DOM Google a changé). **Pas d'auto-fallback** : on évite de relancer silencieusement des milliers de calls sans consentement explicite. |
| Cellule de prix au format inattendu    | Skip cellule, continue le slide                                                                                                                                                                                |
| Click "next" sans effet sur la matrice | Détection : 1re date affichée identique à l'itération précédente → break (fin de plage atteinte)                                                                                                               |
| Throttle Google / CAPTCHA              | Non géré spécifiquement (rare avec stealth) ; timeout naturel → skip                                                                                                                                           |

**Garde-fou critique** : si phase 1 retourne `[]` pour TOUTES les routes, `main()` log un warning explicite et **n'enchaîne pas sur phase 2**. L'utilisateur est invité à relancer en `--legacy`.

## Tests

Le projet n'a actuellement aucun test. Niveau de test pragmatique pour ce pivot :

1. **Tests unitaires** sur fonctions pures (sans Playwright) :
   - `filter_and_select_top_n()` avec matrice synthétique : vérifier weekday/durée/range/top-N
   - Parse cellule prix : `"€489"`, `"$489"`, `"489 €"`, `""` → float ou skip
   - Cache get/save calendar : roundtrip JSON + TTL expiré
   - Ajouter `pytest` à `pyproject.toml`, créer `tests/test_calendar_picker.py`

2. **Test d'intégration smoke** (optionnel) :
   - 1 route (CDG→LIM), 1 anchor date, vérifier ≥1 cellule retournée dans plage plausible (€400-€2000)
   - Tag `@pytest.mark.network` pour skip en CI

3. **Pas de mocks Playwright** : trop fragiles. Pour tester le parsing sans réseau, stocker des HTML samples dans `tests/fixtures/`.

## Ordre d'implémentation suggéré

(L'exploration DOM/network est déjà faite, cf. `exploration.md` à la racine du projet.)

1. **Parser de réponse `GetCalendarGrid`** (fonction pure, sans Playwright) :
   - Input : la string brute du body de réponse (XSSI + chunked frames)
   - Output : `list[CalendarCell]`
   - Tests unitaires avec une réponse réelle copiée depuis `exploration.md`
2. **Module `calendar_picker_scraper.py`** :
   - Setup Playwright dupliqué (stealth/consent/cookies de `fast_flights_patch.py`)
   - `scrape_calendar_for_route()` : navigate → wait `.eQ35Ce` → set `page.on("response")` filter → click `KqtnKd` → consume 1ère réponse → boucle scroll-right + scroll-down → consume responses → dedup
   - Détection fin de plage : `date_aller_max(matrices) >= END_DATE - min(TRIP_DURATIONS)`
3. **Cache** : `get_calendar_cache` / `save_calendar_cache` dans `cache.py`
4. **Bridge** : `filter_and_select_top_n()` + tests unitaires
5. **Orchestration parallèle** : sémaphore + tracker live Rich + `run_calendar_picker_scraper_async()`
6. **Intégration `main.py`** : `combos_override` dans fast_flights, modes CLI `--calendar-only` / `--legacy`
7. **Config** : ajouts `USE_CALENDAR_PHASE`, `TOP_COMBOS_PHASE2`, etc.
8. **Tests** unitaires (parser + filter_and_select_top_n + cache) + smoke test optionnel
9. **End-to-end** : run complet sur les 12 routes Pérou, comparer avec un run legacy pour vérifier cohérence des prix

## Hors scope

- Le **graphique des prix** mentionné dans `xx.md` (matrices alternatives, tendances) — exploré dans une itération future
- Refactor de `fast_flights_patch.py` ou de l'orchestration existante non liée au pivot
- Tests E2E exhaustifs ou intégration CI
- **Bypass de Playwright** : on garde Playwright pour la v1 (stealth + cookies + click pattern). Voir "Optimisations futures" ci-dessous.

## Optimisations futures (post-v1)

### Pure-httpx vers `GetCalendarGrid`

Une fois le parser de réponse stabilisé, on peut sniffer le **payload POST** (body form-data) d'un seul appel manuel, l'analyser, et appeler `GetCalendarGrid` directement avec `primp.Client(impersonate="chrome_126")` (déjà installé via fast-flights). Gain estimé : **~10× plus rapide**, suppression du browser, pas de canvas, pas de clicks, pas de throttle.

Verrous à lever :
- Le `f.sid` et `_reqid` sont dynamiques par session — il faut les obtenir via une mini-page d'init ou comprendre leur algorithme
- Le `bl=boq_travel-frontend-flights-ui_<date>.<n>_p0` est un identifiant de build front qui change parfois (à scraper depuis la page d'accueil ou hardcoder + détection de changement)
- Les cookies `CONSENT` + `SOCS` doivent être préchargés (déjà connus, cf. `fast_flights_patch.py`)
- Le payload POST contient probablement la route + dates encodées en JSON ou protobuf — à reverse-engineerer

À aborder en sprint séparé une fois la v1 Playwright validée. La v1 n'est pas pénalisée si la v2 ne se fait pas.
