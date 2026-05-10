# Design — Pivot Calendar Picker (Phase 1 + Phase 2 ciblée)

**Date** : 2026-05-10
**Statut** : design validé, prêt pour writing-plans

## Contexte et motivation

Le pipeline actuel scrape Google Flights via la lib `fast-flights` combo par combo. Avec ~12 routes valides × ~25 combos/route × ~123 jours de plage = **milliers de calls** Playwright. Coût : plusieurs heures de runtime, beaucoup de timeouts sur les routes exotiques (CUZ, AQP), fragilité globale.

**Pivot** : exploiter la matrice calendaire de Google Flights (bouton "Date grid" sur la page de résultats). Cette matrice retourne 7×7 = 49 prix par requête pour une route donnée. En slidant via les boutons next/prev, on couvre toute la plage [START_DATE, END_DATE] en **1 session browser par route**.

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
│   - 1 session Playwright                    │
│   - URL Google Flights TFS                  │
│   - Click bouton "Date grid"                │
│   - Slide via next/prev jusqu'à END_DATE    │
│   - Parse matrice 7×7 → liste de cellules   │
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

**Sélecteurs DOM** :
- Bouton matrice : `button:has-text("Date grid")` + fallback `button[aria-label*="Date grid" i]`
- Cellules de prix, boutons next/prev : **à découvrir** lors de la première étape d'implémentation (micro-exploration via `debug_visual.py` ou Playwright headed mode).

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

| Erreur | Comportement |
|---|---|
| Timeout navigation URL initiale | Retry 1× puis log + skip route |
| Timeout sur `.eQ35Ce` | Retry 1× puis skip route |
| Bouton "Date grid" introuvable | Erreur fatale : abort phase 1 + log invitant à relancer en `--legacy` (DOM Google a changé). **Pas d'auto-fallback** : on évite de relancer silencieusement des milliers de calls sans consentement explicite. |
| Cellule de prix au format inattendu | Skip cellule, continue le slide |
| Click "next" sans effet sur la matrice | Détection : 1re date affichée identique à l'itération précédente → break (fin de plage atteinte) |
| Throttle Google / CAPTCHA | Non géré spécifiquement (rare avec stealth) ; timeout naturel → skip |

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

1. **Découverte DOM** : ouvrir Google Flights manuellement via `debug_visual.py` ou Playwright headed, identifier les sélecteurs (cellules matrice, next/prev buttons). Sans ça, le scraper est aveugle.
2. **Module `calendar_picker_scraper.py`** :
   - Setup Playwright dupliqué
   - `scrape_calendar_for_route()` (single route, no cache)
   - Parse matrice → CalendarCell
   - Slide loop avec détection fin de plage
3. **Cache** : `get_calendar_cache` / `save_calendar_cache` dans `cache.py`
4. **Bridge** : `filter_and_select_top_n()` + tests unitaires
5. **Orchestration parallèle** : sémaphore + tracker live + `run_calendar_picker_scraper_async()`
6. **Intégration `main.py`** : `combos_override` dans fast_flights, modes CLI `--calendar-only` / `--legacy`
7. **Config** : ajouts `USE_CALENDAR_PHASE`, `TOP_COMBOS_PHASE2`, etc.
8. **Tests** unitaires + smoke test
9. **End-to-end** : run complet sur les 12 routes Pérou, comparer avec un run legacy en parallèle pour vérifier la cohérence des prix

## Hors scope

- Le **graphique des prix** mentionné dans `xx.md` (matrices alternatives, tendances) — exploré dans une itération future
- Refactor de `fast_flights_patch.py` ou de l'orchestration existante non liée au pivot
- Migration vers une API directe Google Flights (httpx) — Playwright reste le mécanisme
- Tests E2E exhaustifs ou intégration CI
