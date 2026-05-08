1. URL ORIGINALE (sans type=1, ce que v2 envoie nativement) :
   https://www.google.com/travel/flights?tfs=GhoSCjIwMjYtMDctMDNqBRIDQU1TcgUSA0FRUBoaEgoyMDI2LTA3LTI0agUSA0FRUHIFEgNBTVNCAQFIAZgBAQ==&hl=en&tfu=EgQIABABIgA
   -> Les vols sont bien trouvés

2. URL PATCHÉE (avec type=1 IATA injecté) :
   https://www.google.com/travel/flights?tfs=Gh4SCjIwMjYtMDctMDNqBwgBEgNBTVNyBwgBEgNBUVAaHhIKMjAyNi0wNy0yNGoHCAESA0FRUHIHCAESA0FNU0IBAUgBmAEB&hl=en&tfu=EgQIABABIgA
   -> Les vols sont bien trouvés

3. URL PATCHÉE + path /flights/search :
   https://www.google.com/travel/flights/search?tfs=Gh4SCjIwMjYtMDctMDNqBwgBEgNBTVNyBwgBEgNBUVAaHhIKMjAyNi0wNy0yNGoHCAESA0FRUHIHCAESA0FNU0IBAUgBmAEB&hl=en&tfu=EgQIABABIgA
   -> Les vols sont bien trouvés

🔍 1926 combinaisons | 4 workers
⏱️ Estimation initiale : ~64.2 min (raffinée en live)
📦 Cache : 1172 round-trip + 0 one-way (20661.5 KB)

🛫 [█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 68/1926 (4%) | écoulé 2m10s | ETA 56m13s
📦 45 cache 🌐 7 net ⚠️ 0 vides ❌ 16 err

[ 54/1926] ❌ ORY→AQP 2026-07-03: TimeoutError: Locator.wait_for: Timeout 25000ms exceeded.
[ 62/1926] 🌐 ✅ CDG→CUZ 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €2208 (24 hr 30 min, 2esc)
[ 64/1926] 📦 ✅ ORY→LIM 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €1517 (16 hr, 1esc)
[ 65/1926] 📦 ✅ ORY→CUZ 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €1819 (19 hr 40 min, 2esc)
[ 66/1926] 📦 ✅ ORY→AQP 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €2041 (23 hr 25 min, 2esc)
[ 67/1926] 📦 ✅ BRU→LIM 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €1390 (16 hr 5 min, 1esc)
[ 68/1926] 📦 ✅ BRU→CUZ 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €2104 (20 hr 10 min, 2esc)
[ 63/1926] 🌐 ✅ CDG→AQP 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €1860 (24 hr 45 min, 2esc)
[ 70/1926] 📦 ✅ AMS→LIM 2026-07-03(Fri) → 2026-07-27(Mon) (24j) | min: €1345 (15 hr 45 min, 1esc)
[ 57/1926] ❌ BRU→AQP 2026-07-03: TimeoutError: Locator.wait_for: Timeout 25000ms exceeded.
