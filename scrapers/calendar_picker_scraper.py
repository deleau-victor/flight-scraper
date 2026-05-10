"""Phase 1 scraper : matrice calendaire Google Flights via XHR interception.

Endpoint cible :
    POST https://www.google.com/_/FlightsFrontendUi/data/
         travel.frontend.flights.FlightsFrontendService/GetCalendarGrid

Format de réponse : voir spec docs/superpowers/specs/2026-05-10-calendar-picker-design.md
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CalendarCell:
    """Une cellule de la matrice calendaire : un couple (aller, retour) avec son prix."""
    date_aller: date
    date_retour: date
    dep: str
    arrival: str
    prix: float
    deeplink_token: str = ""
