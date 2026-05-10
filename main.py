"""Orchestrateur principal"""

import fast_flights_patch  # noqa: F401  — DOIT être en premier (monkey-patch)

import asyncio
import os
import sys
from config import (
    GOOGLE_FLIGHTS_CSV, SELF_TRANSFER_CSV, FINAL_RANKING_CSV, DATA_DIR,
    USE_CALENDAR_PHASE, TOP_COMBOS_PHASE2,
)
from models import save_flights_to_csv, load_flights_from_csv
from scrapers.fast_flights_scraper import run_google_flights_scraper
from scrapers.self_transfer_builder import run_self_transfer_builder
from aggregator import aggregate_and_rank
from reporting import print_final_report


def _run_phase1_then_phase2() -> list:
    """Phase 1 (calendar matrix) → filter → top-N → Phase 2 (fast-flights ciblé)."""
    from prefilter import prefilter_routes_async
    from scrapers.calendar_picker_scraper import (
        run_calendar_picker_scraper_async, filter_and_select_top_n,
    )

    async def _phase1():
        valid_routes = await prefilter_routes_async()
        cells = await run_calendar_picker_scraper_async(valid_routes)
        return cells

    cells = asyncio.run(_phase1())

    if not cells:
        print("\n⚠️  Phase 1 a retourné 0 cellule pour TOUTES les routes.")
        print("    Le DOM Google a peut-être changé. Relance en mode legacy :")
        print("        python main.py --legacy")
        return []

    combos = filter_and_select_top_n(cells, top_n=TOP_COMBOS_PHASE2)
    print(f"\n🎯 Phase 1 → Phase 2 : {len(combos)} combos sélectionnés "
          f"(top-{TOP_COMBOS_PHASE2}/route après filtre weekday/durée/prix)")

    if not combos:
        print("⚠️  0 combo après filtrage. Vérifie ALLOWED_DEPARTURE_WEEKDAYS, "
              "ALLOWED_RETURN_WEEKDAYS, TRIP_DURATIONS, MIN/MAX_PRICE.")
        return []

    return run_google_flights_scraper(combos_override=combos)


def main():
    """Run complet : Phase 1 calendar → Phase 2 fast-flights → self-transfer → ranking"""
    os.makedirs(DATA_DIR, exist_ok=True)

    if USE_CALENDAR_PHASE:
        google_results = _run_phase1_then_phase2()
    else:
        google_results = run_google_flights_scraper()

    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)
    print(f"💾 Google Flights sauvé : {GOOGLE_FLIGHTS_CSV}")

    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)
    print(f"💾 Self-transfer sauvé : {SELF_TRANSFER_CSV}")

    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print(f"💾 Ranking final sauvé : {FINAL_RANKING_CSV}")

    print_final_report(final)
    print(f"\n\n✅ Terminé. CSVs disponibles dans {DATA_DIR}/")


def main_legacy():
    """Pipeline legacy : skip Phase 1, fast-flights sur toutes les combinaisons."""
    os.makedirs(DATA_DIR, exist_ok=True)
    google_results = run_google_flights_scraper()
    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)

    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)

    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_calendar_only():
    """Phase 1 seule. Dump CSV des cellules brutes (debug / scouting)."""
    import csv
    from prefilter import prefilter_routes_async
    from scrapers.calendar_picker_scraper import run_calendar_picker_scraper_async

    os.makedirs(DATA_DIR, exist_ok=True)

    async def _go():
        valid_routes = await prefilter_routes_async()
        return await run_calendar_picker_scraper_async(valid_routes)

    cells = asyncio.run(_go())

    out_path = f"{DATA_DIR}/calendar_matrix.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "dep", "arrival", "date_aller", "date_retour", "duration",
            "prix", "weekday_aller", "weekday_retour", "deeplink_token",
        ])
        for c in cells:
            writer.writerow([
                c.dep, c.arrival, c.date_aller.isoformat(), c.date_retour.isoformat(),
                (c.date_retour - c.date_aller).days, c.prix,
                c.date_aller.weekday(), c.date_retour.weekday(), c.deeplink_token,
            ])
    print(f"\n💾 {len(cells)} cellules sauvées dans {out_path}")


def main_google_only():
    os.makedirs(DATA_DIR, exist_ok=True)

    if USE_CALENDAR_PHASE:
        google_results = _run_phase1_then_phase2()
    else:
        google_results = run_google_flights_scraper()

    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)
    print(f"💾 Google Flights sauvé : {GOOGLE_FLIGHTS_CSV}")

    self_transfer_results = load_flights_from_csv(SELF_TRANSFER_CSV)
    if self_transfer_results:
        print(f"📂 Self-transfer rechargé depuis CSV : {len(self_transfer_results)} offres")
    else:
        print("ℹ️  Pas de self-transfer.csv, ranking basé uniquement sur Google Flights")

    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print(f"💾 Ranking final sauvé : {FINAL_RANKING_CSV}")
    print_final_report(final)


def main_self_transfer_only():
    google_results = load_flights_from_csv(GOOGLE_FLIGHTS_CSV)
    if not google_results:
        print("❌ Pas de CSV Google Flights, lance d'abord le run complet ou --google-only")
        return
    print(f"📂 {len(google_results)} résultats Google chargés")

    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)

    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_from_csv():
    google_results = load_flights_from_csv(GOOGLE_FLIGHTS_CSV)
    self_transfer_results = load_flights_from_csv(SELF_TRANSFER_CSV)
    print(f"📂 Rechargement : {len(google_results)} Google + {len(self_transfer_results)} Self-transfer")

    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_clear_cache():
    from cache import clear_cache
    clear_cache()


def main_force_prefilter():
    from prefilter import prefilter_routes
    prefilter_routes(force_refresh=True)


def main_cache_stats():
    from cache import cache_stats
    cache_stats()


def print_usage():
    print("Usage:")
    print("  python main.py                       # Run complet (Phase 1 calendar + Phase 2 fast-flights + self-transfer)")
    print("  python main.py --legacy              # Pipeline legacy (skip Phase 1)")
    print("  python main.py --calendar-only       # Phase 1 seule, dump calendar_matrix.csv")
    print("  python main.py --google-only         # Google Flights uniquement (utilise Phase 1 si activée)")
    print("  python main.py --self-transfer-only  # Self-transfer uniquement")
    print("  python main.py --from-csv            # Re-rank depuis CSVs (instantané)")
    print("  python main.py --clear-cache         # Vide le cache")
    print("  python main.py --force-prefilter     # Force un nouveau préfiltrage")
    print("  python main.py --cache-stats         # Stats du cache")
    print("  python main.py --help                # Cette aide")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--from-csv":
            main_from_csv()
        elif cmd == "--self-transfer-only":
            main_self_transfer_only()
        elif cmd == "--google-only":
            main_google_only()
        elif cmd == "--legacy":
            main_legacy()
        elif cmd == "--calendar-only":
            main_calendar_only()
        elif cmd == "--clear-cache":
            main_clear_cache()
        elif cmd == "--force-prefilter":
            main_force_prefilter()
        elif cmd == "--cache-stats":
            main_cache_stats()
        elif cmd in ("-h", "--help"):
            print_usage()
        else:
            print(f"❌ Commande inconnue : {cmd}\n")
            print_usage()
    else:
        main()
