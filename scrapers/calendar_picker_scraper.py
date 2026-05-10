"""Phase 1 scraper : matrice calendaire Google Flights via XHR interception.

Endpoint cible :
    POST https://www.google.com/_/FlightsFrontendUi/data/
         travel.frontend.flights.FlightsFrontendService/GetCalendarGrid

Format de réponse : voir spec docs/superpowers/specs/2026-05-10-calendar-picker-design.md
"""

import json
from dataclasses import dataclass
from datetime import date
from typing import Iterator


@dataclass(frozen=True)
class CalendarCell:
    """Une cellule de la matrice calendaire : un couple (aller, retour) avec son prix."""
    date_aller: date
    date_retour: date
    dep: str
    arrival: str
    prix: float
    deeplink_token: str = ""


def strip_xssi_prefix(text: str) -> str:
    """Retire le préfixe anti-XSSI de Google `)]}'` et les newlines en tête."""
    if text.startswith(")]}'"):
        text = text[4:]
    return text.lstrip("\n")


def iter_frames(body: str) -> Iterator[object]:
    """Itère sur les frames JSON d'une réponse Google chunked.

    Format : `<size>\\n<frame_of_size_bytes>` répété.
    Skip silencieusement les frames non-JSON ou les size non-numériques (fin de stream).
    """
    pos = 0
    while pos < len(body):
        # Skip any leading newlines
        while pos < len(body) and body[pos] == '\n':
            pos += 1

        if pos >= len(body):
            return

        nl = body.find("\n", pos)
        if nl == -1:
            return
        size_str = body[pos:nl].strip()
        if not size_str.isdigit():
            return
        size = int(size_str)
        pos = nl + 1
        frame_text = body[pos:pos + size]
        pos += size
        try:
            yield json.loads(frame_text)
        except json.JSONDecodeError:
            continue


def extract_wrb_payload(frame) -> object | None:
    """Extrait le payload JSON imbriqué d'une frame `wrb.fr`.

    Format frame : `[["wrb.fr", null, "<json_stringified>"]]`.
    Retourne None pour les frames non-`wrb.fr` ou malformées.
    """
    if not isinstance(frame, list) or not frame:
        return None
    head = frame[0]
    if not isinstance(head, list) or len(head) < 3 or head[0] != "wrb.fr":
        return None
    inner_str = head[2]
    if not isinstance(inner_str, str):
        return None
    try:
        return json.loads(inner_str)
    except json.JSONDecodeError:
        return None
