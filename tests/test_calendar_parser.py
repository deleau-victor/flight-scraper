from datetime import date
from scrapers.calendar_picker_scraper import CalendarCell, strip_xssi_prefix


def test_calendar_cell_dataclass_fields():
    cell = CalendarCell(
        date_aller=date(2026, 8, 30),
        date_retour=date(2026, 8, 31),
        dep="CDG",
        arrival="LIM",
        prix=1107.0,
        deeplink_token="abc123",
    )
    assert cell.date_aller == date(2026, 8, 30)
    assert cell.prix == 1107.0
    assert cell.deeplink_token == "abc123"


def test_strip_xssi_prefix_present():
    raw = ")]}'\n7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"


def test_strip_xssi_prefix_absent():
    raw = "7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"


def test_strip_xssi_prefix_with_extra_newlines():
    raw = ")]}'\n\n\n7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"
