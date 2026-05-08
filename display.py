"""Helpers de rendu rich partagés.

Console singleton + helpers de coloration (gradients, badges, marqueurs) utilisés
par le rapport final. Stateless : tous les helpers prennent leurs bornes en
paramètre, jamais de cache global.
"""

from rich.console import Console
from rich.text import Text


_console: Console | None = None


def get_console() -> Console:
    global _console
    if _console is None:
        _console = Console()
    return _console


# Seuils du delta % (écart relatif au minimum). Tunables.
DELTA_PCT_GREEN_MAX = 5.0
DELTA_PCT_YELLOW_MAX = 20.0


def _gradient_style(ratio: float) -> str:
    """ratio ∈ [0, 1] où 0 = best (vert) et 1 = worst (rouge)."""
    if ratio <= 0.33:
        return "green"
    if ratio <= 0.66:
        return "yellow"
    return "red"


def _safe_ratio(value: float, vmin: float, vmax: float) -> float:
    if vmax <= vmin:
        return 0.0
    return max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))


def color_price(value: float, vmin: float, vmax: float, *, prefix: str = "€") -> Text:
    style = _gradient_style(_safe_ratio(value, vmin, vmax))
    return Text(f"{prefix}{value:.0f}", style=style)


def color_score(value: float, vmin: float, vmax: float) -> Text:
    style = _gradient_style(_safe_ratio(value, vmin, vmax))
    return Text(f"{value:.0f}", style=style)


def color_duration(minutes: int, vmin: int, vmax: int) -> Text:
    style = _gradient_style(_safe_ratio(minutes, vmin, vmax))
    h, m = divmod(minutes, 60)
    label = f"{h}h{m:02d}" if m else f"{h}h"
    return Text(label, style=style)


def color_delta_pct(pct: float) -> Text:
    if pct <= 0.01:
        return Text("0.0%", style="green dim")
    if pct <= DELTA_PCT_GREEN_MAX:
        style = "green"
    elif pct <= DELTA_PCT_YELLOW_MAX:
        style = "yellow"
    else:
        style = "red"
    return Text(f"+{pct:.1f}%", style=style)


def color_stops(n: int) -> Text:
    if n == 0:
        return Text("0", style="green bold")
    if n == 1:
        return Text("1", style="yellow")
    return Text(str(n), style="red")


def source_badge(source: str) -> Text:
    if source == "google_flights":
        return Text("🛫 GF", style="cyan")
    if source == "self_transfer":
        return Text("🔀 ST", style="magenta")
    return Text(source, style="dim")


def st_marker(self_transfer: bool) -> Text:
    if self_transfer:
        return Text("⚠️", style="yellow bold")
    return Text("")
