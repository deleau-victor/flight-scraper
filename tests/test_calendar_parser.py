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


from scrapers.calendar_picker_scraper import extract_wrb_payload


def test_extract_wrb_payload_valid():
    inner = '[["meta"], [["2026-08-30","2026-08-31",[[null,1107],"tok"],1]]]'
    frame = [["wrb.fr", None, inner]]
    payload = extract_wrb_payload(frame)
    assert payload == [["meta"], [["2026-08-30", "2026-08-31", [[None, 1107], "tok"], 1]]]


def test_extract_wrb_payload_di_frame_returns_none():
    assert extract_wrb_payload([["di", 527]]) is None


def test_extract_wrb_payload_e_frame_returns_none():
    assert extract_wrb_payload([["e", 8, None, None, 9236]]) is None


def test_extract_wrb_payload_malformed_returns_none():
    assert extract_wrb_payload([]) is None
    assert extract_wrb_payload(None) is None
    assert extract_wrb_payload([["wrb.fr", None, "not-json"]]) is None


from scrapers.calendar_picker_scraper import extract_cells


def test_extract_cells_valid_only():
    payload = [
        ["meta"],
        [
            ["2026-08-30", "2026-08-31", [[None, 1107], "tok1"], 1],
            ["2026-08-30", "2026-09-01", [[None, 1019], "tok2"], 1],
            ["2026-08-29", "2026-08-28", None, 2],  # invalid (return < dep)
        ],
    ]
    cells = extract_cells(payload, dep="CDG", arrival="LIM")
    assert len(cells) == 2
    assert cells[0].date_aller == date(2026, 8, 30)
    assert cells[0].date_retour == date(2026, 8, 31)
    assert cells[0].dep == "CDG"
    assert cells[0].arrival == "LIM"
    assert cells[0].prix == 1107.0
    assert cells[0].deeplink_token == "tok1"
    assert cells[1].prix == 1019.0


def test_extract_cells_handles_missing_token():
    payload = [["meta"], [["2026-08-30", "2026-08-31", [[None, 1107]], 1]]]
    cells = extract_cells(payload, dep="CDG", arrival="LIM")
    assert len(cells) == 1
    assert cells[0].deeplink_token == ""


def test_extract_cells_skips_status_2():
    payload = [["meta"], [["2026-08-29", "2026-08-28", None, 2]]]
    assert extract_cells(payload, dep="X", arrival="Y") == []


def test_extract_cells_empty_payload():
    assert extract_cells([["meta"], []], dep="X", arrival="Y") == []
    assert extract_cells(None, dep="X", arrival="Y") == []
    assert extract_cells([["meta"]], dep="X", arrival="Y") == []
