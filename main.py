"""Orchestrateur principal"""

import fast_flights_patch  # noqa: F401  — DOIT être en premier (monkey-patch)

import os
import sys
from config import (
    GOOGLE_FLIGHTS_CSV, SELF_TRANSFER_CSV, FINAL_RANKING_CSV, DATA_DIR,
)
from models import save_flights_to_csv, load_flights_from_csv
from scrapers.fast_flights_scraper import run_google_flights_scraper
from scrapers.self_transfer_builder import run_self_transfer_builder
from aggregator import aggregate_and_rank
from reporting import print_final_report


def main():
    """Run complet : Google Flights + Self-transfer + ranking"""
    os.makedirs(DATA_DIR, exist_ok=True)
    
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


def main_google_only():
    """Lance uniquement Google Flights, agrège avec self-transfer existant si présent"""
    os.makedirs(DATA_DIR, exist_ok=True)
    
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
    print(f"\n\n✅ Terminé. CSVs disponibles dans {DATA_DIR}/")


def main_self_transfer_only():
    """Lance uniquement le self-transfer (utilise google_flights.csv existant)"""
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
    """Recharge les CSVs et refait juste le ranking (instantané)"""
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
    print("  python main.py                       # Run complet")
    print("  python main.py --google-only         # Google Flights uniquement")
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