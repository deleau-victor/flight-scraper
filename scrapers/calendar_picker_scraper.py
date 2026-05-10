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


def extract_cells(payload, dep: str, arrival: str) -> list[CalendarCell]:
    """Extrait les CalendarCell d'un payload wrb.fr (parsé via extract_wrb_payload).

    Format cellule : [date_aller_iso, date_retour_iso, [[null, prix_int], token], status]
    status == 1 → valide ; 2 → invalide (prix slot = null).
    """
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    cells_data = payload[1]
    if not isinstance(cells_data, list):
        return []

    out = []
    for entry in cells_data:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        date_aller_str, date_retour_str, price_data, status = entry[:4]
        if status != 1 or not price_data:
            continue
        try:
            prix = price_data[0][1]
        except (IndexError, TypeError):
            continue
        if prix is None:
            continue
        try:
            token = price_data[1] if len(price_data) > 1 else ""
        except (IndexError, TypeError):
            token = ""
        try:
            d_aller = date.fromisoformat(date_aller_str)
            d_retour = date.fromisoformat(date_retour_str)
        except (ValueError, TypeError):
            continue
        out.append(CalendarCell(
            date_aller=d_aller,
            date_retour=d_retour,
            dep=dep,
            arrival=arrival,
            prix=float(prix),
            deeplink_token=token if isinstance(token, str) else "",
        ))
    return out
