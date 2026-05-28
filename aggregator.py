"""Aggrège les résultats des scrapers et fait le ranking final"""

from collections import defaultdict
from datetime import date

from rich.rule import Rule

from config import (
    START_DATE, END_DATE, TRIP_DURATIONS,
    ALLOWED_DEPARTURE_WEEKDAYS, ALLOWED_RETURN_WEEKDAYS,
    MIN_PRICE, MAX_PRICE,
)
from models import FlightOffer
from display import get_console


def filter_flights_by_config(flights: list[FlightOffer]) -> list[FlightOffer]:
    """Filtre des FlightOffer (typiquement rechargés d'un CSV) selon la config
    courante : date range, durées autorisées, weekdays autorisés, fenêtre de prix.

    Nécessaire après `load_flights_from_csv` car le CSV peut contenir des données
    historiques générées avec un autre `START_DATE`/`END_DATE`. La pipeline live
    génère déjà de la donnée filtrée à la source (via `generate_combinations` ou
    `filter_and_select_top_n`), donc le filtre n'a pas à y être appelé.
    """
    out = []
    for f in flights:
        try:
            da = date.fromisoformat(f.depart_date)
            dr = date.fromisoformat(f.retour_date)
        except (ValueError, TypeError):
            continue
        if da < START_DATE or dr > END_DATE:
            continue
        if (dr - da).days not in TRIP_DURATIONS:
            continue
        if da.weekday() not in ALLOWED_DEPARTURE_WEEKDAYS:
            continue
        if dr.weekday() not in ALLOWED_RETURN_WEEKDAYS:
            continue
        if not (MIN_PRICE < f.prix_billet < MAX_PRICE):
            continue
        out.append(f)
    return out


def deduplicate(flights: list[FlightOffer]) -> list[FlightOffer]:
    grouped = defaultdict(list)

    for f in flights:
        first_airline = f.compagnies.split(",")[0].split("+")[0].strip().lower()
        price_bucket = round(f.prix_billet / 20) * 20
        key = (
            f.depart_date, f.retour_date,
            f.from_airport, f.to_airport,
            first_airline, price_bucket,
        )
        grouped[key].append(f)

    deduplicated = []
    for key, group in grouped.items():
        if len(group) == 1:
            deduplicated.append(group[0])
        else:
            google_versions = [f for f in group if f.source == "google_flights"]
            if google_versions:
                deduplicated.append(min(google_versions, key=lambda x: x.score))
            else:
                deduplicated.append(min(group, key=lambda x: x.score))

    return deduplicated


def aggregate_and_rank(
    google_flights: list[FlightOffer],
    self_transfer_flights: list[FlightOffer],
) -> list[FlightOffer]:
    console = get_console()
    console.print()
    console.print(Rule("🔀 AGGREGATION & RANKING", style="bold cyan"))

    console.print(f"📥 Google Flights         : [cyan]{len(google_flights)}[/cyan] offres")
    console.print(f"📥 Self-transfer construit : [magenta]{len(self_transfer_flights)}[/magenta] offres")

    all_flights = google_flights + self_transfer_flights
    console.print(f"📊 Total avant dédup : [cyan]{len(all_flights)}[/cyan]")

    deduplicated = deduplicate(all_flights)
    n_dups = len(all_flights) - len(deduplicated)
    console.print(
        f"✨ Total après dédup : [green bold]{len(deduplicated)}[/green bold]"
        f" ([dim]{n_dups} doublons[/dim])"
    )

    deduplicated.sort(key=lambda f: f.score)

    return deduplicated
