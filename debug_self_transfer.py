"""Debug : comprend pourquoi le self-transfer ne match rien"""

from fast_flights import FlightData, Passengers, get_flights
from utils import parse_time_str, calculate_layover_minutes, parse_price, parse_duration_to_minutes

# Test 1 : Que retourne fast-flights pour un one-way ?
print("=" * 80)
print("TEST 1 : Format brut d'un vol one-way ORY → MAD")
print("=" * 80)

result = get_flights(
    flight_data=[FlightData(
        date="2026-06-05",
        from_airport="ORY",
        to_airport="MAD",
    )],
    trip="one-way",
    seat="economy",
    passengers=Passengers(adults=1),
    fetch_mode="local",
)

print(f"Nombre de vols : {len(result.flights)}")
if result.flights:
    f = result.flights[0]
    print(f"\n--- Premier vol ---")
    for attr in ['name', 'price', 'departure', 'arrival', 'duration', 'stops', 'arrival_time_ahead']:
        val = getattr(f, attr, 'MISSING')
        print(f"  {attr}: {val!r}")

# Test 2 : Le parsing des heures fonctionne-t-il ?
print("\n" + "=" * 80)
print("TEST 2 : Parsing des heures")
print("=" * 80)

if result.flights:
    f = result.flights[0]
    dep_parsed = parse_time_str(f.departure)
    arr_parsed = parse_time_str(f.arrival)
    print(f"Départ '{f.departure}' → {dep_parsed}")
    print(f"Arrivée '{f.arrival}' → {arr_parsed}")
    if dep_parsed is None or arr_parsed is None:
        print("❌ PARSING ÉCHOUE !")

# Test 3 : Simuler une combinaison ORY→MAD + MAD→LIM
print("\n" + "=" * 80)
print("TEST 3 : Combinaison réelle ORY→MAD + MAD→LIM le 5 juin")
print("=" * 80)

result1 = get_flights(
    flight_data=[FlightData(date="2026-06-05", from_airport="ORY", to_airport="MAD")],
    trip="one-way", seat="economy", passengers=Passengers(adults=1),
    fetch_mode="local",
)

result2 = get_flights(
    flight_data=[FlightData(date="2026-06-05", from_airport="MAD", to_airport="LIM")],
    trip="one-way", seat="economy", passengers=Passengers(adults=1),
    fetch_mode="local",
)

print(f"Vols ORY→MAD : {len(result1.flights)}")
print(f"Vols MAD→LIM : {len(result2.flights)}")

if result1.flights and result2.flights:
    leg1 = result1.flights[0]
    leg2 = result2.flights[0]
    
    print(f"\nLeg 1 ORY→MAD : {leg1.name} | dep {leg1.departure!r} | arr {leg1.arrival!r}")
    print(f"Leg 2 MAD→LIM : {leg2.name} | dep {leg2.departure!r} | arr {leg2.arrival!r}")
    
    layover = calculate_layover_minutes(leg1.arrival, leg2.departure)
    print(f"\nEscale calculée : {layover} minutes")
    if layover is None:
        print("❌ Calcul d'escale ÉCHOUE !")
    elif layover < 0:
        print(f"❌ Escale négative ({layover}) — mauvais ordre temporel ?")
    else:
        print(f"✅ Escale = {layover // 60}h{layover % 60:02d}")
        from config import MIN_LAYOVER_HOURS, MAX_LAYOVER_HOURS
        print(f"   Limites : {MIN_LAYOVER_HOURS*60} ≤ {layover} ≤ {MAX_LAYOVER_HOURS*60}")
        if layover < MIN_LAYOVER_HOURS * 60:
            print(f"   → Trop court (min {MIN_LAYOVER_HOURS}h)")
        elif layover > MAX_LAYOVER_HOURS * 60:
            print(f"   → Trop long (max {MAX_LAYOVER_HOURS}h)")
        else:
            print(f"   → ✅ Dans la fenêtre OK")