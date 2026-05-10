from datetime import date
from scrapers.calendar_picker_scraper import CalendarCell


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
