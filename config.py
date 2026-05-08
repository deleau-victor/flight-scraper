"""Configuration partagée entre tous les scrapers"""

from datetime import date

# ============ DATES & DURÉES ============
START_DATE = date(2026, 7, 1)
END_DATE = date(2026, 10, 31)
TRIP_DURATIONS = [21, 22, 23, 24, 25, 26, 27]

# 0=lundi
# 1=mardi
# 2=mercredi
# 3=jeudi
# 4=vendredi
# 5=samedi
# 6=dimanche
ALLOWED_DEPARTURE_WEEKDAYS = [3, 4, 5]
ALLOWED_RETURN_WEEKDAYS = [5, 6, 0]

# ============ AÉROPORTS ============
DEPARTURE_AIRPORTS = ["CDG", "ORY", "BVA", "CRL", "BRU", "AMS"]
ARRIVAL_AIRPORTS = ["LIM", "CUZ", "AQP"]

# Coût d'acheminement A/R depuis ton domicile (€)
DEPARTURE_AIRPORTS_COST = {
    "CDG": 60,
    "ORY": 70,
    "BVA": 80,
    "CRL": 130,
    "BRU": 100,
    "AMS": 150,
}

# Coût d'acheminement local depuis l'aéroport d'arrivée (€)
ARRIVAL_AIRPORTS_TRANSPORT_COST = {
    "LIM": 0,
    "CUZ": 0,
    "AQP": 0,
}

# ============ FILTRES ============
MAX_DURATION_HOURS = 30
MIN_PRICE = 200
MAX_PRICE = 5000

# ============ SCRAPING ============
THROTTLE_MIN = 1
THROTTLE_MAX = 3
TOP_FLIGHTS_PER_COMBO = 3
MAX_RETRIES = 2
SKIP_AIRPORT_AFTER_FAILURES = 3

# ============ PARALLÉLISATION ============
PARALLEL_WORKERS = 4  # 3-4 optimal, plus = risque blocage Google

# ============ CACHE & PRÉFILTRAGE ============
USE_CACHE = True
USE_PREFILTER = True
CACHE_TTL_HOURS = 24
ROUTE_VALIDITY_TTL_DAYS = 7

# ============ SELF-TRANSFER ============
SELF_TRANSFER_HUBS = ["MAD", "AMS", "FRA", "LIS", "BCN"]
MIN_LAYOVER_HOURS = 4
MAX_LAYOVER_HOURS = 28
SELF_TRANSFER_MAX_COMBOS = 30
SELF_TRANSFER_LEGS_PER_SEARCH = 8
SELF_TRANSFER_TEST_DAY_BEFORE = True

# ============ SCORING ============
COST_PER_HOUR_OVER_REF = 30
DURATION_REFERENCE_HOURS = 16
COST_PER_EXTRA_STOP = 100
SELF_TRANSFER_PENALTY = 80

# ============ FICHIERS ============
DATA_DIR = "data"
GOOGLE_FLIGHTS_CSV = f"{DATA_DIR}/google_flights.csv"
SELF_TRANSFER_CSV = f"{DATA_DIR}/self_transfer.csv"
FINAL_RANKING_CSV = f"{DATA_DIR}/final_ranking.csv"