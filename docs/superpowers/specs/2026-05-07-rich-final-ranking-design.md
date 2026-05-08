# Rich-based final ranking report — design

## Context

The pipeline (`prefilter.py`, `scrapers/fast_flights_scraper.py`) already renders
its phases with `rich`: matrix tables, live trackers, panels. The final report —
the artifact the user actually consumes after every run — is still printed via
plain `print()` in `aggregator.py::print_final_report`, with manual `═` dividers,
fixed-width column alignment via f-strings, and no semantic coloring.

This design migrates `print_final_report` to a `rich`-based renderer with
semantic color-coding, a header dashboard, and proper `rich.Table` layouts. It
also factors out shared display helpers so prefilter and scrapers can converge
on the same visual idiom over time.

## Goals

- Final ranking report rendered entirely with `rich` (Tables, Panels, styled
  Text) — no more raw `print` + manual padding for tabular data.
- Semantic color-coding on the TOP 30 table (score, prices, duration, stops,
  self-transfer, source).
- A header `Panel` summarizing the run (totals, best price, best score, fastest,
  date window).
- Stats tables (per arrival airport, per departure airport, per route) gain a
  `Δ vs min` column with color-coded percentage gap.
- Self-transfer entries kept in a multi-line per-offer format, but rendered as
  individual `Panel`s with a yellow border, plus a final red panel for the
  warning footer.
- Code organized so rendering lives in dedicated modules: `reporting.py`
  (the report itself) and `display.py` (shared helpers).

## Non-goals

- No changes to ranking logic, scoring, deduplication, or the `FlightOffer`
  model. `aggregator.aggregate_and_rank` keeps its current behavior.
- No changes to how data is persisted (CSV format unchanged).
- No unit tests on rendered output — `rich` output is visual; validation is
  manual via `python main.py --from-csv`.
- No retrofit of `prefilter.py` / `scrapers/fast_flights_scraper.py` to consume
  the new `display.py` helpers in this iteration. They keep their current
  rendering. `display.py` is designed as shared infrastructure but only
  `reporting.py` uses it initially.

## Module layout

### `display.py` (new)

Shared, stateless helpers. No business logic.

- `get_console() -> Console` — module-level singleton, returned by accessor so
  any module can `print` to the same instance.
- `color_price(value: float, vmin: float, vmax: float) -> Text` — gradient
  green → yellow → red mapped to `(value - vmin) / (vmax - vmin)`. When
  `vmax == vmin`, returns the value styled `green` (everything is the minimum).
- `color_score(value: float, vmin: float, vmax: float) -> Text` — same shape as
  `color_price`. Lower score is better.
- `color_duration(minutes: int, vmin: int, vmax: int) -> Text` — same shape;
  lower is better. Returns the formatted `"Xh YYm"` string styled.
- `color_delta_pct(pct: float) -> Text` — formats `+12.3%` / `-5.0%` / `0.0%`.
  Style: `green` for 0% (the minimum), `yellow` up to ~20%, `red` beyond.
  Threshold constants live at module top for tunability.
- `color_stops(n: int) -> Text` — `0 → green`, `1 → yellow`, `≥2 → red`.
- `source_badge(source: str) -> Text` — `"🛫 GF"` cyan for `google_flights`,
  `"🔀 ST"` magenta for `self_transfer`.
- `st_marker(self_transfer: bool) -> Text` — `"⚠️ "` `yellow bold` if True,
  empty `Text("")` otherwise.

Edge case: gradient functions must guard against `vmax == vmin` (single-element
input or fully homogeneous list) to avoid division by zero.

### `reporting.py` (new)

All rendering for the final report. Public API:

- `print_final_report(flights: list[FlightOffer]) -> None` — drops in for the
  current `aggregator.print_final_report`. Same signature, same call sites.

Private renderers, one per section, each producing a `rich` renderable that the
top-level function prints with spacing in between:

- `_render_dashboard(flights) -> Panel`
- `_render_top_score(flights, n=30) -> Table`
- `_render_top_price(flights, n=15) -> Table`
- `_render_top_fastest(flights, n=10) -> Table`
- `_render_arrival_stats(flights) -> Table`
- `_render_departure_stats(flights) -> Table`
- `_render_route_stats(flights) -> Table`
- `_render_source_stats(flights) -> Table`
- `_render_self_transfer_blocks(flights) -> list[Panel]` — list of per-offer
  panels, plus the warning panel as the final element. Returns empty list if
  there are no self-transfer offers.

`print_final_report` early-exits with a styled `"❌ Aucun résultat"` if
`flights` is empty (preserves current behavior).

### `aggregator.py` (modified)

- Drops `print_final_report` (moved to `reporting.py`).
- The `aggregate_and_rank` banner (`"🔀 AGGREGATION & RANKING"`) is rewritten
  using `rich.rule.Rule` + `console.print` for visual consistency with the new
  report. The body lines (`📥 Google Flights : N offres`, etc.) become
  `console.print` calls with light styling but keep the same content.
- `aggregate_and_rank` import from `display` for the shared `Console`.

### `main.py` (modified)

- Imports `print_final_report` from `reporting` instead of `aggregator`.
- The `💾 ... sauvé` and `📂 ... rechargé` lines stay as plain `print()` —
  out of scope for this design. They are operational logs, not part of the
  report.

## Section designs

### Dashboard

A single `Panel` with `border_style="cyan"`, title `"🏆 RANKING FINAL"`. Body
content laid out as labeled rows:

```
Total offres : 384      Fenêtre : 2026-06-01 → 2026-09-30
Sources      : 312 GF + 72 ST

Meilleur prix total : €387  (CDG → BKK, 12 nuits)
Meilleur score      : 142   (ORY → DPS, 14 nuits)
Plus rapide         : 11h45 (CDG → BKK)
```

Implementation: build a `rich.text.Text` with explicit newlines, label in
`bold`, value in `cyan` for emphasis. The dashboard is informational — it does
not use the gradient helpers.

The "Fenêtre" range is computed as `min(f.depart_date for f in flights)` to
`max(f.retour_date for f in flights)` (string comparison works because dates
are ISO-formatted in the data).

### TOP 30 (by score)

`rich.Table` with `box=rich.box.SIMPLE_HEAVY`, `show_lines=False`, title
`"🏆 TOP 30 — RANKING FINAL (par score)"`, title style `bold cyan`.

Columns and styling, in order:

| # | Col | Justify | Style |
|---|-----|---------|-------|
| 1 | `#` | right | normal; `⭐ N` `bold` if `is_best` |
| 2 | `Score` | right | `color_score(score, score_min, score_max)` |
| 3 | `Total` | right | `color_price(prix_total, ...)` prefixed `€` |
| 4 | `Billet` | right | normal (already present in price string) |
| 5 | `Trans` | right | `dim`, prefixed `+` suffixed `€` |
| 6 | `Aller` | left | date in normal, jour in `dim` |
| 7 | `Retour` | left | same as Aller |
| 8 | `N` | right | `dim` |
| 9 | `AP↑` | center | `bold cyan` |
| 10 | `AP↓` | center | `bold cyan` |
| 11 | `Durée` | right | `color_duration(...)` |
| 12 | `E` | center | `color_stops(nb_escales)` |
| 13 | `ST` | center | `st_marker(self_transfer)` |
| 14 | `Compagnie` | left | normal, `Column(no_wrap=True, max_width=25)` |
| 15 | `Escale` | left | `dim`, `max_width=22` |
| 16 | `Source` | center | `source_badge(source)` |

Min/max for gradient bounds are computed once per call from the rendered slice
(top 30), not the full list. This makes color contrast meaningful within the
shown rows.

`is_best=True` rows: keep the ⭐ in the `#` cell, and apply `style="bold"` to
the row via `Table.add_row(..., style="bold")`. (Bold over the colored text
remains readable; we don't override the gradient.)

### TOP 15 (by total price)

Columns: `#`, `Total`, `Billet`, `Aller`, `Retour`, `N`, `AP↑`, `AP↓`, `Durée`,
`E`, `Compagnie`, `Source`. (No `Score`, no `Trans`, no `ST` column — matches
the current TOP 15 schema.) `Source` column keeps the `source_badge`.
Color-coding applies to `Total`, `Durée`, `E`. Min/max bounds computed on the
15 shown rows.

### TOP 10 fastest

Filter `f.duree_min > 0`, sort ascending on `duree_min`, slice 10. Color-coding
on `Durée` (via `color_duration` — short = green by definition of the helper)
and `Total` (via `color_price`). Other columns plain.

### Stats tables (arrival / departure / route)

Each gets a new `Δ vs min` column inserted between `TOTAL min` and the next
column. Computation: for each row, `(min_total_row - min_total_global) /
min_total_global * 100`, where `min_total_global` is the smallest `min_total`
across all rows in that table. The first row (the global minimum) shows
`0.0%` styled `green dim`; subsequent rows use `color_delta_pct`.

Sort order is preserved (ascending on `min_total`), so deltas grow as the
reader scans down.

### Stats by source

Two-row table; no Δ column (low value with so few rows). Columns: `Source`,
`Nb vols`, `Min total`, `Moy total`. `source_badge` in the first column.

### Self-transfer panels

Iterate over `sorted([f for f in flights if f.self_transfer], key=prix_total)`,
take the first 10. Each yields a `Panel`:

- `border_style="yellow"`
- `title=f"#{i} · €{prix_total:.0f} total · {from}→{to} · {nuits} nuits"`
- Body: a `rich.text.Text` with the existing fields (dates, price breakdown,
  companies, duration, escale, optional `legs_detail` formatted as bullet list).

After all per-offer panels, a final `Panel`:

- `border_style="red"`, `title="⚠️  À LIRE"`, body = current warning text.

If no self-transfer offers exist, this section is omitted entirely (no header,
no panels).

## Edge cases

- **Empty flights list** → `❌ Aucun résultat` styled `red bold`. Same as
  current behavior.
- **Single-flight slice** (e.g. only 1 flight passes filters) → gradient
  helpers see `vmin == vmax`, return styled `green` (everything is "best").
- **No self-transfer offers** → entire self-transfer section is skipped.
- **Flight with `duree_min == 0`** (parsing miss) → excluded from TOP 10
  fastest only, included everywhere else. Same as current behavior.
- **Very narrow terminal** → `rich.Table` truncates with ellipsis instead of
  wrapping; `Compagnie` and `Escale` use `no_wrap=True` + `max_width`.

## Validation plan

Manual, not automated. Workflow:

1. Run `python main.py --from-csv` against existing CSVs in `data/`. This is
   instantaneous (no scraping) and exercises the whole report.
2. Visually verify each section renders: dashboard panel, TOP 30, TOP 15,
   TOP 10, three stats tables with Δ column, source stats, self-transfer
   panels + warning.
3. Verify color-coding on a row known to be cheap vs. a row known to be
   expensive — gradients should be visually distinguishable.
4. Edge cases: temporarily empty `final_ranking.csv` → confirm `❌ Aucun
   résultat`. Temporarily filter the CSV to a single flight → confirm no
   crash on gradient bounds.
5. Check rendering on a narrow terminal (`COLUMNS=100`) — tables must not
   collapse.

## Out of scope (explicitly)

- Migrating `prefilter.py` and `scrapers/fast_flights_scraper.py` to use
  `display.py` helpers. They already use `rich` directly; convergence can
  happen later if useful.
- Interactive features (filtering, sorting from the terminal).
- Export to HTML / SVG via `Console.export_html` etc.
- Theming / user-configurable colors.
- The save-line `print()`s in `main.py` (`💾 ... sauvé`).
