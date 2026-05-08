"""Rendu rich du rapport final (ranking + tableaux + self-transfer).

Point d'entrée public : print_final_report(flights). Les renderers privés
construisent chacun un renderable rich (Table ou Panel) que print_final_report
imprime avec un espacement vertical.
"""

from collections import defaultdict

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from models import FlightOffer
from utils import format_duration, get_transport_cost, get_arrival_transport_cost
from display import (
    get_console,
    color_price,
    color_score,
    color_duration,
    color_delta_pct,
    color_stops,
    source_badge,
    st_marker,
)


def print_final_report(flights: list[FlightOffer]) -> None:
    console = get_console()

    if not flights:
        console.print(Text("❌ Aucun résultat", style="red bold"))
        return

    console.print()
    console.print(_render_dashboard(flights))
    console.print()
    console.print(_render_top_score(flights))
    console.print()
    console.print(_render_top_price(flights))
    console.print()
    console.print(_render_top_fastest(flights))
    console.print()
    console.print(_render_arrival_stats(flights))
    console.print()
    console.print(_render_departure_stats(flights))
    console.print()
    console.print(_render_route_stats(flights))
    console.print()
    console.print(_render_source_stats(flights))

    for renderable in _render_self_transfer_blocks(flights):
        console.print()
        console.print(renderable)


# ─────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────

def _render_dashboard(flights: list[FlightOffer]) -> Panel:
    n_total = len(flights)
    n_gf = sum(1 for f in flights if f.source == "google_flights")
    n_st = sum(1 for f in flights if f.source == "self_transfer")

    fenetre_min = min(f.depart_date for f in flights)
    fenetre_max = max(f.retour_date for f in flights)

    best_price = min(flights, key=lambda f: f.prix_total)
    best_score = min(flights, key=lambda f: f.score)
    fastest_pool = [f for f in flights if f.duree_min > 0]
    fastest = min(fastest_pool, key=lambda f: f.duree_min) if fastest_pool else None

    body = Text()
    body.append("Total offres : ", style="bold")
    body.append(f"{n_total}", style="cyan")
    body.append("      Fenêtre : ", style="bold")
    body.append(f"{fenetre_min} → {fenetre_max}", style="cyan")
    body.append("\n")
    body.append("Sources      : ", style="bold")
    body.append(f"{n_gf} GF", style="cyan")
    body.append(" + ")
    body.append(f"{n_st} ST", style="magenta")
    body.append("\n\n")

    body.append("Meilleur prix total : ", style="bold")
    body.append(f"€{best_price.prix_total:.0f}", style="green bold")
    body.append(
        f"  ({best_price.from_airport} → {best_price.to_airport}, "
        f"{best_price.nuits} nuits)\n",
        style="dim",
    )
    body.append("Meilleur score      : ", style="bold")
    body.append(f"{best_score.score:.0f}", style="green bold")
    body.append(
        f"   ({best_score.from_airport} → {best_score.to_airport}, "
        f"{best_score.nuits} nuits)\n",
        style="dim",
    )
    if fastest is not None:
        body.append("Plus rapide         : ", style="bold")
        body.append(format_duration(fastest.duree_min), style="green bold")
        body.append(
            f" ({fastest.from_airport} → {fastest.to_airport})",
            style="dim",
        )

    return Panel(
        body,
        title="🏆 RANKING FINAL",
        title_align="center",
        border_style="cyan",
        padding=(1, 2),
    )


# ─────────────────────────────────────────────────────────────────────
# TOP 30 par score
# ─────────────────────────────────────────────────────────────────────

def _render_top_score(flights: list[FlightOffer], n: int = 30) -> Table:
    rows = flights[:n]
    score_min = min(f.score for f in rows)
    score_max = max(f.score for f in rows)
    total_min = min(f.prix_total for f in rows)
    total_max = max(f.prix_total for f in rows)
    duree_pool = [f.duree_min for f in rows if f.duree_min > 0]
    duree_min = min(duree_pool) if duree_pool else 0
    duree_max = max(duree_pool) if duree_pool else 0

    table = Table(
        title=f"🏆 TOP {n} — RANKING FINAL (par score)",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Billet", justify="right", style="dim")
    table.add_column("Trans", justify="right", style="dim")
    table.add_column("Aller", justify="left")
    table.add_column("Retour", justify="left")
    table.add_column("N", justify="right", style="dim")
    table.add_column("AP↑", justify="center", style="bold cyan")
    table.add_column("AP↓", justify="center", style="bold cyan")
    table.add_column("Durée", justify="right")
    table.add_column("E", justify="center")
    table.add_column("ST", justify="center")
    table.add_column("Compagnie", justify="left", no_wrap=True, max_width=25)
    table.add_column("Escale", justify="left", style="dim", no_wrap=True, max_width=22)
    table.add_column("Source", justify="center")

    for i, f in enumerate(rows, 1):
        idx = Text(f"⭐ {i}", style="bold yellow") if f.is_best else Text(str(i))

        aller = Text()
        aller.append(f.depart_date)
        aller.append(f" {f.depart_jour}", style="dim")
        retour = Text()
        retour.append(f.retour_date)
        retour.append(f" {f.retour_jour}", style="dim")

        if f.duree_min > 0:
            duree_cell = color_duration(f.duree_min, duree_min, duree_max)
        else:
            duree_cell = Text("—", style="dim")

        row_style = "bold" if f.is_best else None

        table.add_row(
            idx,
            color_score(f.score, score_min, score_max),
            color_price(f.prix_total, total_min, total_max),
            f.prix_str,
            f"+{f.transport_cost}€",
            aller,
            retour,
            str(f.nuits),
            f.from_airport,
            f.to_airport,
            duree_cell,
            color_stops(f.nb_escales),
            st_marker(f.self_transfer),
            f.compagnies,
            f.escale,
            source_badge(f.source),
            style=row_style,
        )

    return table


# ─────────────────────────────────────────────────────────────────────
# TOP 15 par prix total
# ─────────────────────────────────────────────────────────────────────

def _render_top_price(flights: list[FlightOffer], n: int = 15) -> Table:
    rows = sorted(flights, key=lambda f: f.prix_total)[:n]
    total_min = min(f.prix_total for f in rows)
    total_max = max(f.prix_total for f in rows)
    duree_pool = [f.duree_min for f in rows if f.duree_min > 0]
    duree_min = min(duree_pool) if duree_pool else 0
    duree_max = max(duree_pool) if duree_pool else 0

    table = Table(
        title=f"💰 TOP {n} PAR PRIX TOTAL",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("#", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Billet", justify="right", style="dim")
    table.add_column("Aller", justify="left")
    table.add_column("Retour", justify="left")
    table.add_column("N", justify="right", style="dim")
    table.add_column("AP↑", justify="center", style="bold cyan")
    table.add_column("AP↓", justify="center", style="bold cyan")
    table.add_column("Durée", justify="right")
    table.add_column("E", justify="center")
    table.add_column("Compagnie", justify="left", no_wrap=True, max_width=25)
    table.add_column("Source", justify="center")

    for i, f in enumerate(rows, 1):
        aller = Text()
        aller.append(f.depart_date)
        aller.append(f" {f.depart_jour}", style="dim")
        retour = Text()
        retour.append(f.retour_date)
        retour.append(f" {f.retour_jour}", style="dim")

        duree_cell = (
            color_duration(f.duree_min, duree_min, duree_max)
            if f.duree_min > 0 else Text("—", style="dim")
        )

        table.add_row(
            str(i),
            color_price(f.prix_total, total_min, total_max),
            f.prix_str,
            aller,
            retour,
            str(f.nuits),
            f.from_airport,
            f.to_airport,
            duree_cell,
            color_stops(f.nb_escales),
            f.compagnies,
            source_badge(f.source),
        )

    return table


# ─────────────────────────────────────────────────────────────────────
# TOP 10 les plus rapides
# ─────────────────────────────────────────────────────────────────────

def _render_top_fastest(flights: list[FlightOffer], n: int = 10) -> Table:
    pool = [f for f in flights if f.duree_min > 0]
    rows = sorted(pool, key=lambda f: f.duree_min)[:n]

    table = Table(
        title=f"⚡ TOP {n} LES PLUS RAPIDES",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )

    if not rows:
        table.add_column("Info")
        table.add_row("Aucune durée valide")
        return table

    duree_min = min(f.duree_min for f in rows)
    duree_max = max(f.duree_min for f in rows)
    total_min = min(f.prix_total for f in rows)
    total_max = max(f.prix_total for f in rows)

    table.add_column("#", justify="right")
    table.add_column("Durée", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Aller", justify="left")
    table.add_column("AP↑", justify="center", style="bold cyan")
    table.add_column("AP↓", justify="center", style="bold cyan")
    table.add_column("Compagnie", justify="left", no_wrap=True, max_width=25)
    table.add_column("Escale", justify="left", style="dim", no_wrap=True, max_width=25)
    table.add_column("Source", justify="center")

    for i, f in enumerate(rows, 1):
        aller = Text()
        aller.append(f.depart_date)
        aller.append(f" {f.depart_jour}", style="dim")

        table.add_row(
            str(i),
            color_duration(f.duree_min, duree_min, duree_max),
            color_price(f.prix_total, total_min, total_max),
            aller,
            f.from_airport,
            f.to_airport,
            f.compagnies,
            f.escale,
            source_badge(f.source),
        )

    return table


# ─────────────────────────────────────────────────────────────────────
# Stats par AP arrivée / départ / route — avec colonne Δ vs min
# ─────────────────────────────────────────────────────────────────────

def _render_arrival_stats(flights: list[FlightOffer]) -> Table:
    by_arrival: dict[str, list[FlightOffer]] = defaultdict(list)
    for f in flights:
        by_arrival[f.to_airport].append(f)

    rows_data = []
    for ap, offers in by_arrival.items():
        min_billet = min(f.prix_billet for f in offers)
        min_total = min(f.prix_total for f in offers)
        durees = [f.duree_min for f in offers if f.duree_min > 0]
        min_duree = min(durees) if durees else 0
        rows_data.append({
            "ap": ap,
            "trans": get_arrival_transport_cost(ap),
            "min_billet": min_billet,
            "min_total": min_total,
            "min_duree": min_duree,
            "n": len(offers),
        })
    rows_data.sort(key=lambda r: r["min_total"])
    global_min_total = rows_data[0]["min_total"] if rows_data else 0

    table = Table(
        title="🎯 STATS PAR AÉROPORT D'ARRIVÉE",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("AP↓", style="bold cyan")
    table.add_column("Trans.dest", justify="right", style="dim")
    table.add_column("Billet min", justify="right")
    table.add_column("TOTAL min", justify="right")
    table.add_column("Δ vs min", justify="right")
    table.add_column("Durée min", justify="right")
    table.add_column("Nb vols", justify="right", style="dim")

    for r in rows_data:
        delta_pct = (
            (r["min_total"] - global_min_total) / global_min_total * 100
            if global_min_total > 0 else 0.0
        )
        duree_cell = (
            Text(format_duration(r["min_duree"])) if r["min_duree"] > 0
            else Text("—", style="dim")
        )
        table.add_row(
            r["ap"],
            f"+{r['trans']}€",
            f"€{r['min_billet']:.0f}",
            f"€{r['min_total']:.0f}",
            color_delta_pct(delta_pct),
            duree_cell,
            str(r["n"]),
        )

    return table


def _render_departure_stats(flights: list[FlightOffer]) -> Table:
    by_dep: dict[str, list[FlightOffer]] = defaultdict(list)
    for f in flights:
        by_dep[f.from_airport].append(f)

    rows_data = []
    for ap, offers in by_dep.items():
        min_billet = min(f.prix_billet for f in offers)
        min_total = min(f.prix_total for f in offers)
        durees = [f.duree_min for f in offers if f.duree_min > 0]
        min_duree = min(durees) if durees else 0
        rows_data.append({
            "ap": ap,
            "trans": get_transport_cost(ap),
            "min_billet": min_billet,
            "min_total": min_total,
            "min_duree": min_duree,
            "n": len(offers),
        })
    rows_data.sort(key=lambda r: r["min_total"])
    global_min_total = rows_data[0]["min_total"] if rows_data else 0

    table = Table(
        title="🛫 STATS PAR AÉROPORT DE DÉPART",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("AP↑", style="bold cyan")
    table.add_column("Trans.", justify="right", style="dim")
    table.add_column("Billet min", justify="right")
    table.add_column("TOTAL min", justify="right")
    table.add_column("Δ vs min", justify="right")
    table.add_column("Durée min", justify="right")
    table.add_column("Nb vols", justify="right", style="dim")

    for r in rows_data:
        delta_pct = (
            (r["min_total"] - global_min_total) / global_min_total * 100
            if global_min_total > 0 else 0.0
        )
        duree_cell = (
            Text(format_duration(r["min_duree"])) if r["min_duree"] > 0
            else Text("—", style="dim")
        )
        table.add_row(
            r["ap"],
            f"+{r['trans']}€",
            f"€{r['min_billet']:.0f}",
            f"€{r['min_total']:.0f}",
            color_delta_pct(delta_pct),
            duree_cell,
            str(r["n"]),
        )

    return table


def _render_route_stats(flights: list[FlightOffer]) -> Table:
    by_route: dict[tuple[str, str], list[FlightOffer]] = defaultdict(list)
    for f in flights:
        by_route[(f.from_airport, f.to_airport)].append(f)

    rows_data = []
    for (dep, arr), offers in by_route.items():
        min_billet = min(f.prix_billet for f in offers)
        min_total = min(f.prix_total for f in offers)
        durees = [f.duree_min for f in offers if f.duree_min > 0]
        min_duree = min(durees) if durees else 0
        rows_data.append({
            "route": f"{dep}→{arr}",
            "min_billet": min_billet,
            "min_total": min_total,
            "min_duree": min_duree,
            "n": len(offers),
        })
    rows_data.sort(key=lambda r: r["min_total"])
    global_min_total = rows_data[0]["min_total"] if rows_data else 0

    table = Table(
        title="🛬 STATS PAR ROUTE",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("Route", style="bold cyan")
    table.add_column("Billet min", justify="right")
    table.add_column("TOTAL min", justify="right")
    table.add_column("Δ vs min", justify="right")
    table.add_column("Durée min", justify="right")
    table.add_column("Nb vols", justify="right", style="dim")

    for r in rows_data:
        delta_pct = (
            (r["min_total"] - global_min_total) / global_min_total * 100
            if global_min_total > 0 else 0.0
        )
        duree_cell = (
            Text(format_duration(r["min_duree"])) if r["min_duree"] > 0
            else Text("—", style="dim")
        )
        table.add_row(
            r["route"],
            f"€{r['min_billet']:.0f}",
            f"€{r['min_total']:.0f}",
            color_delta_pct(delta_pct),
            duree_cell,
            str(r["n"]),
        )

    return table


# ─────────────────────────────────────────────────────────────────────
# Stats par source (pas de Δ, peu de lignes)
# ─────────────────────────────────────────────────────────────────────

def _render_source_stats(flights: list[FlightOffer]) -> Table:
    by_source: dict[str, list[FlightOffer]] = defaultdict(list)
    for f in flights:
        by_source[f.source].append(f)

    table = Table(
        title="📊 STATS PAR SOURCE",
        title_style="bold cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("Source", justify="center")
    table.add_column("Nb vols", justify="right")
    table.add_column("Min total", justify="right")
    table.add_column("Moy total", justify="right")

    for source, offers in by_source.items():
        min_total = min(f.prix_total for f in offers)
        avg_total = sum(f.prix_total for f in offers) / len(offers)
        table.add_row(
            source_badge(source),
            str(len(offers)),
            f"€{min_total:.0f}",
            f"€{avg_total:.0f}",
        )

    return table


# ─────────────────────────────────────────────────────────────────────
# Bloc self-transfer (Panels)
# ─────────────────────────────────────────────────────────────────────

def _render_self_transfer_blocks(flights: list[FlightOffer]) -> list[Panel]:
    self_transfers = sorted(
        [f for f in flights if f.self_transfer],
        key=lambda f: f.prix_total,
    )[:10]

    if not self_transfers:
        return []

    panels: list[Panel] = []

    header = Text()
    header.append("🔀 TOP 10 SELF-TRANSFER", style="bold magenta")
    header.append(" — à réserver en 2 billets séparés", style="dim")
    panels.append(Panel(header, border_style="magenta", padding=(0, 1)))

    for i, f in enumerate(self_transfers, 1):
        body = Text()
        body.append("📅 ", style="bold")
        body.append(f"{f.depart_date} ({f.depart_jour}) → {f.retour_date} ({f.retour_jour})")
        body.append(f"  ·  {f.nuits} nuits\n", style="dim")

        body.append("💶 ", style="bold")
        body.append(f"{f.prix_billet:.0f}€ billet", style="cyan")
        body.append(
            f"  +  {f.transport_cost}€ acheminement dep"
            f"  +  {f.arrival_transport_cost}€ acheminement dest\n",
            style="dim",
        )

        body.append("✈️  ", style="bold")
        body.append(f"{f.compagnies}\n")

        body.append("⏱️  ", style="bold")
        body.append(f"Durée aller : {f.duree_fmt}", style="cyan")
        body.append(f"  ·  Escale : {f.escale}", style="dim")

        if f.legs_detail:
            body.append("\n\n📋 Détail :\n", style="bold")
            for line in f.legs_detail.split(" | "):
                body.append(f"   • {line}\n", style="dim")

        title = (
            f"#{i} · €{f.prix_total:.0f} total"
            f" · {f.from_airport} → {f.to_airport}"
            f" · {f.nuits} nuits"
        )
        panels.append(Panel(
            body,
            title=title,
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        ))

    warning = Text()
    warning.append(
        "Ces offres sont des CONSTRUCTIONS, à réserver en 2 billets séparés.\n",
        style="bold",
    )
    warning.append(
        "Marge d'escale : 4–28h pour absorber retards et bagages.\n",
        style="dim",
    )
    warning.append(
        "En cas de retard du 1er vol, le 2ème n'est PAS garanti.",
        style="red",
    )
    panels.append(Panel(
        warning,
        title="⚠️  À LIRE",
        title_align="left",
        border_style="red",
        padding=(0, 1),
    ))

    return panels
