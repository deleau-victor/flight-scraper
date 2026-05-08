Voici un résumé complet pour Claude Code :

---

# Contexte du projet

Scraper Python pour comparer des prix de vols multi-aéroports avec fast-flights (qui scrape Google Flights via Playwright local).
Ici exemple vers le Pérou (LIM, CUZ, AQP)

**Setup actuel** : projet `flight-scraper` géré par `uv`, Python 3.12, fast-flights v2 avec `fetch_mode="local"`. Tourne sur Fedora KDE Wayland.

# État actuel du code

L'utilisateur a une version **simple monolithique** qui fonctionne (Google Flights scraper séquentiel + self-transfer builder + aggregator/ranking). Il a en main une **proposition d'évolution non implémentée** comprenant :

- Async/parallélisation avec `asyncio` (3-4 workers)
- Cache disque JSON (round_trip + one_way) avec TTL 24h
- Préfiltrage des routes pour éliminer celles sans vols
- Multi-aéroports d'arrivée (pas juste LIM)
- Architecture modulaire : `config.py`, `models.py`, `utils.py`, `cache.py`, `prefilter.py`, `aggregator.py`, `main.py`, `scrapers/fast_flights_scraper.py`, `scrapers/self_transfer_builder.py`

# Problèmes identifiés à résoudre

## 1. Timeout Playwright bloque les workers (CRITIQUE)

Quand fast-flights ne trouve pas le sélecteur `.eQ35Ce` (cas où Google Flights affiche une page "no results" différente), il timeout après **30 secondes hardcodées**. Avec 4 workers, chaque timeout bloque un worker pendant 30s, faisant perdre énormément de temps sur les routes rares.

**Solution à implémenter** : patcher fast-flights pour réduire ce timeout à **8-10 secondes**. Le code source est dans `.venv/lib/python3.12/site-packages/fast_flights/local_playwright.py` et utilise `await page.locator(".eQ35Ce").wait_for()` sans timeout custom. Faire un monkey-patch dans un fichier `fast_flights_patch.py` importé en premier dans `main.py`, qui remplace `fast_flights.local_playwright.fetch_with_playwright` par une version qui passe `timeout=10000` au `goto` et au `wait_for`. Ou récupérer le repository fastflight sur github pour l'intégrer au projet et permet une gestion plus fine de ce workaround.

## 2. Préfiltrage trop grossier perd les pépites

Le préfiltrage actuel teste 3 dates par route et marque la route invalide si aucune ne marche.
Problème : certains vols rares (ex: CDG→CUZ via Bogota avec Avianca, 678€) n'existent que sur quelques dates précises et peuvent être ratés.

**Solution à implémenter** : préfiltrage à granularité fine avec **zones chaudes**. Pour chaque route :

- Tester ~12 dates réparties dans la période (au lieu de 3)
- Stocker les dates où des vols ont été trouvés (`valid_test_dates`)
- Calculer des "hot zones" = plages temporelles autour de chaque date validée (rayon ±7 jours, fusion des plages qui se chevauchent)
- Lors du scan principal, ne tester que les combos dont la `date_aller` tombe dans une hot zone de cette route

Le but étant d'essayer de determiner quand ont lieu ses vols en calculant les périodicités ou des patterns afin d'éviter les timeouts.

Stockage dans `data/route_validity.json` avec TTL 7 jours.

## 3. TimeoutError ≠ "no results"

Important : un timeout sur Playwright peut signifier soit "pas de vol pour cette date" soit "page met du temps à charger". Skipper aggressivement risque de perdre les pépites. Donc :

- **Ne pas réduire les retries** systématiquement sur timeout
- **Réduire le timeout** (problème 1) pour que ça ne coûte plus cher de retry
- Combiner avec les hot zones (problème 2) pour ne pas tester inutilement les dates sans vol

## 5. Mauvaise interprétation initiale des `TimeoutError`

J'avais (mal) suggéré que les timeouts venaient de Chromium débordé par 4 workers parallèles. **C'est faux** : ce sont juste des routes rares (CDG/ORY → AQP/CUZ) où Google Flights n'a pas de résultat. Ne pas réduire `PARALLEL_WORKERS` pour ça.

# Configuration utilisateur actuelle

```python
START_DATE = date(2026, 7, 1)
END_DATE = date(2026, 10, 31)
TRIP_DURATIONS = [21, 22, 23, 24, 25, 26, 27]
ALLOWED_DEPARTURE_WEEKDAYS = [3, 4, 5]  # jeu/ven/sam
ALLOWED_RETURN_WEEKDAYS = [5, 6, 0]     # sam/dim/lun
DEPARTURE_AIRPORTS = ["CDG", "ORY", "BVA", "CRL", "BRU", "AMS"]
ARRIVAL_AIRPORTS = ["LIM", "CUZ", "AQP"]
PARALLEL_WORKERS = 4
```

# Ce que je veux

Implémenter le projet en mode **production-ready** avec :

1. La structure modulaire complète (cache, prefilter, scrapers async, aggregator)
2. Le **patch fast-flights** pour ramener le timeout à 10s
3. Le **préfiltrage avec zones chaudes** (12 dates de test, radius 7 jours)
4. Multi-aéroports d'arrivée
5. Self-transfer builder qui exploite le cache one-way

Vérifier d'abord le contenu de `.venv/lib/python3.12/site-packages/fast_flights/local_playwright.py` pour adapter le patch à la vraie signature de la fonction.

Toutes les commandes utiles dans `main.py` : `--google-only`, `--self-transfer-only`, `--from-csv`, `--clear-cache`, `--force-prefilter`, `--cache-stats`.
