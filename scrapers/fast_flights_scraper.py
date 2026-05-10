"""Scraper Google Flights — async + cache + préfiltrage"""

import asyncio
import random
import time
from collections import deque
from datetime import date
from fast_flights import FlightData, Passengers, Result, get_flights

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from config import (
    MAX_DURATION_HOURS, MIN_PRICE, MAX_PRICE,
    THROTTLE_MIN, THROTTLE_MAX, TOP_FLIGHTS_PER_COMBO,
    MAX_RETRIES,
    PARALLEL_WORKERS, USE_CACHE, USE_PREFILTER,
)
from models import FlightOffer
from utils import (
    parse_price, parse_duration_to_minutes, format_duration,
    infer_layover, get_transport_cost, get_arrival_transport_cost,
    calculate_score, generate_combinations,
)
from cache import get_round_trip_cache, save_round_trip_cache, cache_stats
from prefilter import prefilter_routes_async, is_date_in_hot_zones


_semaphore: asyncio.Semaphore | None = None


class ScraperTracker:
    """Live tracker pour le scraper : barre + stats + 10 lignes roulantes.

    ETA pondéré : avg_per_test = avg_succès × P(succès) + avg_échec × P(échec).
    Wall-clock ETA = (total - done) × avg_per_test / workers.

    Définitions :
    - succès = combo a produit des vols utiles (cache_with_flights ou network ok)
    - échec  = combo n'a rien produit (vide, erreur)
    """

    MAX_RESULTS = 10
    BAR_WIDTH = 40

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

        self.from_cache = 0
        self.from_network = 0
        self.empty = 0
        self.errors = 0

        # Pré-rempli pour que la zone Live ait une hauteur constante dès t=0
        self.last_results: deque = deque(
            [Text(" ")] * self.MAX_RESULTS,
            maxlen=self.MAX_RESULTS,
        )

    async def record(self, *, line: Text, kind: str, success: bool, duration: float):
        async with self.lock:
            self.done += 1
            if success:
                self.success_count += 1
                self.success_total_seconds += duration
            else:
                self.fail_count += 1
                self.fail_total_seconds += duration

            if kind == "cache":
                self.from_cache += 1
            elif kind == "network":
                self.from_network += 1
            elif kind == "empty":
                self.empty += 1
            elif kind == "error":
                self.errors += 1

            self.last_results.append(line)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"

    def _eta_str(self) -> str:
        if self.done == 0:
            return "—"
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
        return self._fmt_time(eta_seconds)

    def __rich__(self):
        pct = self.done / self.total if self.total else 1.0
        filled = int(self.BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        elapsed = self._fmt_time(time.perf_counter() - self.start_time)
        eta = self._eta_str()

        header = Text.assemble(
            "🛫 [",
            (bar, "cyan"),
            "] ",
            (f"{self.done}/{self.total}", "bold"),
            (f" ({pct * 100:.0f}%) ", "dim"),
            "| ",
            (f"écoulé {elapsed} ", "yellow"),
            "| ",
            (f"ETA {eta}", "bold green"),
        )

        stats = Text.assemble(
            "📦 ", (f"{self.from_cache}", "bold blue"), " cache  ",
            "🌐 ", (f"{self.from_network}", "bold cyan"), " net  ",
            "⚠️  ", (f"{self.empty}", "bold yellow"), " vides  ",
            "❌ ", (f"{self.errors}", "bold red"), " err",
        )

        # Snapshot atomique du deque pour éviter les races avec le refresh thread
        results_snapshot = list(self.last_results)
        return Group(header, stats, Text(""), *results_snapshot)


def search_flights_sync(
    date_aller: date, date_retour: date, 
    dep_airport: str, arrival_airport: str,
) -> Result:
    return get_flights(
        flight_data=[
            FlightData(
                date=date_aller.isoformat(),
                from_airport=dep_airport,
                to_airport=arrival_airport,
            ),
            FlightData(
                date=date_retour.isoformat(),
                from_airport=arrival_airport,
                to_airport=dep_airport,
            ),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=1),
        fetch_mode="local",
    )


async def search_with_retry_async(
    date_aller, date_retour, dep_airport, arrival_airport, 
    max_retries=MAX_RETRIES,
):
    """Retourne (result, from_cache)"""
    if USE_CACHE:
        # I/O ultra-rapide (0.14ms/hit mesuré) : pas la peine de wrapper en
        # to_thread, l'overhead de scheduler dépasse le gain.
        cached = get_round_trip_cache(date_aller, date_retour, dep_airport, arrival_airport)
        if cached is not None:
            return cached, True

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.to_thread(
                search_flights_sync, date_aller, date_retour, dep_airport, arrival_airport
            )
            if USE_CACHE and result:
                save_round_trip_cache(date_aller, date_retour, dep_airport, arrival_airport, result)
            return result, False
        except Exception as e:
            last_error = e
            error_name = type(e).__name__

            # Pas de retry sur TimeoutError : indique probablement
            # "no result round-trip" pour cette combinaison, pas un blip transient.
            # Retry coûterait 35-45s pour rien.
            if "Timeout" in error_name:
                raise

            if "TargetClosed" in error_name or "BrowserClosed" in error_name:
                wait = (attempt + 1) * 15
            else:
                wait = (attempt + 1) * 5

            if attempt < max_retries:
                await asyncio.sleep(wait)
    raise last_error


def flight_to_offer(
    f, date_aller, date_retour, duration, 
    dep, arrival, current_price,
) -> FlightOffer:
    duree_min = parse_duration_to_minutes(getattr(f, 'duration', None))
    prix = parse_price(getattr(f, 'price', None))
    name = getattr(f, 'name', 'N/A')
    nb_escales = int(getattr(f, 'stops', 0)) if str(getattr(f, 'stops', 0)).isdigit() else 0
    transport_cost = get_transport_cost(dep)
    arrival_cost = get_arrival_transport_cost(arrival)
    
    return FlightOffer(
        source="google_flights",
        depart_date=date_aller.isoformat(),
        depart_jour=date_aller.strftime("%a"),
        retour_date=date_retour.isoformat(),
        retour_jour=date_retour.strftime("%a"),
        nuits=duration - 1,
        from_airport=dep,
        to_airport=arrival,
        prix_billet=prix,
        transport_cost=transport_cost,
        arrival_transport_cost=arrival_cost,
        prix_total=prix + transport_cost + arrival_cost if prix != float('inf') else float('inf'),
        prix_str=getattr(f, 'price', 'N/A'),
        compagnies=name,
        escale=infer_layover(name),
        duree_min=duree_min,
        duree_fmt=format_duration(duree_min),
        nb_escales=nb_escales,
        depart_h=getattr(f, 'departure', ''),
        arrivee_h=getattr(f, 'arrival', ''),
        j_plus=getattr(f, 'arrival_time_ahead', ''),
        is_best=getattr(f, 'is_best', False),
        self_transfer=False,
        tendance=current_price or "",
        score=calculate_score(prix, duree_min, nb_escales, dep, arrival, self_transfer=False),
    )


async def process_combo(
    combo_idx: int, total: int,
    date_aller, date_retour, duration, dep, arrival,
    results_lock: asyncio.Lock,
    results: list,
    tracker: "ScraperTracker",
):
    """Pipeline :
    1. Cache check HORS sémaphore (lecture disque locale, pas besoin de rate-limit)
    2. Si miss : sémaphore + network call + throttle (workers serialisent ici)
    3. Post-process (filter + sort + build offers) HORS sémaphore (CPU local)

    Effet : les cache hits ne sont plus bloqués derrière les errors qui occupent
    les 4 slots workers pendant 12-25s. Ils flushent en parallèle via l'event loop.
    """
    t0 = time.perf_counter()
    progress_str = f"[{combo_idx:>3}/{total}]"

    # === Phase 1 : cache check (hors sémaphore) ===
    cached = (
        get_round_trip_cache(date_aller, date_retour, dep, arrival)
        if USE_CACHE else None
    )
    from_cache = cached is not None
    res = cached
    error: Exception | None = None

    # === Phase 2 : si miss, network call (sémaphore + throttle) ===
    if not from_cache:
        async with _semaphore:
            try:
                res, _ = await search_with_retry_async(
                    date_aller, date_retour, dep, arrival
                )
            except Exception as e:
                error = e
            # Throttle dans le sémaphore : le worker reste occupé pendant la pause
            await asyncio.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))

    # === Phase 3 : post-process (hors sémaphore) ===
    if error is not None:
        kind = "error"
        success = False
        first_line = (str(error).splitlines() or [""])[0]
        err_msg = f"{type(error).__name__}: {first_line[:80]}"
        line = Text(
            f"{progress_str} ❌ {dep}→{arrival} {date_aller}: {err_msg}",
            style="red", no_wrap=True, overflow="ellipsis",
        )
    elif res and res.flights:
        valid = []
        for f in res.flights:
            prix = parse_price(getattr(f, "price", None))
            duree_min = parse_duration_to_minutes(getattr(f, "duration", None))
            if MIN_PRICE < prix < MAX_PRICE and duree_min <= MAX_DURATION_HOURS * 60:
                valid.append(f)

        if not valid:
            cache_marker = "📦" if from_cache else "🌐"
            kind = "empty"
            success = False
            line = Text(
                f"{progress_str} {cache_marker} ⚠️  {dep}→{arrival} {date_aller}: aucun vol valide",
                style="yellow", no_wrap=True, overflow="ellipsis",
            )
        else:
            valid.sort(key=lambda f: calculate_score(
                parse_price(f.price),
                parse_duration_to_minutes(f.duration),
                int(f.stops) if str(f.stops).isdigit() else 0,
                dep, arrival,
            ))

            offers_to_add = [
                flight_to_offer(f, date_aller, date_retour, duration, dep, arrival, res.current_price)
                for f in valid[:TOP_FLIGHTS_PER_COMBO]
            ]

            async with results_lock:
                results.extend(offers_to_add)

            best = valid[0]
            cache_marker = "📦" if from_cache else "🌐"
            kind = "cache" if from_cache else "network"
            success = True
            line = Text(
                f"{progress_str} {cache_marker} ✅ {dep}→{arrival} "
                f"{date_aller}({date_aller.strftime('%a')}) → "
                f"{date_retour}({date_retour.strftime('%a')}) ({duration}j) | "
                f"min: {best.price} ({best.duration}, {best.stops}esc)",
                style="green", no_wrap=True, overflow="ellipsis",
            )
    else:
        kind = "empty"
        success = False
        line = Text(
            f"{progress_str} ⚠️  {dep}→{arrival} {date_aller}: aucun vol",
            style="yellow", no_wrap=True, overflow="ellipsis",
        )

    elapsed = time.perf_counter() - t0
    await tracker.record(line=line, kind=kind, success=success, duration=elapsed)


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