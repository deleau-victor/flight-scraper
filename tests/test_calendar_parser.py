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


from scrapers.calendar_picker_scraper import iter_frames


def test_iter_frames_two_frames():
    body = '7\n["a",1]\n5\n["b"]'
    frames = list(iter_frames(body))
    assert frames == [["a", 1], ["b"]]


def test_iter_frames_skips_invalid_size_line():
    body = '5\n["x"]\nblah\n5\n["y"]'
    frames = list(iter_frames(body))
    assert frames == [["x"]]  # stops at first non-numeric size


def test_iter_frames_empty():
    assert list(iter_frames("")) == []
