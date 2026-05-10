# Calendar Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 2-phase Google Flights pivot — Phase 1 scrapes the calendar matrix per route via Playwright + XHR interception (`POST .../GetCalendarGrid`), filters top-N combos, then Phase 2 runs the existing `fast-flights` scraper only on those targeted combos.

**Architecture:** New module `scrapers/calendar_picker_scraper.py` opens 1 Playwright session per route, intercepts `GetCalendarGrid` JSON responses (XSSI + chunked `wrb.fr` frames), slides via scroll buttons (each click = 1 day = 1 new POST). Cache per slide, dedup cells, filter weekday/duration/price/range, take top-N per route, inject as `combos_override` into existing fast-flights scraper. Aggregator/models/self-transfer untouched.

**Tech Stack:** Python 3.14, Playwright + playwright-stealth, fast-flights, pytest (new), rich, asyncio.

**Reference Spec:** `docs/superpowers/specs/2026-05-10-calendar-picker-design.md`

---

## File Structure

**Created:**
- `scrapers/calendar_picker_scraper.py` — main module: `CalendarCell` dataclass, response parser, scraper, `filter_and_select_top_n`
- `tests/__init__.py` — package marker
- `tests/conftest.py` — pytest fixtures (paths, sample data)
- `tests/test_calendar_parser.py` — parser unit tests
- `tests/test_calendar_filter.py` — `filter_and_select_top_n` unit tests
- `tests/test_calendar_cache.py` — cache get/save tests
- `tests/fixtures/calendar_response_sample.txt` — captured-style synthetic response

**Modified:**
- `pyproject.toml` — add `pytest` dev dep
- `config.py` — add Phase 1 config block
- `cache.py` — add `CALENDAR_CACHE` + `get_calendar_cache` / `save_calendar_cache`, extend `cache_stats`
- `scrapers/fast_flights_scraper.py` — add `combos_override` param to `run_google_flights_scraper_async` + sync wrapper
- `main.py` — new orchestration `main()` with `USE_CALENDAR_PHASE`, new CLI flags `--calendar-only` / `--legacy`

---

## Task 1: Set up pytest infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add pytest to pyproject.toml**

Edit `pyproject.toml` — add a `[dependency-groups]` section (uv convention) below the existing `dependencies` list:

```toml
[project]
name = "flight-scraper"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "fast-flights[local]>=2.2",
    "playwright>=1.59.0",
    "playwright-stealth>=2.0",
    "rich>=13.7",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Install pytest**

Run: `uv sync --all-groups`
Expected: pytest and pytest-asyncio added to .venv.

- [ ] **Step 3: Create test package**

Create `tests/__init__.py` (empty file) and `tests/conftest.py`:

```python
# tests/conftest.py
import sys
from pathlib import Path

# Make project root importable so tests can `import scrapers.calendar_picker_scraper`
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = Path(__file__).parent / "fixtures"
```

- [ ] **Step 4: Verify pytest runs**

Run: `uv run pytest --collect-only`
Expected: `no tests ran in 0.0Xs` (no errors, just empty).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py
git commit -m "test: bootstrap pytest infrastructure for calendar picker"
```

---

## Task 2: Create CalendarCell dataclass and module skeleton

**Files:**
- Create: `scrapers/calendar_picker_scraper.py`
- Create: `tests/test_calendar_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_calendar_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.calendar_picker_scraper'`.

- [ ] **Step 3: Create the module with dataclass**

Create `scrapers/calendar_picker_scraper.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): add CalendarCell dataclass + module skeleton"
```

---

## Task 3: Parse XSSI prefix from response body

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py`

The Google response starts with `)]}'\n` followed by the chunked frames. We need a helper that strips this prefix.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar_parser.py`:

```python
from scrapers.calendar_picker_scraper import strip_xssi_prefix


def test_strip_xssi_prefix_present():
    raw = ")]}'\n7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"


def test_strip_xssi_prefix_absent():
    raw = "7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"


def test_strip_xssi_prefix_with_extra_newlines():
    raw = ")]}'\n\n\n7778\n[]"
    assert strip_xssi_prefix(raw) == "7778\n[]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'strip_xssi_prefix'`.

- [ ] **Step 3: Implement the function**

Append to `scrapers/calendar_picker_scraper.py`:

```python
def strip_xssi_prefix(text: str) -> str:
    """Retire le préfixe anti-XSSI de Google `)]}'` et les newlines en tête."""
    if text.startswith(")]}'"):
        text = text[4:]
    return text.lstrip("\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): strip XSSI prefix from response body"
```

---

## Task 4: Iterate chunked frames

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py`

The response after XSSI strip looks like:
```
<size_in_bytes>\n<frame_text_of_size_bytes><size>\n<frame>...
```

Each frame is JSON. We yield `(frame_dict, ...)` pairs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py::test_iter_frames_two_frames -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement `iter_frames`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
import json
from typing import Iterator


def iter_frames(body: str) -> Iterator[object]:
    """Itère sur les frames JSON d'une réponse Google chunked.
    
    Format : `<size>\\n<frame_of_size_bytes>` répété.
    Skip silencieusement les frames non-JSON ou les size non-numériques (fin de stream).
    """
    pos = 0
    while pos < len(body):
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): iterate chunked frames from Google response"
```

---

## Task 5: Extract `wrb.fr` payload from frame

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py`

A `wrb.fr` frame looks like `[["wrb.fr", null, "<inner_json_stringified>"]]`. We need to extract and re-parse the inner JSON. Other frame types (`di`, `af.httprm`, `e`) are skipped.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement `extract_wrb_payload`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): extract wrb.fr inner payload from frame"
```

---

## Task 6: Extract cells from a `wrb.fr` payload

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py`

The inner payload structure is `[meta, cells_list]` where each cell is `[date_aller_iso, date_retour_iso, [[null, prix_int], token_b64], status]` (status 1 = valid, 2 = invalid). For status=2 the price slot is `null`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement `extract_cells`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): extract CalendarCells from wrb.fr payload"
```

---

## Task 7: End-to-end parser `parse_calendar_response`

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py`
- Create: `tests/fixtures/__init__.py` (empty)
- Create: `tests/fixtures/calendar_response_sample.txt`

Glue all parser pieces. Test with a realistic multi-frame fixture (XSSI + wrb.fr + di + e frames).

- [ ] **Step 1: Create fixture file**

Create `tests/fixtures/__init__.py` (empty file).

Create `tests/fixtures/calendar_response_sample.txt` with **exactly** this content (no trailing newline added by the editor; line endings = `\n`):

```
)]}'

185
[["wrb.fr",null,"[[\"meta\"],[[\"2026-08-30\",\"2026-08-31\",[[null,1107],\"tokA\"],1],[\"2026-08-30\",\"2026-09-01\",[[null,1019],\"tokB\"],1],[\"2026-08-29\",\"2026-08-28\",null,2]]]"]]
24
[["di",527],["e",8]]
```

NOTE: the size `185` and `24` must match the byte length of the JSON string that follows them (use `len(line.encode("utf-8"))`). If you regenerate the fixture, recalculate sizes.

- [ ] **Step 2: Write the failing integration test**

Append to `tests/test_calendar_parser.py`:

```python
from tests.conftest import FIXTURES_DIR
from scrapers.calendar_picker_scraper import parse_calendar_response


def test_parse_calendar_response_full_fixture():
    raw = (FIXTURES_DIR / "calendar_response_sample.txt").read_text(encoding="utf-8")
    cells = parse_calendar_response(raw, dep="CDG", arrival="LIM")
    assert len(cells) == 2
    assert {c.prix for c in cells} == {1107.0, 1019.0}
    assert all(c.dep == "CDG" and c.arrival == "LIM" for c in cells)


def test_parse_calendar_response_empty_string():
    assert parse_calendar_response("", dep="X", arrival="Y") == []


def test_parse_calendar_response_only_xssi():
    assert parse_calendar_response(")]}'\n", dep="X", arrival="Y") == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py::test_parse_calendar_response_full_fixture -v`
Expected: FAIL — ImportError.

- [ ] **Step 4: Implement `parse_calendar_response`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
def parse_calendar_response(raw: str, dep: str, arrival: str) -> list[CalendarCell]:
    """Parse une réponse complète `GetCalendarGrid` → liste de CalendarCell.
    
    Pipeline : strip XSSI → iter chunked frames → extract wrb.fr payload → extract cells.
    Skip silencieusement les frames di/e/af.httprm.
    """
    body = strip_xssi_prefix(raw)
    cells: list[CalendarCell] = []
    for frame in iter_frames(body):
        payload = extract_wrb_payload(frame)
        if payload is None:
            continue
        cells.extend(extract_cells(payload, dep=dep, arrival=arrival))
    return cells
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_calendar_parser.py -v`
Expected: 18 PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py tests/fixtures/__init__.py tests/fixtures/calendar_response_sample.txt
git commit -m "feat(calendar): end-to-end parse_calendar_response + fixture test"
```

---

## Task 8: Add Phase 1 config

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Append config block**

Add at the end of `config.py`:

```python
# ============ PHASE 1 — CALENDAR PICKER ============
USE_CALENDAR_PHASE = True
TOP_COMBOS_PHASE2 = 25
CALENDAR_SLIDE_THROTTLE_MIN = 1.0
CALENDAR_SLIDE_THROTTLE_MAX = 2.5
CALENDAR_WAIT_FOR_MATRIX_MS = 8000
CALENDAR_GOTO_TIMEOUT_MS = 12000
CALENDAR_RESULTS_TIMEOUT_MS = 12000
```

- [ ] **Step 2: Verify nothing imports broken**

Run: `uv run python -c "from config import USE_CALENDAR_PHASE, TOP_COMBOS_PHASE2; print(USE_CALENDAR_PHASE, TOP_COMBOS_PHASE2)"`
Expected: `True 25`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(config): add Phase 1 calendar picker config"
```

---

## Task 9: Calendar cache get/save

**Files:**
- Modify: `cache.py`
- Create: `tests/test_calendar_cache.py`

Cache 1 file per slide: `data/cache/calendar/{dep}_{arrival}_{anchor_iso}.json`. Same TTL (`CACHE_TTL_HOURS`) and JSON format as `round_trip` cache.

- [ ] **Step 1: Write failing tests**

Create `tests/test_calendar_cache.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_cache.py -v`
Expected: FAIL — `AttributeError: module 'cache' has no attribute 'save_calendar_cache'`.

- [ ] **Step 3: Modify `cache.py`**

Add to `cache.py` next to `ROUND_TRIP_CACHE` definition (around line 10):

```python
CALENDAR_CACHE = f"{CACHE_DIR}/calendar"
```

Update `_ensure_cache_dirs` to also create `CALENDAR_CACHE`:

```python
def _ensure_cache_dirs():
    global _dirs_ensured
    if _dirs_ensured:
        return
    os.makedirs(ROUND_TRIP_CACHE, exist_ok=True)
    os.makedirs(ONE_WAY_CACHE, exist_ok=True)
    os.makedirs(CALENDAR_CACHE, exist_ok=True)
    _dirs_ensured = True
```

Add at the end of `cache.py`:

```python
# ============== CALENDAR CACHE ==============

def _calendar_key(dep: str, arrival: str, anchor: date) -> str:
    return f"{dep}_{arrival}_{anchor.isoformat()}"


def get_calendar_cache(dep: str, arrival: str, anchor: date):
    """Retourne list[CalendarCell] ou None si miss/expiré.
    
    Import local de CalendarCell pour éviter cycle d'import (cache importé
    par calendar_picker_scraper).
    """
    _ensure_cache_dirs()
    filepath = f"{CALENDAR_CACHE}/{_calendar_key(dep, arrival, anchor)}.json"
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not _is_cache_valid(data.get("cached_at", "")):
            return None
        from scrapers.calendar_picker_scraper import CalendarCell
        return [
            CalendarCell(
                date_aller=date.fromisoformat(c["date_aller"]),
                date_retour=date.fromisoformat(c["date_retour"]),
                dep=c["dep"],
                arrival=c["arrival"],
                prix=float(c["prix"]),
                deeplink_token=c.get("deeplink_token", ""),
            )
            for c in data.get("cells", [])
        ]
    except (json.JSONDecodeError, IOError, KeyError):
        return None


def save_calendar_cache(dep: str, arrival: str, anchor: date, cells: list):
    _ensure_cache_dirs()
    filepath = f"{CALENDAR_CACHE}/{_calendar_key(dep, arrival, anchor)}.json"
    data = {
        "cached_at": datetime.now().isoformat(),
        "cells": [
            {
                "date_aller": c.date_aller.isoformat(),
                "date_retour": c.date_retour.isoformat(),
                "dep": c.dep,
                "arrival": c.arrival,
                "prix": c.prix,
                "deeplink_token": c.deeplink_token,
            }
            for c in cells
        ],
    }
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"      ⚠️  Erreur calendar cache write {_calendar_key(dep, arrival, anchor)}: {e}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_cache.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add cache.py tests/test_calendar_cache.py
git commit -m "feat(cache): add calendar cache get/save"
```

---

## Task 10: Extend `cache_stats()` with calendar count

**Files:**
- Modify: `cache.py`

- [ ] **Step 1: Update `cache_stats`**

Replace the existing `cache_stats()` body in `cache.py` with:

```python
def cache_stats():
    _ensure_cache_dirs()
    rt_files = [f for f in os.listdir(ROUND_TRIP_CACHE) if f.endswith(".json")] if os.path.exists(ROUND_TRIP_CACHE) else []
    ow_files = [f for f in os.listdir(ONE_WAY_CACHE) if f.endswith(".json")] if os.path.exists(ONE_WAY_CACHE) else []
    cal_files = [f for f in os.listdir(CALENDAR_CACHE) if f.endswith(".json")] if os.path.exists(CALENDAR_CACHE) else []
    
    total_size = sum(
        os.path.getsize(os.path.join(ROUND_TRIP_CACHE, f)) for f in rt_files
    ) + sum(
        os.path.getsize(os.path.join(ONE_WAY_CACHE, f)) for f in ow_files
    ) + sum(
        os.path.getsize(os.path.join(CALENDAR_CACHE, f)) for f in cal_files
    )
    
    print(
        f"📦 Cache : {len(rt_files)} round-trip + {len(ow_files)} one-way + "
        f"{len(cal_files)} calendar ({total_size / 1024:.1f} KB)"
    )
```

- [ ] **Step 2: Smoke run**

Run: `uv run python -c "from cache import cache_stats; cache_stats()"`
Expected: line printed with `0 calendar` (no error).

- [ ] **Step 3: Commit**

```bash
git add cache.py
git commit -m "feat(cache): include calendar count in cache_stats"
```

---

## Task 11: `filter_and_select_top_n` — full implementation + tests

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Create: `tests/test_calendar_filter.py`

Filtering pipeline: weekday → duration → price/range → top-N per route.

NOTE on `duration` semantics: `utils.generate_combinations()` uses `return_date = current + timedelta(days=duration)` — so `duration == (date_retour - date_aller).days`. The filter must use the same convention.

- [ ] **Step 1: Write failing tests**

Create `tests/test_calendar_filter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_filter.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement `filter_and_select_top_n`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
from collections import defaultdict
from config import (
    START_DATE, END_DATE, TRIP_DURATIONS,
    ALLOWED_DEPARTURE_WEEKDAYS, ALLOWED_RETURN_WEEKDAYS,
    MIN_PRICE, MAX_PRICE,
)


def filter_and_select_top_n(
    cells: list[CalendarCell],
    top_n: int,
) -> list[tuple]:
    """Pipeline de filtrage côté Python sur les cellules de la matrice :
    
        1. weekday  : date_aller.weekday() ∈ ALLOWED_DEPARTURE_WEEKDAYS
                      date_retour.weekday() ∈ ALLOWED_RETURN_WEEKDAYS
        2. durée    : (date_retour - date_aller).days ∈ TRIP_DURATIONS
                      (convention de utils.generate_combinations)
        3. prix     : MIN_PRICE < prix < MAX_PRICE
        4. range    : date_aller >= START_DATE, date_retour <= END_DATE
        5. dédup    : par (dep, arr, date_aller, date_retour), garde le moins cher
        6. group by route, sort by prix asc, take [:top_n]
    
    Retourne : list[(date_aller, date_retour, duration, dep, arrival)]
    Format identique à `utils.generate_combinations()` / consommé par
    `fast_flights_scraper.process_combo()`.
    """
    # Étapes 1-4 : filtres
    valid: list[CalendarCell] = []
    for c in cells:
        if c.date_aller.weekday() not in ALLOWED_DEPARTURE_WEEKDAYS:
            continue
        if c.date_retour.weekday() not in ALLOWED_RETURN_WEEKDAYS:
            continue
        duration = (c.date_retour - c.date_aller).days
        if duration not in TRIP_DURATIONS:
            continue
        if not (MIN_PRICE < c.prix < MAX_PRICE):
            continue
        if c.date_aller < START_DATE or c.date_retour > END_DATE:
            continue
        valid.append(c)
    
    # Étape 5 : dédup par (dep, arr, da, dr) en gardant le moins cher
    dedup: dict[tuple, CalendarCell] = {}
    for c in valid:
        key = (c.dep, c.arrival, c.date_aller, c.date_retour)
        prev = dedup.get(key)
        if prev is None or c.prix < prev.prix:
            dedup[key] = c
    
    # Étape 6 : group by route, top-N par route
    by_route: dict[tuple, list[CalendarCell]] = defaultdict(list)
    for c in dedup.values():
        by_route[(c.dep, c.arrival)].append(c)
    
    out: list[tuple] = []
    for route_cells in by_route.values():
        route_cells.sort(key=lambda c: c.prix)
        for c in route_cells[:top_n]:
            duration = (c.date_retour - c.date_aller).days
            out.append((c.date_aller, c.date_retour, duration, c.dep, c.arrival))
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_calendar_filter.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_filter.py
git commit -m "feat(calendar): filter_and_select_top_n with weekday/duration/price/range/top-N"
```

---

## Task 12: Stealth Playwright context (duplicated)

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`

Duplicate the stealth/consent setup from `fast_flights_patch.py`. Per user preference: do NOT extract a shared helper — `fast_flights_patch.py` stays untouched.

- [ ] **Step 1: Append duplicated setup**

Append to `scrapers/calendar_picker_scraper.py`:

```python
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


REALISTIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_stealth = Stealth()


@asynccontextmanager
async def _stealth_browser_context():
    """Browser+context Chromium configuré identiquement à fast_flights_patch.py
    (UA, locale, timezone, cookies CONSENT/SOCS, stealth patches).
    
    Code dupliqué intentionnellement de fast_flights_patch.py — ne pas refactorer
    pour mutualiser, le module doit rester intact (cf spec : préférence
    duplication > refactor pour le code anti-détection qui marche).
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=REALISTIC_UA,
            )
            await _stealth.apply_stealth_async(context)
            await context.add_cookies([
                {
                    "name": "CONSENT",
                    "value": "YES+cb.20210720-07-p0.en+FX+410",
                    "domain": ".google.com",
                    "path": "/",
                },
                {
                    "name": "SOCS",
                    "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
                    "domain": ".google.com",
                    "path": "/",
                },
            ])
            yield context
        finally:
            await browser.close()


async def _dismiss_consent_fallback(page):
    """Cliquer 'Accept all' si la page consent apparaît malgré les cookies préchargés."""
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Tout accepter")',
        'button[aria-label*="Accept"]',
        'button[aria-label*="Accepter"]',
    ]
    for sel in selectors:
        btn = page.locator(sel)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=2000)
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from scrapers.calendar_picker_scraper import _stealth_browser_context; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scrapers/calendar_picker_scraper.py
git commit -m "feat(calendar): duplicate stealth Playwright context setup"
```

---

## Task 13: Build Google Flights TFS URL for a route + anchor

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`
- Modify: `tests/test_calendar_parser.py` (or new file `tests/test_calendar_url.py`)

The Date grid only opens on a Google Flights round-trip search page. We need to navigate to a TFS URL with a starting `(date_aller, date_retour)` anchor. We reuse `fast_flights.flights_impl.FlightData` + `TFSData` (via the patched library) to build the protobuf-encoded `tfs` param.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar_parser.py`:

```python
from datetime import date
from scrapers.calendar_picker_scraper import build_google_flights_url


def test_build_google_flights_url_round_trip():
    # Must NOT raise; must return a https URL with tfs=, hl=en-US, gl=FR
    url = build_google_flights_url(
        dep="CDG", arrival="LIM",
        date_aller=date(2026, 8, 27), date_retour=date(2026, 9, 19),
    )
    assert url.startswith("https://www.google.com/travel/flights")
    assert "tfs=" in url
    assert "hl=en-US" in url
    assert "gl=FR" in url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calendar_parser.py::test_build_google_flights_url_round_trip -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement `build_google_flights_url`**

Append to `scrapers/calendar_picker_scraper.py`:

```python
import fast_flights_patch  # noqa: F401  — DOIT être importé pour appliquer le monkey-patch protobuf type=1
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData


def build_google_flights_url(
    dep: str, arrival: str,
    date_aller: date, date_retour: date,
) -> str:
    """Construit l'URL Google Flights round-trip qu'on visite avant d'ouvrir Date grid.
    
    Réutilise le builder TFSData de fast-flights (avec son monkey-patch type=1
    qui répare CUZ/AQP). Locale en-US/FR pour cohérence avec l'exploration manuelle.
    """
    tfs = TFSData.from_interface(
        flight_data=[
            FlightData(date=date_aller.isoformat(), from_airport=dep, to_airport=arrival),
            FlightData(date=date_retour.isoformat(), from_airport=arrival, to_airport=dep),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1),
        max_stops=None,
    )
    tfs_b64 = tfs.as_b64().decode("utf-8")
    return (
        "https://www.google.com/travel/flights"
        f"?tfs={tfs_b64}&hl=en-US&gl=FR&curr=EUR"
    )
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/test_calendar_parser.py::test_build_google_flights_url_round_trip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/calendar_picker_scraper.py tests/test_calendar_parser.py
git commit -m "feat(calendar): build_google_flights_url for round-trip TFS"
```

---

## Task 14: `scrape_calendar_for_route` — single route end-to-end (no cache yet)

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`

This is the core scraping function. It does NOT use the cache yet (added in Task 15). It produces a deduplicated list of `CalendarCell`.

- [ ] **Step 1: Implement the function**

Append to `scrapers/calendar_picker_scraper.py`:

```python
import asyncio
import random
from config import (
    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX,
    CALENDAR_GOTO_TIMEOUT_MS, CALENDAR_RESULTS_TIMEOUT_MS,
    CALENDAR_WAIT_FOR_MATRIX_MS,
    START_DATE, END_DATE, TRIP_DURATIONS,
)


# Selectors confirmed via manual DOM exploration (cf. exploration.md)
_SEL_RESULTS_LOADED = ".eQ35Ce"
_SEL_DATE_GRID_BUTTON = 'button[jsname="KqtnKd"]'
_SEL_MATRIX_CANVAS = 'canvas[jsname="qTwgI"]'
_SEL_SCROLL_RIGHT = 'button[aria-label="Scroll right"]'
_SEL_SCROLL_DOWN = 'button[aria-label="Scroll down"]'
_GET_CALENDAR_GRID_URL_FRAGMENT = "/GetCalendarGrid"


async def scrape_calendar_for_route(
    dep: str,
    arrival: str,
    start_anchor: date,
    end_anchor: date,
    *,
    max_clicks: int = 250,
) -> list[CalendarCell]:
    """Scrape la matrice calendaire pour 1 route.
    
    Pattern :
      1. Build URL avec anchor (start_anchor, start_anchor + median_duration)
      2. Navigate, wait results, dismiss consent
      3. Set up page.on("response") qui filtre sur /GetCalendarGrid et stocke les bodies
      4. Click Date grid button (jsname=KqtnKd) → 1ère réponse
      5. Loop : alternate scroll_right + scroll_down clicks, capture chaque réponse,
         parse, jusqu'à atteindre end_anchor ou max_clicks
      6. Dédup les cellules par (date_aller, date_retour)
    """
    median_duration = sorted(TRIP_DURATIONS)[len(TRIP_DURATIONS) // 2]  # 24
    from datetime import timedelta
    anchor_aller = start_anchor
    anchor_retour = start_anchor + timedelta(days=median_duration)
    url = build_google_flights_url(dep, arrival, anchor_aller, anchor_retour)
    
    captured: list[str] = []
    
    async def on_response(response):
        if _GET_CALENDAR_GRID_URL_FRAGMENT in response.url:
            try:
                captured.append(await response.text())
            except Exception:
                pass
    
    cells_by_key: dict[tuple, CalendarCell] = {}
    
    async with _stealth_browser_context() as context:
        page = await context.new_page()
        page.on("response", on_response)
        
        await page.goto(url, timeout=CALENDAR_GOTO_TIMEOUT_MS)
        await _dismiss_consent_fallback(page)
        await page.locator(_SEL_RESULTS_LOADED).wait_for(timeout=CALENDAR_RESULTS_TIMEOUT_MS)
        
        # Open Date grid → triggers initial GetCalendarGrid
        await page.locator(_SEL_DATE_GRID_BUTTON).click(timeout=5000)
        await page.locator(_SEL_MATRIX_CANVAS).wait_for(timeout=CALENDAR_WAIT_FOR_MATRIX_MS)
        # Wait a moment for the response listener to capture
        await asyncio.sleep(0.8)
        
        # Slide loop: alternate scroll_right and scroll_down (advance both axes by 1)
        clicks = 0
        max_aller = end_anchor  # we want date_aller to reach this
        
        while clicks < max_clicks:
            # Parse what we have so far to know our coverage
            for raw in captured:
                for cell in parse_calendar_response(raw, dep=dep, arrival=arrival):
                    key = (cell.date_aller, cell.date_retour)
                    prev = cells_by_key.get(key)
                    if prev is None or cell.prix < prev.prix:
                        cells_by_key[key] = cell
            captured.clear()
            
            # Termination: if we have at least one cell with date_aller >= max_aller, done
            if cells_by_key and max(c.date_aller for c in cells_by_key.values()) >= max_aller:
                break
            
            # Click pair: scroll right (advance date_aller) then scroll down (advance date_retour)
            try:
                await page.locator(_SEL_SCROLL_RIGHT).click(timeout=3000)
                await asyncio.sleep(random.uniform(
                    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX
                ))
                clicks += 1
                if clicks >= max_clicks:
                    break
                await page.locator(_SEL_SCROLL_DOWN).click(timeout=3000)
                await asyncio.sleep(random.uniform(
                    CALENDAR_SLIDE_THROTTLE_MIN, CALENDAR_SLIDE_THROTTLE_MAX
                ))
                clicks += 1
            except Exception:
                # Buttons disabled (end of range) or vanished — break
                break
        
        # Final parse pass for any responses captured during the last sleep
        for raw in captured:
            for cell in parse_calendar_response(raw, dep=dep, arrival=arrival):
                key = (cell.date_aller, cell.date_retour)
                prev = cells_by_key.get(key)
                if prev is None or cell.prix < prev.prix:
                    cells_by_key[key] = cell
    
    return list(cells_by_key.values())
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from scrapers.calendar_picker_scraper import scrape_calendar_for_route; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Manual smoke test (optional, requires network)**

Run:

```bash
uv run python -c "
import asyncio
from datetime import date
from scrapers.calendar_picker_scraper import scrape_calendar_for_route

cells = asyncio.run(scrape_calendar_for_route(
    'CDG', 'LIM', date(2026, 7, 2), date(2026, 7, 20), max_clicks=10,
))
print(f'Got {len(cells)} cells')
for c in cells[:5]:
    print(f'  {c.date_aller} → {c.date_retour}: €{c.prix}')
"
```

Expected: ≥10 cells with prices in plausible range (€400–€2500). If 0 cells: re-check selectors via `exploration.md`.

- [ ] **Step 4: Commit**

```bash
git add scrapers/calendar_picker_scraper.py
git commit -m "feat(calendar): scrape_calendar_for_route end-to-end (no cache)"
```

---

## Task 15: Wire calendar cache into `scrape_calendar_for_route`

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`

Cache key = `(dep, arrival, anchor_date)` where `anchor_date = start_anchor`. Each call to `scrape_calendar_for_route` is cached as a single unit (1 file = 1 route × 1 anchor).

- [ ] **Step 1: Modify `scrape_calendar_for_route` to read/write cache**

In `scrapers/calendar_picker_scraper.py`, modify `scrape_calendar_for_route` — wrap it with a cache check at the beginning and a cache save at the end. Add this near the top of the file (after the existing imports):

```python
from config import USE_CACHE
from cache import get_calendar_cache, save_calendar_cache
```

Then modify the function body — replace the existing `scrape_calendar_for_route` definition with:

```python
async def scrape_calendar_for_route(
    dep: str,
    arrival: str,
    start_anchor: date,
    end_anchor: date,
    *,
    max_clicks: int = 250,
) -> list[CalendarCell]:
    """Scrape la matrice calendaire pour 1 route. Cf docstring détaillé du module.
    
    Cache disque par (dep, arrival, start_anchor). TTL = CACHE_TTL_HOURS.
    """
    if USE_CACHE:
        cached = get_calendar_cache(dep, arrival, start_anchor)
        if cached is not None:
            return cached
    
    cells = await _scrape_calendar_for_route_uncached(
        dep, arrival, start_anchor, end_anchor, max_clicks=max_clicks,
    )
    
    if USE_CACHE and cells:
        save_calendar_cache(dep, arrival, start_anchor, cells)
    
    return cells
```

Then rename the existing function body (without cache) to `_scrape_calendar_for_route_uncached` — keeping the same body, just changing the name on the `async def` line.

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from scrapers.calendar_picker_scraper import scrape_calendar_for_route, _scrape_calendar_for_route_uncached; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scrapers/calendar_picker_scraper.py
git commit -m "feat(calendar): wrap scraper with disk cache"
```

---

## Task 16: Phase 1 orchestrator with semaphore + Rich tracker

**Files:**
- Modify: `scrapers/calendar_picker_scraper.py`

- [ ] **Step 1: Implement orchestrator and tracker**

Append to `scrapers/calendar_picker_scraper.py`:

```python
import time
from collections import deque
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from config import PARALLEL_WORKERS


class _CalendarTracker:
    """Live tracker pour Phase 1 : barre + stats par route + 10 lignes roulantes."""
    MAX_RESULTS = 10
    BAR_WIDTH = 40
    
    def __init__(self, total_routes: int):
        self.total = total_routes
        self.done = 0
        self.cells_count = 0
        self.from_cache = 0
        self.from_network = 0
        self.errors = 0
        self.start_time = time.perf_counter()
        self.lock = asyncio.Lock()
        self.last_results: deque = deque(
            [Text(" ")] * self.MAX_RESULTS,
            maxlen=self.MAX_RESULTS,
        )
    
    async def record(self, *, line: Text, kind: str, n_cells: int):
        async with self.lock:
            self.done += 1
            self.cells_count += n_cells
            if kind == "cache":
                self.from_cache += 1
            elif kind == "network":
                self.from_network += 1
            elif kind == "error":
                self.errors += 1
            self.last_results.append(line)
    
    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"
    
    def __rich__(self):
        pct = self.done / self.total if self.total else 1.0
        filled = int(self.BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        elapsed = self._fmt_time(time.perf_counter() - self.start_time)
        header = Text.assemble(
            "📅 [", (bar, "magenta"), "] ",
            (f"{self.done}/{self.total}", "bold"),
            (f" ({pct * 100:.0f}%) ", "dim"),
            "| ", (f"écoulé {elapsed}", "yellow"),
        )
        stats = Text.assemble(
            "🧮 ", (f"{self.cells_count}", "bold green"), " cellules  ",
            "📦 ", (f"{self.from_cache}", "bold blue"), " cache  ",
            "🌐 ", (f"{self.from_network}", "bold cyan"), " net  ",
            "❌ ", (f"{self.errors}", "bold red"), " err",
        )
        return Group(header, stats, Text(""), *list(self.last_results))


async def _process_route(
    dep: str, arrival: str,
    start_anchor: date, end_anchor: date,
    semaphore: asyncio.Semaphore,
    tracker: _CalendarTracker,
    out: list,
    out_lock: asyncio.Lock,
):
    t0 = time.perf_counter()
    cached = get_calendar_cache(dep, arrival, start_anchor) if USE_CACHE else None
    if cached is not None:
        async with out_lock:
            out.extend(cached)
        elapsed = time.perf_counter() - t0
        await tracker.record(
            line=Text(f"📦 ✅ {dep}→{arrival}: {len(cached)} cellules ({elapsed:.1f}s)",
                      style="blue", no_wrap=True, overflow="ellipsis"),
            kind="cache", n_cells=len(cached),
        )
        return
    
    async with semaphore:
        try:
            cells = await _scrape_calendar_for_route_uncached(
                dep, arrival, start_anchor, end_anchor,
            )
            if USE_CACHE and cells:
                save_calendar_cache(dep, arrival, start_anchor, cells)
            async with out_lock:
                out.extend(cells)
            elapsed = time.perf_counter() - t0
            await tracker.record(
                line=Text(
                    f"🌐 ✅ {dep}→{arrival}: {len(cells)} cellules ({elapsed:.1f}s)",
                    style="green", no_wrap=True, overflow="ellipsis",
                ),
                kind="network", n_cells=len(cells),
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0
            err = f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:60]}"
            await tracker.record(
                line=Text(f"❌ {dep}→{arrival}: {err} ({elapsed:.1f}s)",
                          style="red", no_wrap=True, overflow="ellipsis"),
                kind="error", n_cells=0,
            )


async def run_calendar_picker_scraper_async(
    valid_routes: dict | None = None,
) -> list[CalendarCell]:
    """Orchestre Phase 1 sur toutes les routes (DEPARTURE × ARRIVAL),
    filtrées par valid_routes si fourni.
    """
    from datetime import timedelta
    from config import DEPARTURE_AIRPORTS, ARRIVAL_AIRPORTS
    
    routes = []
    for dep in DEPARTURE_AIRPORTS:
        for arr in ARRIVAL_AIRPORTS:
            if valid_routes is not None:
                info = valid_routes.get((dep, arr))
                if info is not None and not info["is_valid"]:
                    continue
            routes.append((dep, arr))
    
    print("\n" + "═" * 80)
    print(f"{'📅 PHASE 1 — CALENDAR PICKER':^80}")
    print("═" * 80 + "\n")
    print(f"🔍 {len(routes)} routes | {PARALLEL_WORKERS} workers\n")
    
    semaphore = asyncio.Semaphore(PARALLEL_WORKERS)
    tracker = _CalendarTracker(total_routes=len(routes))
    out: list[CalendarCell] = []
    out_lock = asyncio.Lock()
    
    # Walk anchors covering the full range. For each route, one (start_anchor=START_DATE)
    # call walks the matrix until END_DATE - min(TRIP_DURATIONS).
    end_anchor = END_DATE - timedelta(days=min(TRIP_DURATIONS))
    
    tasks = [
        _process_route(dep, arr, START_DATE, end_anchor, semaphore, tracker, out, out_lock)
        for dep, arr in routes
    ]
    
    console = Console()
    with Live(tracker, refresh_per_second=8, console=console):
        await asyncio.gather(*tasks)
    
    print(f"\n✅ Phase 1 terminée : {len(out)} cellules brutes pour {len(routes)} routes")
    return out


def run_calendar_picker_scraper(valid_routes=None) -> list[CalendarCell]:
    return asyncio.run(run_calendar_picker_scraper_async(valid_routes))
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from scrapers.calendar_picker_scraper import run_calendar_picker_scraper; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scrapers/calendar_picker_scraper.py
git commit -m "feat(calendar): orchestrator with semaphore + Rich live tracker"
```

---

## Task 17: Add `combos_override` to fast-flights scraper

**Files:**
- Modify: `scrapers/fast_flights_scraper.py`

- [ ] **Step 1: Modify `run_google_flights_scraper_async` and the sync wrapper**

In `scrapers/fast_flights_scraper.py`:

Replace the signature of `run_google_flights_scraper_async` (currently at line ~358):

```python
async def run_google_flights_scraper_async(
    combos_override: list | None = None,
) -> list[FlightOffer]:
    global _semaphore
    _semaphore = asyncio.Semaphore(PARALLEL_WORKERS)
    
    print("\n" + "═" * 80)
    print(f"{'🛫 SCRAPER GOOGLE FLIGHTS (async + cache)':^80}")
    print("═" * 80 + "\n")
    
    if combos_override is not None:
        combos = combos_override
        print(f"🎯 Mode ciblé : {len(combos)} combos passés en override (skip prefilter)\n")
    else:
        valid_routes = {}
        if USE_PREFILTER:
            valid_routes = await prefilter_routes_async()
        
        all_combos = generate_combinations()
        
        if valid_routes:
            combos = []
            eliminated_invalid = 0
            eliminated_cold = 0
            for c in all_combos:
                date_aller, _, _, dep, arrival = c
                info = valid_routes.get((dep, arrival))
                if info is None:
                    combos.append(c)
                    continue
                if not info["is_valid"]:
                    eliminated_invalid += 1
                    continue
                if info["hot_zones"] and not is_date_in_hot_zones(date_aller, info["hot_zones"]):
                    eliminated_cold += 1
                    continue
                combos.append(c)
            eliminated = eliminated_invalid + eliminated_cold
            if eliminated:
                print(
                    f"\n🔪 {eliminated} combinaisons éliminées par le préfiltrage "
                    f"({eliminated_invalid} routes mortes + {eliminated_cold} hors hot zones)"
                )
        else:
            combos = all_combos
    
    total = len(combos)
    estimated_time = total * 8 / PARALLEL_WORKERS / 60
    print(f"\n🔍 {total} combinaisons | {PARALLEL_WORKERS} workers")
    print(f"⏱️  Estimation initiale : ~{estimated_time:.1f} min (raffinée en live)")
    
    if USE_CACHE:
        cache_stats()
    print()
    
    results: list[FlightOffer] = []
    results_lock = asyncio.Lock()
    tracker = ScraperTracker(total=total, workers=PARALLEL_WORKERS)
    
    tasks = [
        process_combo(
            idx, total, date_aller, date_retour, duration, dep, arrival,
            results_lock, results, tracker,
        )
        for idx, (date_aller, date_retour, duration, dep, arrival) in enumerate(combos, 1)
    ]
    
    console = Console()
    with Live(tracker, refresh_per_second=8, console=console):
        await asyncio.gather(*tasks)
    
    print(f"\n✅ Google Flights terminé : {len(results)} offres")
    print(
        f"📊 Stats : 📦 {tracker.from_cache} cache | 🌐 {tracker.from_network} réseau | "
        f"⚠️  {tracker.empty} vides | ❌ {tracker.errors} erreurs"
    )
    
    return results


def run_google_flights_scraper(combos_override: list | None = None) -> list[FlightOffer]:
    """Wrapper sync"""
    return asyncio.run(run_google_flights_scraper_async(combos_override))
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from scrapers.fast_flights_scraper import run_google_flights_scraper; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Verify legacy mode still works (no override = unchanged behavior)**

Run: `uv run python -c "
import inspect
from scrapers.fast_flights_scraper import run_google_flights_scraper
sig = inspect.signature(run_google_flights_scraper)
assert 'combos_override' in sig.parameters
assert sig.parameters['combos_override'].default is None
print('signature OK')"`
Expected: `signature OK`

- [ ] **Step 4: Commit**

```bash
git add scrapers/fast_flights_scraper.py
git commit -m "feat(scraper): add combos_override param to fast-flights pipeline"
```

---

## Task 18: Wire Phase 1 → Phase 2 in `main.py` + new CLI flags

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Replace `main.py`**

Overwrite `main.py` with:

```python
"""Orchestrateur principal"""

import fast_flights_patch  # noqa: F401  — DOIT être en premier (monkey-patch)

import asyncio
import os
import sys
from config import (
    GOOGLE_FLIGHTS_CSV, SELF_TRANSFER_CSV, FINAL_RANKING_CSV, DATA_DIR,
    USE_CALENDAR_PHASE, TOP_COMBOS_PHASE2,
)
from models import save_flights_to_csv, load_flights_from_csv
from scrapers.fast_flights_scraper import run_google_flights_scraper
from scrapers.self_transfer_builder import run_self_transfer_builder
from aggregator import aggregate_and_rank
from reporting import print_final_report


def _run_phase1_then_phase2() -> list:
    """Phase 1 (calendar matrix) → filter → top-N → Phase 2 (fast-flights ciblé)."""
    from prefilter import prefilter_routes_async
    from scrapers.calendar_picker_scraper import (
        run_calendar_picker_scraper_async, filter_and_select_top_n,
    )
    
    async def _phase1():
        valid_routes = await prefilter_routes_async()
        cells = await run_calendar_picker_scraper_async(valid_routes)
        return cells
    
    cells = asyncio.run(_phase1())
    
    if not cells:
        print("\n⚠️  Phase 1 a retourné 0 cellule pour TOUTES les routes.")
        print("    Le DOM Google a peut-être changé. Relance en mode legacy :")
        print("        python main.py --legacy")
        return []
    
    combos = filter_and_select_top_n(cells, top_n=TOP_COMBOS_PHASE2)
    print(f"\n🎯 Phase 1 → Phase 2 : {len(combos)} combos sélectionnés "
          f"(top-{TOP_COMBOS_PHASE2}/route après filtre weekday/durée/prix)")
    
    if not combos:
        print("⚠️  0 combo après filtrage. Vérifie ALLOWED_DEPARTURE_WEEKDAYS, "
              "ALLOWED_RETURN_WEEKDAYS, TRIP_DURATIONS, MIN/MAX_PRICE.")
        return []
    
    return run_google_flights_scraper(combos_override=combos)


def main():
    """Run complet : Phase 1 calendar → Phase 2 fast-flights → self-transfer → ranking"""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if USE_CALENDAR_PHASE:
        google_results = _run_phase1_then_phase2()
    else:
        google_results = run_google_flights_scraper()
    
    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)
    print(f"💾 Google Flights sauvé : {GOOGLE_FLIGHTS_CSV}")
    
    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)
    print(f"💾 Self-transfer sauvé : {SELF_TRANSFER_CSV}")
    
    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print(f"💾 Ranking final sauvé : {FINAL_RANKING_CSV}")
    
    print_final_report(final)
    print(f"\n\n✅ Terminé. CSVs disponibles dans {DATA_DIR}/")


def main_legacy():
    """Pipeline legacy : skip Phase 1, fast-flights sur toutes les combinaisons."""
    os.makedirs(DATA_DIR, exist_ok=True)
    google_results = run_google_flights_scraper()
    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)
    
    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)
    
    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_calendar_only():
    """Phase 1 seule. Dump CSV des cellules brutes (debug / scouting)."""
    import csv
    from prefilter import prefilter_routes_async
    from scrapers.calendar_picker_scraper import run_calendar_picker_scraper_async
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    async def _go():
        valid_routes = await prefilter_routes_async()
        return await run_calendar_picker_scraper_async(valid_routes)
    
    cells = asyncio.run(_go())
    
    out_path = f"{DATA_DIR}/calendar_matrix.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "dep", "arrival", "date_aller", "date_retour", "duration",
            "prix", "weekday_aller", "weekday_retour", "deeplink_token",
        ])
        for c in cells:
            writer.writerow([
                c.dep, c.arrival, c.date_aller.isoformat(), c.date_retour.isoformat(),
                (c.date_retour - c.date_aller).days, c.prix,
                c.date_aller.weekday(), c.date_retour.weekday(), c.deeplink_token,
            ])
    print(f"\n💾 {len(cells)} cellules sauvées dans {out_path}")


def main_google_only():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if USE_CALENDAR_PHASE:
        google_results = _run_phase1_then_phase2()
    else:
        google_results = run_google_flights_scraper()
    
    save_flights_to_csv(google_results, GOOGLE_FLIGHTS_CSV)
    print(f"💾 Google Flights sauvé : {GOOGLE_FLIGHTS_CSV}")
    
    self_transfer_results = load_flights_from_csv(SELF_TRANSFER_CSV)
    if self_transfer_results:
        print(f"📂 Self-transfer rechargé depuis CSV : {len(self_transfer_results)} offres")
    else:
        print("ℹ️  Pas de self-transfer.csv, ranking basé uniquement sur Google Flights")
    
    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print(f"💾 Ranking final sauvé : {FINAL_RANKING_CSV}")
    print_final_report(final)


def main_self_transfer_only():
    google_results = load_flights_from_csv(GOOGLE_FLIGHTS_CSV)
    if not google_results:
        print("❌ Pas de CSV Google Flights, lance d'abord le run complet ou --google-only")
        return
    print(f"📂 {len(google_results)} résultats Google chargés")
    
    self_transfer_results = run_self_transfer_builder(google_results)
    save_flights_to_csv(self_transfer_results, SELF_TRANSFER_CSV)
    
    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_from_csv():
    google_results = load_flights_from_csv(GOOGLE_FLIGHTS_CSV)
    self_transfer_results = load_flights_from_csv(SELF_TRANSFER_CSV)
    print(f"📂 Rechargement : {len(google_results)} Google + {len(self_transfer_results)} Self-transfer")
    
    final = aggregate_and_rank(google_results, self_transfer_results)
    save_flights_to_csv(final, FINAL_RANKING_CSV)
    print_final_report(final)


def main_clear_cache():
    from cache import clear_cache
    clear_cache()


def main_force_prefilter():
    from prefilter import prefilter_routes
    prefilter_routes(force_refresh=True)


def main_cache_stats():
    from cache import cache_stats
    cache_stats()


def print_usage():
    print("Usage:")
    print("  python main.py                       # Run complet (Phase 1 calendar + Phase 2 fast-flights + self-transfer)")
    print("  python main.py --legacy              # Pipeline legacy (skip Phase 1)")
    print("  python main.py --calendar-only       # Phase 1 seule, dump calendar_matrix.csv")
    print("  python main.py --google-only         # Google Flights uniquement (utilise Phase 1 si activée)")
    print("  python main.py --self-transfer-only  # Self-transfer uniquement")
    print("  python main.py --from-csv            # Re-rank depuis CSVs (instantané)")
    print("  python main.py --clear-cache         # Vide le cache")
    print("  python main.py --force-prefilter     # Force un nouveau préfiltrage")
    print("  python main.py --cache-stats         # Stats du cache")
    print("  python main.py --help                # Cette aide")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--from-csv":
            main_from_csv()
        elif cmd == "--self-transfer-only":
            main_self_transfer_only()
        elif cmd == "--google-only":
            main_google_only()
        elif cmd == "--legacy":
            main_legacy()
        elif cmd == "--calendar-only":
            main_calendar_only()
        elif cmd == "--clear-cache":
            main_clear_cache()
        elif cmd == "--force-prefilter":
            main_force_prefilter()
        elif cmd == "--cache-stats":
            main_cache_stats()
        elif cmd in ("-h", "--help"):
            print_usage()
        else:
            print(f"❌ Commande inconnue : {cmd}\n")
            print_usage()
    else:
        main()
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "import main; print('ok')"`
Expected: `ok` (with the fast-flights monkey-patch line printing).

- [ ] **Step 3: Verify CLI help**

Run: `uv run python main.py --help`
Expected: usage block with `--legacy` and `--calendar-only` listed.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(main): orchestrate Phase 1 + Phase 2 with --calendar-only / --legacy CLI"
```

---

## Task 19: Run full test suite

**Files:** none modified

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: all tests PASS (no Playwright tests are run; smoke E2E is manual).

- [ ] **Step 2: Run --cache-stats to confirm calendar dir is created**

Run: `uv run python main.py --cache-stats`
Expected: line includes `0 calendar` (or N if you ran the smoke test from Task 14).

- [ ] **Step 3: No commit needed (test-only step)**

---

## Task 20: End-to-end smoke validation

**Files:** none modified

This is a manual E2E validation, not automated. Skip in CI.

- [ ] **Step 1: Run --calendar-only on the full route set**

Run: `time uv run python main.py --calendar-only`
Expected: completes in <5 minutes for 12 routes (with cache cold). `data/calendar_matrix.csv` created with thousands of rows. Inspect a few lines:

Run: `head -20 data/calendar_matrix.csv`
Expected: rows like `CDG,LIM,2026-07-02,2026-07-25,23,1107.0,3,5,...`.

- [ ] **Step 2: Sanity check distribution**

Run: `uv run python -c "
import csv
from collections import Counter
with open('data/calendar_matrix.csv') as f:
    rows = list(csv.DictReader(f))
print(f'Total cells: {len(rows)}')
print(f'Routes covered: {len({(r[\"dep\"], r[\"arrival\"]) for r in rows})}')
prices = [float(r['prix']) for r in rows]
print(f'Price range: €{min(prices):.0f} - €{max(prices):.0f}')
print(f'Median price: €{sorted(prices)[len(prices)//2]:.0f}')
"`
Expected: ≥10 routes covered, prices in €300–€3000 range, ≥2000 cells total (12 routes × ~200 cells/route).

- [ ] **Step 3: Run full pipeline (Phase 1 + Phase 2 + self-transfer)**

Run: `time uv run python main.py`
Expected: completes in <30 minutes (vs hours for legacy). `data/final_ranking.csv` populated.

- [ ] **Step 4: Compare a route's prices vs legacy run**

Pick one route (e.g. CDG→LIM) and verify the cheapest combos in `final_ranking.csv` are coherent (within ±10%) with what fast-flights returned previously. Spot-check 3 combos.

- [ ] **Step 5: Commit any final tweaks if needed; otherwise tag the milestone**

```bash
git tag -a calendar-picker-v1 -m "Calendar Picker pivot v1 — Phase 1 + Phase 2 ciblée"
```

---

## Self-review checklist

Going through the spec sections to confirm coverage:

| Spec section | Plan task(s) |
|---|---|
| `CalendarCell` dataclass | Task 2 |
| Endpoint capture / response parsing (XSSI + chunked + wrb.fr + cells) | Tasks 3, 4, 5, 6, 7 |
| Sliding strategy (scroll right + scroll down, click pair) | Task 14 |
| Selectors (jsname=KqtnKd, aria-label="Scroll right/down") | Task 14 |
| Stealth Playwright duplicated from fast_flights_patch | Task 12 |
| URL building reusing TFSData | Task 13 |
| Cache per slide (data/cache/calendar/) | Tasks 9, 15 |
| `cache_stats` extension | Task 10 |
| `filter_and_select_top_n` (weekday + duration + price + range + top-N) | Task 11 |
| `combos_override` injection in fast_flights | Task 17 |
| Config additions (USE_CALENDAR_PHASE, TOP_COMBOS_PHASE2, etc.) | Task 8 |
| `main.py` orchestration + `--calendar-only` / `--legacy` | Task 18 |
| Error handling: phase 1 returns [] → log + invite legacy (no auto-fallback) | Task 18 (Step 1, `_run_phase1_then_phase2`) |
| End-to-end validation | Tasks 19, 20 |
| pure-httpx v2 | Hors scope (mentionné dans spec section "Optimisations futures") |

Type/name consistency check:
- `CalendarCell` fields (`date_aller`, `date_retour`, `dep`, `arrival`, `prix`, `deeplink_token`) — used identically across Tasks 2, 6, 7, 9, 11, 14, 15, 16
- `scrape_calendar_for_route` signature matches between Tasks 14 and 15 (cache wrap)
- `_scrape_calendar_for_route_uncached` is referenced from Task 16 (process_route) and defined in Task 15 — consistent
- `filter_and_select_top_n(cells, top_n)` returns `list[tuple]` of `(date_aller, date_retour, duration, dep, arrival)` — consumed identically by `combos_override` in Task 17

No placeholders, no TBDs, no "similar to Task N" handwaves.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-10-calendar-picker.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
