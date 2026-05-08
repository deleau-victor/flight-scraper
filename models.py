"""Modèle de données unifié pour tous les scrapers"""

from dataclasses import dataclass, asdict
import csv
import os


@dataclass
class FlightOffer:
    source: str
    
    depart_date: str
    depart_jour: str
    retour_date: str
    retour_jour: str
    nuits: int
    
    from_airport: str
    to_airport: str
    
    prix_billet: float
    transport_cost: int
    arrival_transport_cost: int
    prix_total: float
    prix_str: str
    
    compagnies: str
    escale: str
    duree_min: int
    duree_fmt: str
    nb_escales: int
    
    depart_h: str = ""
    arrivee_h: str = ""
    j_plus: str = ""
    
    is_best: bool = False
    self_transfer: bool = False
    booking_url: str = ""
    tendance: str = ""
    legs_detail: str = ""
    
    score: float = 0.0


def save_flights_to_csv(flights: list[FlightOffer], filepath: str):
    if not flights:
        return
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=asdict(flights[0]).keys())
        writer.writeheader()
        for flight in flights:
            writer.writerow(asdict(flight))


def load_flights_from_csv(filepath: str) -> list[FlightOffer]:
    if not os.path.exists(filepath):
        return []
    
    flights = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["nuits"] = int(row["nuits"])
            row["prix_billet"] = float(row["prix_billet"])
            row["transport_cost"] = int(row["transport_cost"])
            row["arrival_transport_cost"] = int(row.get("arrival_transport_cost", 0))
            row["prix_total"] = float(row["prix_total"])
            row["duree_min"] = int(row["duree_min"])
            row["nb_escales"] = int(row["nb_escales"])
            row["is_best"] = row["is_best"] == "True"
            row["self_transfer"] = row["self_transfer"] == "True"
            row["score"] = float(row["score"])
            flights.append(FlightOffer(**row))
    
    return flights