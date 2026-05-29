Pivot stratégique du scraping. Au lieu de scraper Google Flights page par page (lent, fragile, beaucoup de timeouts pour CUZ/AQP), on passe sur le scrap de la mtrice calendaire accessible via le bouton "Calendrier". Cette matrice calendaire retourne en 1 seule requête une matrice 2D de prix sur 49 jours (7 jours x 7 jours) pour une route donnée.

Architecture cible :

Phase 1 (rapide) : 1 call par route valide (12 routes pour Pérou) → matrices de prix
Phase 2 (ciblée) : top 20-30 combinaisons par route, scraping détaillé avec fast-flights existant si besoin de compagnies/durée

Le préfiltrage hot zones et le cache restent utiles pour la phase 2. Garder la structure modulaire actuelle (config.py, models.py, etc.).
À implémenter :

Nouveau scraper scrapers/calendar_picker_scraper.py.
Nouvelle phase dans main.py qui lance le calendar picker avant fast-flights
Filtre côté Python sur la matrice retournée selon weekday/duration
Adapter aggregator pour fusionner les résultats des 2 phases

Possibilité aussi avec "Graphique des prix" d'établir des tendances mais plus complexe à scraper et moins structuré que la matrice calendaire. À explorer éventuellement pour des insights complémentaires.
