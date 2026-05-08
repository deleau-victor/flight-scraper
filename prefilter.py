"""Préfiltrage des routes : skip celles qui n'ont jamais de vols + hot zones.

Pour chaque route (dep, arr), on teste ~12 dates réparties dans la période.
Les dates où des vols sont trouvés génèrent des "hot zones" = plages temporelles
[date - 7j, date + 7j] (fusionnées si chevauchement). Lors du scan principal, on
ne garde que les combos dont la date_aller tombe dans une hot zone de la route.

But : ne tester que les zones où Google Flights a des résultats réels, sans
gaspiller de timeout sur les zones désertes.
"""

import json
import os
import asyncio
import time
from datetime import date, datetime, timedelta
from fast_flights import FlightData, Passengers, get_flights

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import (
    DEPARTURE_AIRPORTS, ARRIVAL_AIRPORTS,
    START_DATE, END_DATE,
    PARALLEL_WORKERS, ROUTE_VALIDITY_TTL_DAYS,
)

ROUTE_VALIDITY_FILE = "data/route_validity.json"
TEST_DATES_PER_ROUTE = 12
HOT_ZONE_RADIUS_DAYS = 7


def _generate_test_dates(num_dates: int = TEST_DATES_PER_ROUTE) -> list[date]:
    total_days = (END_DATE - START_DATE).days
    if total_days < num_dates:
        return [START_DATE + timedelta(days=i) for i in range(min(num_dates, total_days))]

    interval = total_days / num_dates
    return [START_DATE + timedelta(days=int(interval * i + interval / 2)) for i in range(num_dates)]


def _compute_hot_zones(
    valid_dates: list[date],
    radius_days: int = HOT_ZONE_RADIUS_DAYS,
) -> list[tuple[date, date]]:
    """Pour chaque date validée, étend en [d-radius, d+radius] (clampé sur la
    fenêtre globale), puis fusionne les ranges qui se chevauchent."""
    if not valid_dates:
        return []

    ranges = sorted(
        (
            max(START_DATE, d - timedelta(days=radius_days)),
            min(END_DATE, d + timedelta(days=radius_days)),
        )
        for d in valid_dates
    )

    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _hot_zones_to_json(zones: list[tuple[date, date]]) -> list[list[str]]:
    return [[s.isoformat(), e.isoformat()] for s, e in zones]


def _hot_zones_from_json(data: list) -> list[tuple[date, date]]:
    out = []
    for item in data:
        try:
            out.append((date.fromisoformat(item[0]), date.fromisoformat(item[1])))
        except (ValueError, IndexError, TypeError):
            continue
    return out


def is_date_in_hot_zones(d: date, zones: list[tuple[date, date]]) -> bool:
    return any(start <= d <= end for start, end in zones)


def _render_routes_matrix(routes: dict, title: str) -> Table:
    """Build une matrice Rich : départs × arrivées.

    Cellules :
    - ✅ N z(s) = route valide avec N hot zones
    - ❌ morte  = route préfiltrée comme sans vols
    - …        = route pas encore testée (utilisé seulement pendant un live test)
    """
    table = Table(
        title=title,
        title_style="bold cyan",
        header_style="bold",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("From \\ To", style="bold dim", justify="right")
    for arr in ARRIVAL_AIRPORTS:
        table.add_column(arr, justify="center")

    for dep in DEPARTURE_AIRPORTS:
        row = [Text(dep, style="bold")]
        for arr in ARRIVAL_AIRPORTS:
            info = routes.get((dep, arr))
            if info is None:
                row.append(Text("…", style="dim"))
            elif info["is_valid"]:
                n_zones = len(info["hot_zones"])
                # Distingue 1 zone (couverture partielle) de plusieurs (couverture morcelée)
                if n_zones == 1:
                    row.append(Text(f"✅ 1 zone", style="green"))
                else:
                    row.append(Text(f"✅ {n_zones} zones", style="green bold"))
            else:
                row.append(Text("❌ morte", style="red"))
        table.add_row(*row)

    return table


def _render_test_plan(
    routes_to_test: list,
    total_routes: int,
    test_dates: list[date],
    workers: int,
    radius_days: int,
) -> Panel:
    """Panel récapitulant le plan de test : combien, quelles dates, estimation."""
    estimate_min = len(routes_to_test) * len(test_dates) * 11 / workers / 60

    # Dates en bandeau compact : "06/07 (Mon) · 16/07 (Thu) · ..."
    dates_str = " · ".join(
        f"{d.strftime('%d/%m')} ({d.strftime('%a')})" for d in test_dates
    )

    info = Text.assemble(
        ("🧪 Routes à tester     : ", "bold"),
        (f"{len(routes_to_test)} / {total_routes}\n", "green"),
        ("📅 Dates par route     : ", "bold"),
        (f"{len(test_dates)}\n", ""),
        ("🔥 Rayon hot zones     : ", "bold"),
        (f"±{radius_days} jours\n", ""),
        ("⚙️  Workers parallèles  : ", "bold"),
        (f"{workers}\n", ""),
        ("⏱️  Estimation initiale : ", "bold"),
        (f"~{estimate_min:.1f} min", "yellow"),
        (" (raffinée en live)\n\n", "dim"),
        ("📅 Dates testées :\n  ", "bold"),
        (dates_str, "cyan"),
    )

    return Panel(
        info,
        title="[bold]🧪 Test plan[/]",
        border_style="cyan",
        padding=(0, 1),
    )


def _load_validity() -> dict:
    if not os.path.exists(ROUTE_VALIDITY_FILE):
        return {}
    try:
        with open(ROUTE_VALIDITY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_validity(data: dict):
    os.makedirs(os.path.dirname(ROUTE_VALIDITY_FILE), exist_ok=True)
    with open(ROUTE_VALIDITY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _is_validity_fresh(checked_at_str: str) -> bool:
    try:
        checked_at = datetime.fromisoformat(checked_at_str)
        age = datetime.now() - checked_at
        return age < timedelta(days=ROUTE_VALIDITY_TTL_DAYS)
    except (ValueError, TypeError):
        return False


def _is_entry_usable(entry: dict) -> bool:
    """Une entrée est utilisable si elle est fraîche ET dans le nouveau format
    (champ hot_zones présent — sinon c'est l'ancien schéma 3-dates, à retester)."""
    if "hot_zones" not in entry:
        return False
    return _is_validity_fresh(entry.get("checked_at", ""))


class PrefilterProgress:
    """Barre de progression live + ETA pondéré succès/échec.

    Formule : avg_per_test = avg_success × P(success) + avg_fail × P(fail).
    Wall-clock ETA = remaining × avg_per_test / workers (parallélisme).
    """

    BAR_WIDTH = 30
    LINE_WIDTH = 110

    def __init__(self, total: int, workers: int):
        self.total = total
        self.workers = workers
        self.done = 0
        self.success_count = 0
        self.fail_count = 0
        self.success_total_seconds = 0.0
        self.fail_total_seconds = 0.0
        self.start_time = time.perf_counter()
        self.lock = asyncio.Lock()

    async def record(self, *, success: bool, duration: float):
        async with self.lock:
            self.done += 1
            if success:
                self.success_count += 1
                self.success_total_seconds += duration
            else:
                self.fail_count += 1
                self.fail_total_seconds += duration
            self._render()

    def _render(self):
        pct = self.done / self.total if self.total else 1.0
        filled = int(self.BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)

        if self.done == 0:
            eta_str = "—"
        else:
            success_rate = self.success_count / self.done
            fail_rate = self.fail_count / self.done
            avg_success = (
                self.success_total_seconds / self.success_count
                if self.success_count else 0.0
            )
            avg_fail = (
                self.fail_total_seconds / self.fail_count
                if self.fail_count else 0.0
            )
            avg_per_test = avg_success * success_rate + avg_fail * fail_rate
            remaining = self.total - self.done
            eta_seconds = remaining * avg_per_test / self.workers if avg_per_test else 0
            eta_str = self._fmt_time(eta_seconds)

        elapsed_str = self._fmt_time(time.perf_counter() - self.start_time)

        line = (
            f"🔍 [{bar}] {self.done:>3}/{self.total} ({pct * 100:>3.0f}%) | "
            f"✅ {self.success_count:>3} ❌ {self.fail_count:>3} | "
            f"écoulé {elapsed_str:>6} | ETA {eta_str:>6}"
        )
        print(f"\r{line:<{self.LINE_WIDTH}}", end="", flush=True)

    def finish(self):
        # Newline final pour que les prints suivants ne se collent pas à la barre
        print()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"


async def _test_route_async(
    from_ap: str,
    to_ap: str,
    semaphore: asyncio.Semaphore,
    progress: "PrefilterProgress",
):
    test_dates = _generate_test_dates()
    valid_dates = []

    async with semaphore:
        for test_date in test_dates:
            t0 = time.perf_counter()
            success = False
            try:
                result = await asyncio.to_thread(
                    get_flights,
                    flight_data=[FlightData(
                        date=test_date.isoformat(),
                        from_airport=from_ap,
                        to_airport=to_ap,
                    )],
                    trip="one-way",
                    seat="economy",
                    passengers=Passengers(adults=1),
                    fetch_mode="local",
                )
                if result and result.flights and len(result.flights) > 0:
                    valid_dates.append(test_date)
                    success = True
            except Exception:
                pass

            duration = time.perf_counter() - t0
            await progress.record(success=success, duration=duration)
            await asyncio.sleep(1)

    return (from_ap, to_ap, valid_dates)


async def prefilter_routes_async(force_refresh: bool = False) -> dict:
    """Returns: {(dep, arr): {"is_valid": bool, "hot_zones": [(date, date), ...]}}"""
    print("\n" + "═" * 80)
    print(f"{'🔍 PRÉFILTRAGE DES ROUTES (hot zones)':^80}")
    print("═" * 80 + "\n")

    validity = _load_validity()

    routes_to_test = []
    cached_routes = {}

    for dep in DEPARTURE_AIRPORTS:
        for arrival in ARRIVAL_AIRPORTS:
            route_key = f"{dep}->{arrival}"
            existing = validity.get(route_key)

            if not force_refresh and existing and _is_entry_usable(existing):
                cached_routes[(dep, arrival)] = {
                    "is_valid": existing.get("is_valid", False),
                    "hot_zones": _hot_zones_from_json(existing.get("hot_zones", [])),
                }
                continue

            routes_to_test.append((dep, arrival))

    console = Console()

    if cached_routes:
        valid_count = sum(1 for v in cached_routes.values() if v["is_valid"])
        dead_count = len(cached_routes) - valid_count
        title = (
            f"📦 {len(cached_routes)} routes en cache "
            f"({valid_count} ✅ vivantes / {dead_count} ❌ mortes)"
        )
        console.print(_render_routes_matrix(cached_routes, title))

    if not routes_to_test:
        console.print("\n[bold green]✨ Toutes les routes sont en cache, pas de test à faire[/]\n")
        return cached_routes

    test_dates = _generate_test_dates()
    total_routes = len(DEPARTURE_AIRPORTS) * len(ARRIVAL_AIRPORTS)
    console.print()
    console.print(_render_test_plan(
        routes_to_test=routes_to_test,
        total_routes=total_routes,
        test_dates=test_dates,
        workers=PARALLEL_WORKERS,
        radius_days=HOT_ZONE_RADIUS_DAYS,
    ))
    console.print()

    semaphore = asyncio.Semaphore(PARALLEL_WORKERS)
    total_tests = len(routes_to_test) * len(test_dates)
    progress = PrefilterProgress(total=total_tests, workers=PARALLEL_WORKERS)
    tasks = [
        _test_route_async(dep, arrival, semaphore, progress)
        for (dep, arrival) in routes_to_test
    ]
    results_async = await asyncio.gather(*tasks)
    progress.finish()
    print()

    tested_zones_detail = []  # (dep, arr, [(start, end), ...]) pour affichage groupé
    for (dep, arr, valid_dates) in results_async:
        is_valid = len(valid_dates) > 0
        hot_zones = _compute_hot_zones(valid_dates) if is_valid else []

        route_key = f"{dep}->{arr}"
        validity[route_key] = {
            "is_valid": is_valid,
            "checked_at": datetime.now().isoformat(),
            "test_dates": [d.isoformat() for d in test_dates],
            "valid_test_dates": [d.isoformat() for d in valid_dates],
            "hot_zones": _hot_zones_to_json(hot_zones),
        }
        cached_routes[(dep, arr)] = {
            "is_valid": is_valid,
            "hot_zones": hot_zones,
        }
        if hot_zones:
            tested_zones_detail.append((dep, arr, hot_zones, len(valid_dates), len(test_dates)))

    _save_validity(validity)

    # Matrice finale (toutes les routes, cachées + nouvellement testées)
    valid_count = sum(1 for v in cached_routes.values() if v["is_valid"])
    dead_count = len(cached_routes) - valid_count
    title = (
        f"📊 Résultat préfiltrage "
        f"({valid_count} ✅ vivantes / {dead_count} ❌ mortes)"
    )
    console.print(_render_routes_matrix(cached_routes, title))

    # Détail des hot zones pour les routes nouvellement testées (séparé pour pas
    # surcharger la matrice)
    if tested_zones_detail:
        console.print("\n[bold]🔥 Hot zones des routes testées :[/]")
        for dep, arr, zones, valid_n, total_n in tested_zones_detail:
            zones_str = ", ".join(
                f"{s.isoformat()}→{e.isoformat()} ({(e - s).days}j)"
                for s, e in zones
            )
            console.print(
                f"   [green]{dep}→{arr}[/] [dim]({valid_n}/{total_n} dates)[/] : {zones_str}"
            )

    return cached_routes


def prefilter_routes(force_refresh: bool = False) -> dict:
    return asyncio.run(prefilter_routes_async(force_refresh))
