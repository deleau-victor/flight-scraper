"""Génère l'URL exacte du scraper pour un combo donné, pour diagnostic manuel.

Usage :
    uv run python debug_failing_url.py AMS AQP 2026-07-03 2026-07-24
    uv run python debug_failing_url.py BRU CUZ 2026-07-03 2026-07-25

Imprime 2 URLs :
1. URL non-patchée (ce que fast-flights v2 enverrait sans nos patches)
2. URL patchée (avec type=1 IATA injecté)

Ouvre les deux dans ton navigateur pour comparer ce que Google retourne.
"""

import base64
import sys
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData


def build_url(tfs_bytes: bytes, path: str = "flights") -> str:
    b64 = base64.b64encode(tfs_bytes).decode()
    return f"https://www.google.com/travel/{path}?tfs={b64}&hl=en&tfu=EgQIABABIgA"


def make_proto(from_a, to_a, d1, d2):
    return TFSData.from_interface(
        flight_data=[
            FlightData(date=d1, from_airport=from_a, to_airport=to_a),
            FlightData(date=d2, from_airport=to_a, to_airport=from_a),
        ],
        trip="round-trip",
        passengers=Passengers(adults=1),
        seat="economy",
        max_stops=None,
    ).to_string()


def main():
    if len(sys.argv) != 5:
        print("Usage: debug_failing_url.py FROM TO DATE_ALLER DATE_RETOUR")
        print("Ex   : debug_failing_url.py AMS AQP 2026-07-03 2026-07-24")
        sys.exit(1)

    from_a, to_a, d1, d2 = sys.argv[1:5]

    # 1. URL ORIGINALE (sans patch type=1)
    raw_orig = make_proto(from_a, to_a, d1, d2)
    url_orig = build_url(raw_orig)

    # 2. URL PATCHÉE (avec type=1)
    import fast_flights_patch  # active les patches
    # Re-fabrique après patch (sinon to_string utilise déjà le patch dans le 1er appel)
    raw_patched = make_proto(from_a, to_a, d1, d2)
    url_patched = build_url(raw_patched)

    # 3. URL avec /search path (variation à tester)
    url_search = build_url(raw_patched, path="flights/search")

    print(f"=== {from_a}→{to_a} round-trip {d1} → {d2} ===\n")
    print(f"1. URL ORIGINALE (sans type=1, ce que v2 envoie nativement) :")
    print(f"   {url_orig}\n")
    print(f"2. URL PATCHÉE (avec type=1 IATA injecté) :")
    print(f"   {url_patched}\n")
    print(f"3. URL PATCHÉE + path /flights/search :")
    print(f"   {url_search}\n")
    print("Ouvre les 3 URLs dans ton navigateur. Regarde laquelle (s'il y en a) affiche des vols.")
    print("Si AUCUNE n'affiche de vols → Google n'a pas de round-trip pour ces dates.")
    print("Si l'URL #2 affiche des vols → notre scraper devrait marcher mais quelque chose")
    print("    bloque côté Playwright (peut-être anti-bot, ou timeout).")


if __name__ == "__main__":
    main()
