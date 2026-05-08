# Empêcher le PC de dormir + lancer le run complet

systemd-inhibit --what=idle:sleep:handle-lid-switch \
 --why="Flight scraper running" \
 uv run python main.py

# Variantes

uv run python main.py --google-only # Google Flights uniquement
uv run python main.py --self-transfer-only # Self-transfer uniquement
uv run python main.py --from-csv # Re-rank depuis CSVs (instantané)
uv run python main.py --force-prefilter # Refresh le préfiltrage
uv run python main.py --clear-cache # Vide le cache
uv run python main.py --cache-stats # Stats du cache
uv run python main.py --help # Aide
