from datetime import date
from scrapers.calendar_picker_scraper import CalendarCell


def test_save_and_get_calendar_cache_roundtrip(tmp_path, monkeypatch):
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cache_mod, "CALENDAR_CACHE", str(tmp_path / "cache" / "calendar"))
    # Reset memoized dirs flag so _ensure_cache_dirs picks up monkey-patched paths
    monkeypatch.setattr(cache_mod, "_dirs_ensured", False)

    cells = [
        CalendarCell(date(2026, 8, 30), date(2026, 8, 31), "CDG", "LIM", 1107.0, "tok"),
        CalendarCell(date(2026, 8, 30), date(2026, 9, 1),  "CDG", "LIM", 1019.0, "tok2"),
    ]
    cache_mod.save_calendar_cache("CDG", "LIM", date(2026, 8, 30), cells)

    got = cache_mod.get_calendar_cache("CDG", "LIM", date(2026, 8, 30))
    assert got is not None
    assert len(got) == 2
    assert got[0].prix == 1107.0
    assert got[0].dep == "CDG"


def test_get_calendar_cache_miss_returns_none(tmp_path, monkeypatch):
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cache_mod, "CALENDAR_CACHE", str(tmp_path / "cache" / "calendar"))
    monkeypatch.setattr(cache_mod, "_dirs_ensured", False)

    assert cache_mod.get_calendar_cache("CDG", "LIM", date(2026, 8, 30)) is None
