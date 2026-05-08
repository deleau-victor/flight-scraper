"""Aggrège les résultats des scrapers et fait le ranking final"""

from collections import defaultdict

from rich.rule import Rule

from models import FlightOffer
from display import get_console


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
