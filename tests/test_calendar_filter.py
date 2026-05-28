from datetime import date
from scrapers.calendar_picker_scraper import CalendarCell, filter_and_select_top_n


def make_cell(da, dr, dep, arr, prix):
    return CalendarCell(date_aller=da, date_retour=dr, dep=dep, arrival=arr, prix=prix)


def test_filter_keeps_valid_weekday_and_duration():
    # 2026-08-27 = Thursday (weekday=3 in ALLOWED_DEPARTURE_WEEKDAYS=[3,4,5])
    # 2026-09-19 = Saturday (weekday=5 in ALLOWED_RETURN_WEEKDAYS=[5,6,0])
    # diff = 23 days ∈ TRIP_DURATIONS=[21..27]
    cells = [make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 1000.0)]
    out = filter_and_select_top_n(cells, top_n=10)
    assert len(out) == 1
    da, dr, dur, dep, arr = out[0]
    assert da == date(2026, 8, 27)
    assert dr == date(2026, 9, 19)
    assert dur == 23
    assert dep == "CDG"
    assert arr == "LIM"


def test_filter_drops_wrong_weekday():
    # 2026-08-25 = Tuesday (weekday=1) NOT in ALLOWED_DEPARTURE_WEEKDAYS
    cells = [make_cell(date(2026, 8, 25), date(2026, 9, 17), "CDG", "LIM", 1000.0)]
    assert filter_and_select_top_n(cells, top_n=10) == []


def test_filter_drops_wrong_duration():
    # diff = 10 days NOT in TRIP_DURATIONS
    cells = [make_cell(date(2026, 8, 27), date(2026, 9, 6), "CDG", "LIM", 1000.0)]
    assert filter_and_select_top_n(cells, top_n=10) == []


def test_filter_drops_too_cheap_or_too_expensive():
    # MIN_PRICE=200, MAX_PRICE=5000
    cells = [
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 100.0),    # too cheap
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 6000.0),   # too expensive
    ]
    assert filter_and_select_top_n(cells, top_n=10) == []


def test_filter_drops_outside_date_range():
    # START_DATE=2026-07-01, END_DATE=2026-10-31
    cells = [make_cell(date(2026, 6, 25), date(2026, 7, 18), "CDG", "LIM", 1000.0)]
    assert filter_and_select_top_n(cells, top_n=10) == []


def test_filter_top_n_per_route():
    cells = [
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 1500.0),
        make_cell(date(2026, 8, 28), date(2026, 9, 20), "CDG", "LIM", 1200.0),
        make_cell(date(2026, 8, 29), date(2026, 9, 21), "CDG", "LIM",  900.0),
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "BRU", "LIM", 1100.0),
    ]
    out = filter_and_select_top_n(cells, top_n=2)
    cdg_lim = [t for t in out if t[3] == "CDG"]
    bru_lim = [t for t in out if t[3] == "BRU"]
    assert len(cdg_lim) == 2
    assert len(bru_lim) == 1
    # Top-2 CDG-LIM should be the 2 cheapest
    cdg_prices_in_order_of_cells = [c.prix for c in cells[:3]]
    assert sorted(cdg_prices_in_order_of_cells)[:2] == [900.0, 1200.0]


def test_filter_dedup_same_combo_keeps_cheapest():
    cells = [
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 1500.0),
        make_cell(date(2026, 8, 27), date(2026, 9, 19), "CDG", "LIM", 1200.0),
    ]
    out = filter_and_select_top_n(cells, top_n=10)
    assert len(out) == 1  # dedup'd by (dep, arr, da, dr)
