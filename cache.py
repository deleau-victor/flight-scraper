"""Cache des résultats de recherche fast-flights"""

import json
import os
from datetime import date, datetime, timedelta
from config import CACHE_TTL_HOURS


CACHE_DIR = "data/cache"
ROUND_TRIP_CACHE = f"{CACHE_DIR}/round_trip"
ONE_WAY_CACHE = f"{CACHE_DIR}/one_way"
CALENDAR_CACHE = f"{CACHE_DIR}/calendar"

_dirs_ensured = False


def _ensure_cache_dirs():
    """Idempotent + memoized. makedirs(exist_ok=True) coûte 2 stat() syscalls à
    chaque appel — sur des milliers de cache hits ça représente ~100-200ms inutiles."""
    global _dirs_ensured
    if _dirs_ensured:
        return
    os.makedirs(ROUND_TRIP_CACHE, exist_ok=True)
    os.makedirs(ONE_WAY_CACHE, exist_ok=True)
    os.makedirs(CALENDAR_CACHE, exist_ok=True)
    _dirs_ensured = True


def _round_trip_key(date_aller: date, date_retour: date, dep: str, arrival: str) -> str:
    return f"{dep}_{arrival}_{date_aller.isoformat()}_{date_retour.isoformat()}"


def _one_way_key(date_dep: date, from_ap: str, to_ap: str) -> str:
    return f"{from_ap}_{to_ap}_{date_dep.isoformat()}"


def _is_cache_valid(cached_at_str: str) -> bool:
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
        age = datetime.now() - cached_at
        return age < timedelta(hours=CACHE_TTL_HOURS)
    except (ValueError, TypeError):
        return False


def _flight_obj_to_dict(f) -> dict:
    return {
        "name": getattr(f, "name", ""),
        "price": getattr(f, "price", ""),
        "departure": getattr(f, "departure", ""),
        "arrival": getattr(f, "arrival", ""),
        "duration": getattr(f, "duration", ""),
        "stops": getattr(f, "stops", 0),
        "arrival_time_ahead": getattr(f, "arrival_time_ahead", ""),
        "delay": getattr(f, "delay", ""),
        "is_best": getattr(f, "is_best", False),
    }


class CachedFlightObj:
    """Recrée un objet Flight-like depuis un dict cache"""
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.price = data.get("price", "")
        self.departure = data.get("departure", "")
        self.arrival = data.get("arrival", "")
        self.duration = data.get("duration", "")
        self.stops = data.get("stops", 0)
        self.arrival_time_ahead = data.get("arrival_time_ahead", "")
        self.delay = data.get("delay", "")
        self.is_best = data.get("is_best", False)


class CachedResultObj:
    """Recrée un objet Result-like depuis un dict cache"""
    def __init__(self, data: dict):
        self.current_price = data.get("current_price", "")
        self.flights = [CachedFlightObj(f) for f in data.get("flights", [])]


# ============== ROUND TRIP CACHE ==============

def get_round_trip_cache(date_aller: date, date_retour: date, dep: str, arrival: str):
    _ensure_cache_dirs()
    key = _round_trip_key(date_aller, date_retour, dep, arrival)
    filepath = f"{ROUND_TRIP_CACHE}/{key}.json"
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not _is_cache_valid(data.get("cached_at", "")):
            return None
        
        return CachedResultObj(data)
    except (json.JSONDecodeError, IOError):
        return None


def save_round_trip_cache(date_aller: date, date_retour: date, dep: str, arrival: str, result):
    _ensure_cache_dirs()
    key = _round_trip_key(date_aller, date_retour, dep, arrival)
    filepath = f"{ROUND_TRIP_CACHE}/{key}.json"
    
    data = {
        "cached_at": datetime.now().isoformat(),
        "current_price": getattr(result, "current_price", "") or "",
        "flights": [_flight_obj_to_dict(f) for f in result.flights] if result and result.flights else [],
    }
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"      ⚠️  Erreur cache write {key}: {e}")


# ============== ONE WAY CACHE ==============

def get_one_way_cache(date_dep: date, from_ap: str, to_ap: str):
    _ensure_cache_dirs()
    key = _one_way_key(date_dep, from_ap, to_ap)
    filepath = f"{ONE_WAY_CACHE}/{key}.json"
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not _is_cache_valid(data.get("cached_at", "")):
            return None
        
        return [CachedFlightObj(fd) for fd in data.get("flights", [])]
    except (json.JSONDecodeError, IOError):
        return None


def save_one_way_cache(date_dep: date, from_ap: str, to_ap: str, flights: list):
    _ensure_cache_dirs()
    key = _one_way_key(date_dep, from_ap, to_ap)
    filepath = f"{ONE_WAY_CACHE}/{key}.json"
    
    data = {
        "cached_at": datetime.now().isoformat(),
        "flights": [_flight_obj_to_dict(f) for f in flights] if flights else [],
    }
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"      ⚠️  Erreur cache write {key}: {e}")


# ============== UTILS ==============

def cache_stats():
    _ensure_cache_dirs()
    rt_files = [f for f in os.listdir(ROUND_TRIP_CACHE) if f.endswith(".json")] if os.path.exists(ROUND_TRIP_CACHE) else []
    ow_files = [f for f in os.listdir(ONE_WAY_CACHE) if f.endswith(".json")] if os.path.exists(ONE_WAY_CACHE) else []
    cal_files = [f for f in os.listdir(CALENDAR_CACHE) if f.endswith(".json")] if os.path.exists(CALENDAR_CACHE) else []

    total_size = sum(
        os.path.getsize(os.path.join(ROUND_TRIP_CACHE, f)) for f in rt_files
    ) + sum(
        os.path.getsize(os.path.join(ONE_WAY_CACHE, f)) for f in ow_files
    ) + sum(
        os.path.getsize(os.path.join(CALENDAR_CACHE, f)) for f in cal_files
    )

    print(
        f"📦 Cache : {len(rt_files)} round-trip + {len(ow_files)} one-way + "
        f"{len(cal_files)} calendar ({total_size / 1024:.1f} KB)"
    )


def clear_cache():
    import shutil
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    _ensure_cache_dirs()
    print("🗑️  Cache vidé")


# ============== CALENDAR CACHE ==============

def _calendar_key(dep: str, arrival: str, anchor: date) -> str:
    return f"{dep}_{arrival}_{anchor.isoformat()}"


def get_calendar_cache(dep: str, arrival: str, anchor: date):
    """Retourne list[CalendarCell] ou None si miss/expiré.

    Import local de CalendarCell pour éviter cycle d'import (cache importé
    par calendar_picker_scraper).
    """
    _ensure_cache_dirs()
    filepath = f"{CALENDAR_CACHE}/{_calendar_key(dep, arrival, anchor)}.json"
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not _is_cache_valid(data.get("cached_at", "")):
            return None
        from scrapers.calendar_picker_scraper import CalendarCell
        return [
            CalendarCell(
                date_aller=date.fromisoformat(c["date_aller"]),
                date_retour=date.fromisoformat(c["date_retour"]),
                dep=c["dep"],
                arrival=c["arrival"],
                prix=float(c["prix"]),
                deeplink_token=c.get("deeplink_token", ""),
            )
            for c in data.get("cells", [])
        ]
    except (json.JSONDecodeError, IOError, KeyError):
        return None


def save_calendar_cache(dep: str, arrival: str, anchor: date, cells: list):
    _ensure_cache_dirs()
    filepath = f"{CALENDAR_CACHE}/{_calendar_key(dep, arrival, anchor)}.json"
    data = {
        "cached_at": datetime.now().isoformat(),
        "cells": [
            {
                "date_aller": c.date_aller.isoformat(),
                "date_retour": c.date_retour.isoformat(),
                "dep": c.dep,
                "arrival": c.arrival,
                "prix": c.prix,
                "deeplink_token": c.deeplink_token,
            }
            for c in cells
        ],
    }
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"      ⚠️  Erreur calendar cache write {_calendar_key(dep, arrival, anchor)}: {e}")