"""Self-transfer builder : combine 2 vols séparés (avec cache)"""

import time
import random
from datetime import date, timedelta
from collections import defaultdict
from fast_flights import FlightData, Passengers, get_flights

from config import (
    DEPARTURE_AIRPORTS,
    MIN_PRICE, MAX_PRICE, MAX_DURATION_HOURS,
    THROTTLE_MIN, THROTTLE_MAX,
    SELF_TRANSFER_HUBS, MIN_LAYOVER_HOURS, MAX_LAYOVER_HOURS,
    SELF_TRANSFER_MAX_COMBOS, SELF_TRANSFER_LEGS_PER_SEARCH,
    SELF_TRANSFER_TEST_DAY_BEFORE, USE_CACHE,
)
from models import FlightOffer
from utils import (
    parse_price, parse_duration_to_minutes, format_duration,
    calculate_layover_minutes, get_transport_cost, get_arrival_transport_cost,
    calculate_score, generate_combinations,
)
from cache import get_one_way_cache, save_one_way_cache


def search_one_way(date_dep: date, from_ap: str, to_ap: str, max_results: int) -> list:
    """Cherche des vols one-way avec cache"""
    
    if USE_CACHE:
        cached = get_one_way_cache(date_dep, from_ap, to_ap)
        if cached is not None:
            return cached[:max_results]
    
    try:
        result = get_flights(
            flight_data=[FlightData(
                date=date_dep.isoformat(),
                from_airport=from_ap,
                to_airport=to_ap,
            )],
            trip="one-way",
            seat="economy",
            passengers=Passengers(adults=1),
            fetch_mode="local",
        )
        if not result.flights:
            if USE_CACHE:
                save_one_way_cache(date_dep, from_ap, to_ap, [])
            return []
        
        valid = [
            f for f in result.flights
            if 30 < parse_price(f.price) < MAX_PRICE
        ]
        valid.sort(key=lambda f: parse_price(f.price))
        result_list = valid[:max_results * 2]  # cache un peu plus
        
        if USE_CACHE:
            save_one_way_cache(date_dep, from_ap, to_ap, result_list)
        
        return result_list[:max_results]
    except Exception as e:
        print(f"      ⚠️  {from_ap}→{to_ap} {date_dep}: {type(e).__name__}: {str(e)[:60]}")
        return []


def build_offer_from_legs(
    leg1, leg2, leg3, leg4,
    date_aller_leg1: date, date_aller_leg2: date,
    date_retour_leg3: date, date_retour_leg4: date,
    duration: int, dep: str, arrival: str, hub: str,
) -> FlightOffer | None:
    try:
        layover_aller = calculate_layover_minutes(leg1.arrival, leg2.departure)
        layover_retour = calculate_layover_minutes(leg3.arrival, leg4.departure)
        
        if layover_aller is None or layover_retour is None:
            return None
        
        if not (MIN_LAYOVER_HOURS * 60 <= layover_aller <= MAX_LAYOVER_HOURS * 60):
            return None
        if not (MIN_LAYOVER_HOURS * 60 <= layover_retour <= MAX_LAYOVER_HOURS * 60):
            return None
        
        prix_total_billet = sum(parse_price(leg.price) for leg in [leg1, leg2, leg3, leg4])
        
        if not (MIN_PRICE < prix_total_billet < MAX_PRICE):
            return None
        
        duree_aller_min = (
            parse_duration_to_minutes(leg1.duration) +
            layover_aller +
            parse_duration_to_minutes(leg2.duration)
        )
        
        if duree_aller_min > MAX_DURATION_HOURS * 60:
            return None
        
        airlines = [leg1.name, leg2.name, leg3.name, leg4.name]
        unique_airlines = list(dict.fromkeys(airlines))
        compagnies = " + ".join(unique_airlines)[:60]
        
        nuit_aller = "🛏️ " if layover_aller > 10 * 60 else ""
        nuit_retour = "🛏️ " if layover_retour > 10 * 60 else ""
        
        escale = f"{hub} (self-transfer{' - nuit aller' if nuit_aller else ''})"
        nb_escales = 1
        
        transport_cost = get_transport_cost(dep)
        arrival_cost = get_arrival_transport_cost(arrival)
        prix_total = prix_total_billet + transport_cost + arrival_cost
        
        legs_detail = (
            f"Aller leg1 ({date_aller_leg1.isoformat()}): {dep}→{hub} ({leg1.name}, €{parse_price(leg1.price):.0f}, {leg1.departure}→{leg1.arrival}) "
            f"+ {nuit_aller}{layover_aller//60}h{layover_aller%60:02d} escale "
            f"+ leg2 ({date_aller_leg2.isoformat()}): {hub}→{arrival} ({leg2.name}, €{parse_price(leg2.price):.0f}, {leg2.departure}→{leg2.arrival}) | "
            f"Retour leg3 ({date_retour_leg3.isoformat()}): {arrival}→{hub} ({leg3.name}, €{parse_price(leg3.price):.0f}) "
            f"+ {nuit_retour}{layover_retour//60}h{layover_retour%60:02d} escale "
            f"+ leg4 ({date_retour_leg4.isoformat()}): {hub}→{dep} ({leg4.name}, €{parse_price(leg4.price):.0f})"
        )
        
        return FlightOffer(
            source="self_transfer_built",
            depart_date=date_aller_leg1.isoformat(),
            depart_jour=date_aller_leg1.strftime("%a"),
            retour_date=date_retour_leg3.isoformat(),
            retour_jour=date_retour_leg3.strftime("%a"),
            nuits=duration - 1,
            from_airport=dep,
            to_airport=arrival,
            prix_billet=prix_total_billet,
            transport_cost=transport_cost,
            arrival_transport_cost=arrival_cost,
            prix_total=prix_total,
            prix_str=f"€{prix_total_billet:.0f}",
            compagnies=compagnies,
            escale=escale,
            duree_min=duree_aller_min,
            duree_fmt=format_duration(duree_aller_min),
            nb_escales=nb_escales,
            depart_h=leg1.departure,
            arrivee_h=leg2.arrival,
            j_plus="",
            is_best=False,
            self_transfer=True,
            booking_url="",
            tendance="",
            legs_detail=legs_detail,
            score=calculate_score(
                prix_total_billet, duree_aller_min, nb_escales, 
                dep, arrival, self_transfer=True
            ),
        )
    except Exception:
        return None


def try_combinations(
    legs1_list, legs2_list, legs3_list, legs4_list,
    date_aller_leg1, date_aller_leg2, date_retour_leg3, date_retour_leg4,
    duration, dep, arrival, hub,
) -> list[FlightOffer]:
    valid_offers = []
    for l1 in legs1_list:
        for l2 in legs2_list:
            for l3 in legs3_list:
                for l4 in legs4_list:
                    offer = build_offer_from_legs(
                        l1, l2, l3, l4,
                        date_aller_leg1, date_aller_leg2,
                        date_retour_leg3, date_retour_leg4,
                        duration, dep, arrival, hub,
                    )
                    if offer:
                        valid_offers.append(offer)
    return valid_offers


def run_self_transfer_builder(google_flights_results: list[FlightOffer] = None) -> list[FlightOffer]:
    print("\n" + "═" * 80)
    print(f"{'🔀 SELF-TRANSFER BUILDER':^80}")
    print("═" * 80 + "\n")
    
    if google_flights_results:
        unique_combos = {}
        for offer in sorted(google_flights_results, key=lambda x: x.score):
            key = (offer.depart_date, offer.retour_date, offer.from_airport, offer.to_airport)
            if key not in unique_combos:
                unique_combos[key] = offer
                if len(unique_combos) >= SELF_TRANSFER_MAX_COMBOS:
                    break
        
        target_combos = []
        for (depart_str, retour_str, dep, arrival), offer in unique_combos.items():
            target_combos.append((
                date.fromisoformat(depart_str),
                date.fromisoformat(retour_str),
                offer.nuits + 1,
                dep,
                arrival,
            ))
        
        print(f"📊 {len(target_combos)} meilleures combinaisons sélectionnées du run Google\n")
    else:
        all_combos = generate_combinations()
        target_combos = all_combos[:SELF_TRANSFER_MAX_COMBOS]
        print(f"📊 {len(target_combos)} combinaisons (échantillon)\n")
    
    searches_per_combo_hub = 5 if SELF_TRANSFER_TEST_DAY_BEFORE else 4
    total_searches = len(target_combos) * len(SELF_TRANSFER_HUBS) * searches_per_combo_hub
    print(f"🔍 ~{total_searches} recherches one-way (~{total_searches * 8 / 60:.1f} min sans cache)\n")
    
    results: list[FlightOffer] = []
    search_count = 0
    skipped_hubs = defaultdict(int)
    
    for combo_idx, (date_aller, date_retour, duration, dep, arrival) in enumerate(target_combos, 1):
        print(f"\n📍 Combo {combo_idx}/{len(target_combos)} : "
              f"{dep}→{arrival} {date_aller} → {date_retour} ({duration-1}n)")
        
        for hub in SELF_TRANSFER_HUBS:
            if hub == dep or hub == arrival:
                continue
            
            print(f"   🔄 Test via {hub}...")
            
            search_count += 1
            legs1_jour_j = search_one_way(date_aller, dep, hub, SELF_TRANSFER_LEGS_PER_SEARCH)
            time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            legs1_veille = []
            if SELF_TRANSFER_TEST_DAY_BEFORE:
                search_count += 1
                date_veille = date_aller - timedelta(days=1)
                legs1_veille = search_one_way(date_veille, dep, hub, SELF_TRANSFER_LEGS_PER_SEARCH)
                time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            if not legs1_jour_j and not legs1_veille:
                continue
            
            search_count += 1
            legs2 = search_one_way(date_aller, hub, arrival, SELF_TRANSFER_LEGS_PER_SEARCH)
            time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            if not legs2:
                continue
            
            search_count += 1
            legs3 = search_one_way(date_retour, arrival, hub, SELF_TRANSFER_LEGS_PER_SEARCH)
            time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            if not legs3:
                continue
            
            search_count += 1
            legs4_jour_r = search_one_way(date_retour, hub, dep, SELF_TRANSFER_LEGS_PER_SEARCH)
            time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            legs4_lendemain = []
            if SELF_TRANSFER_TEST_DAY_BEFORE:
                date_lendemain = date_retour + timedelta(days=1)
                legs4_lendemain = search_one_way(date_lendemain, hub, dep, SELF_TRANSFER_LEGS_PER_SEARCH)
                time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            
            if not legs4_jour_r and not legs4_lendemain:
                continue
            
            all_valid = []
            
            if legs1_jour_j and legs4_jour_r:
                all_valid.extend(try_combinations(
                    legs1_jour_j, legs2, legs3, legs4_jour_r,
                    date_aller, date_aller, date_retour, date_retour,
                    duration, dep, arrival, hub,
                ))
            
            if legs1_veille and legs4_jour_r:
                all_valid.extend(try_combinations(
                    legs1_veille, legs2, legs3, legs4_jour_r,
                    date_aller - timedelta(days=1), date_aller, date_retour, date_retour,
                    duration, dep, arrival, hub,
                ))
            
            if legs1_jour_j and legs4_lendemain:
                all_valid.extend(try_combinations(
                    legs1_jour_j, legs2, legs3, legs4_lendemain,
                    date_aller, date_aller, date_retour, date_retour + timedelta(days=1),
                    duration, dep, arrival, hub,
                ))
            
            if legs1_veille and legs4_lendemain:
                all_valid.extend(try_combinations(
                    legs1_veille, legs2, legs3, legs4_lendemain,
                    date_aller - timedelta(days=1), date_aller, date_retour, date_retour + timedelta(days=1),
                    duration, dep, arrival, hub,
                ))
            
            if all_valid:
                best = min(all_valid, key=lambda o: o.score)
                results.append(best)
                hint = " (avec escale-nuit)" if "🛏️" in best.legs_detail else ""
                print(f"      ✅ via {hub}: €{best.prix_billet:.0f} "
                      f"({best.duree_fmt}, {best.compagnies[:40]}){hint}")
            else:
                total_attempted = (
                    len(legs1_jour_j) * len(legs2) * len(legs3) * len(legs4_jour_r) +
                    len(legs1_veille) * len(legs2) * len(legs3) * len(legs4_jour_r) +
                    len(legs1_jour_j) * len(legs2) * len(legs3) * len(legs4_lendemain) +
                    len(legs1_veille) * len(legs2) * len(legs3) * len(legs4_lendemain)
                )
                print(f"      ⚠️  via {hub}: 0 combo valide sur {total_attempted} testées")
                skipped_hubs[hub] += 1
    
    print(f"\n✅ Self-transfer builder terminé : {len(results)} offres construites")
    print(f"📊 {search_count} recherches one-way effectuées")
    if skipped_hubs:
        print(f"📊 Hubs sans match : {dict(skipped_hubs)}")
    
    return results