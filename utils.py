"""Helpers partagés"""

import re
from datetime import date, datetime, timedelta
from config import (
    START_DATE, END_DATE, TRIP_DURATIONS,
    ALLOWED_DEPARTURE_WEEKDAYS, ALLOWED_RETURN_WEEKDAYS,
    DEPARTURE_AIRPORTS, DEPARTURE_AIRPORTS_COST,
    ARRIVAL_AIRPORTS, ARRIVAL_AIRPORTS_TRANSPORT_COST,
    COST_PER_HOUR_OVER_REF, DURATION_REFERENCE_HOURS,
    COST_PER_EXTRA_STOP, SELF_TRANSFER_PENALTY,
)


AIRLINE_HUBS = {
    "Iberia": "Madrid (MAD)",
    "Air Europa": "Madrid (MAD)",
    "Vueling": "Barcelone (BCN)",
    "LEVEL": "Barcelone (BCN)",
    "KLM": "Amsterdam (AMS)",
    "Air France": "Paris (CDG)",
    "Lufthansa": "Francfort (FRA) / Munich (MUC)",
    "United": "Houston (IAH) / Newark (EWR)",
    "Aeromexico": "Mexico (MEX)",
    "LATAM": "Madrid (MAD) / São Paulo (GRU)",
    "Avianca": "Bogotá (BOG)",
    "Air Canada": "Montréal (YUL) / Toronto (YYZ)",
    "Air Transat": "Montréal (YUL)",
    "Delta": "Atlanta (ATL) / NYC (JFK)",
    "American": "Miami (MIA) / Dallas (DFW)",
    "TAP": "Lisbonne (LIS)",
    "Copa": "Panama (PTY)",
    "British Airways": "Londres (LHR)",
    "Iberojet": "Madrid (MAD)",
    "Brussels Airlines": "Bruxelles (BRU)",
    "Ryanair": "Low-cost",
    "Wizz Air": "Low-cost",
    "easyJet": "Low-cost",
    "Transavia": "Low-cost",
    "TUI": "Low-cost",
    "Air Serbia": "Belgrade (BEG)",
}


def infer_layover(airline_name: str) -> str:
    if not airline_name:
        return "?"
    
    airlines = [a.strip() for a in airline_name.split(",")]
    
    hubs = []
    for airline in airlines:
        for known, hub in AIRLINE_HUBS.items():
            if known.lower() in airline.lower():
                hubs.append(hub)
                break
    
    unique_hubs = list(dict.fromkeys(hubs))
    
    if not unique_hubs:
        return f"? ({airline_name})"
    return " → ".join(unique_hubs)


def parse_price(price_str) -> float:
    if not price_str or price_str == 0:
        return float('inf')
    if isinstance(price_str, (int, float)):
        return float(price_str)
    cleaned = str(price_str).replace(',', '').replace(' ', '')
    match = re.search(r'[\d.]+', cleaned)
    return float(match.group()) if match else float('inf')


def parse_duration_to_minutes(duration_str) -> int:
    if not duration_str:
        return 0
    if isinstance(duration_str, (int, float)):
        return int(duration_str)
    h_match = re.search(r'(\d+)\s*(?:hr|h)', str(duration_str))
    m_match = re.search(r'(\d+)\s*(?:min|m)', str(duration_str))
    h = int(h_match.group(1)) if h_match else 0
    m = int(m_match.group(1)) if m_match else 0
    return h * 60 + m


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


def parse_time_str(time_str: str, year: int = 2026) -> datetime | None:
    if not time_str:
        return None
    try:
        parts = str(time_str).split(" on ")
        if len(parts) != 2:
            return None
        time_part, date_part = parts
        date_clean = date_part.split(", ", 1)[1] if ", " in date_part else date_part
        full_str = f"{time_part.strip()} {date_clean.strip()} {year}"
        return datetime.strptime(full_str, "%I:%M %p %b %d %Y")
    except (ValueError, IndexError):
        return None


def calculate_layover_minutes(arrival_str: str, departure_str: str) -> int | None:
    arr = parse_time_str(arrival_str)
    dep = parse_time_str(departure_str)
    if not arr or not dep:
        return None
    delta = dep - arr
    minutes = int(delta.total_seconds() / 60)
    if minutes < 0:
        return None
    return minutes


def get_transport_cost(dep_airport: str) -> int:
    return DEPARTURE_AIRPORTS_COST.get(dep_airport, 0)


def get_arrival_transport_cost(arrival_airport: str) -> int:
    return ARRIVAL_AIRPORTS_TRANSPORT_COST.get(arrival_airport, 0)


def calculate_score(
    prix: float, duree_min: int, escales: int, 
    dep_airport: str, arrival_airport: str = None,
    self_transfer: bool = False,
) -> float:
    if prix == float('inf'):
        return float('inf')
    
    duree_h = duree_min / 60
    
    duree_penalty = max(0, (duree_h - DURATION_REFERENCE_HOURS) * COST_PER_HOUR_OVER_REF)
    escale_penalty = max(0, escales - 1) * COST_PER_EXTRA_STOP
    transport_cost = get_transport_cost(dep_airport)
    arrival_cost = get_arrival_transport_cost(arrival_airport) if arrival_airport else 0
    self_transfer_pen = SELF_TRANSFER_PENALTY if self_transfer else 0
    
    return (
        prix + duree_penalty + escale_penalty + 
        transport_cost + arrival_cost + self_transfer_pen
    )


def generate_combinations() -> list[tuple]:
    """Génère les (date_aller, date_retour, duration, dep, arrival) valides"""
    combos = []
    current = START_DATE
    while current <= END_DATE:
        if current.weekday() in ALLOWED_DEPARTURE_WEEKDAYS:
            for duration in TRIP_DURATIONS:
                return_date = current + timedelta(days=duration)
                if return_date.weekday() in ALLOWED_RETURN_WEEKDAYS:
                    for dep in DEPARTURE_AIRPORTS:
                        for arrival in ARRIVAL_AIRPORTS:
                            combos.append((current, return_date, duration, dep, arrival))
        current += timedelta(days=1)
    return combos