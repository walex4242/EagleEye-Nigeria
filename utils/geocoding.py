"""
utils/geocoding.py
──────────────────
Reverse geocoding for Nigeria — converts lat/lon to human-readable
location names (state, LGA, nearest town) for operational use.

Uses:
  1. Local Nigeria state/LGA boundary lookup (instant, offline)
  2. OpenStreetMap Nominatim API for nearest town (cached)
  3. Military-grade coordinate formatting (DMS, MGRS-style)
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
import requests
from math import radians, cos, sin, asin, sqrt, degrees, floor
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger("eagleeye.geocoding")

# ── Rate limiting for Nominatim (max 1 req/sec) ──────────────
_last_nominatim_call: float = 0.0
NOMINATIM_MIN_INTERVAL = 1.1  # seconds

# ── Cache directory ───────────────────────────────────────────
GEOCODE_CACHE_DIR = Path("./data/geocode_cache")
GEOCODE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory cache ──────────────────────────────────────────
_geocode_cache: Dict[str, Dict] = {}


# ── Nigeria Administrative Boundaries ─────────────────────────
# All 36 states + FCT with approximate bounding boxes
# Format: "state_name": (min_lat, max_lat, min_lon, max_lon, capital)

NIGERIA_STATES: Dict[str, Dict] = {
    "Abia": {"bounds": (4.75, 6.12, 7.00, 8.00), "capital": "Umuahia", "geo_zone": "South East"},
    "Adamawa": {"bounds": (7.48, 10.96, 11.40, 13.70), "capital": "Yola", "geo_zone": "North East"},
    "Akwa Ibom": {"bounds": (4.32, 5.53, 7.35, 8.30), "capital": "Uyo", "geo_zone": "South South"},
    "Anambra": {"bounds": (5.68, 6.77, 6.60, 7.20), "capital": "Awka", "geo_zone": "South East"},
    "Bauchi": {"bounds": (9.30, 12.22, 8.50, 11.00), "capital": "Bauchi", "geo_zone": "North East"},
    "Bayelsa": {"bounds": (4.20, 5.35, 5.20, 6.80), "capital": "Yenagoa", "geo_zone": "South South"},
    "Benue": {"bounds": (6.40, 8.10, 6.70, 10.00), "capital": "Makurdi", "geo_zone": "North Central"},
    "Borno": {"bounds": (10.00, 13.70, 11.50, 14.70), "capital": "Maiduguri", "geo_zone": "North East"},
    "Cross River": {"bounds": (4.28, 6.88, 7.70, 9.45), "capital": "Calabar", "geo_zone": "South South"},
    "Delta": {"bounds": (5.05, 6.50, 5.00, 6.80), "capital": "Asaba", "geo_zone": "South South"},
    "Ebonyi": {"bounds": (5.70, 6.70, 7.60, 8.30), "capital": "Abakaliki", "geo_zone": "South East"},
    "Edo": {"bounds": (5.70, 7.60, 5.00, 6.70), "capital": "Benin City", "geo_zone": "South South"},
    "Ekiti": {"bounds": (7.25, 8.10, 4.70, 5.80), "capital": "Ado Ekiti", "geo_zone": "South West"},
    "Enugu": {"bounds": (5.90, 7.10, 6.95, 7.85), "capital": "Enugu", "geo_zone": "South East"},
    "FCT": {"bounds": (8.40, 9.45, 6.70, 7.60), "capital": "Abuja", "geo_zone": "North Central"},
    "Gombe": {"bounds": (9.30, 11.20, 10.70, 12.00), "capital": "Gombe", "geo_zone": "North East"},
    "Imo": {"bounds": (5.10, 6.00, 6.60, 7.50), "capital": "Owerri", "geo_zone": "South East"},
    "Jigawa": {"bounds": (11.00, 13.00, 8.00, 10.50), "capital": "Dutse", "geo_zone": "North West"},
    "Kaduna": {"bounds": (9.00, 11.30, 6.00, 8.80), "capital": "Kaduna", "geo_zone": "North West"},
    "Kano": {"bounds": (10.30, 12.70, 7.60, 9.40), "capital": "Kano", "geo_zone": "North West"},
    "Katsina": {"bounds": (11.00, 13.40, 6.50, 8.60), "capital": "Katsina", "geo_zone": "North West"},
    "Kebbi": {"bounds": (10.50, 13.30, 3.40, 5.80), "capital": "Birnin Kebbi", "geo_zone": "North West"},
    "Kogi": {"bounds": (6.70, 8.70, 5.40, 7.80), "capital": "Lokoja", "geo_zone": "North Central"},
    "Kwara": {"bounds": (7.70, 9.80, 2.70, 6.00), "capital": "Ilorin", "geo_zone": "North Central"},
    "Lagos": {"bounds": (6.38, 6.70, 2.70, 4.35), "capital": "Ikeja", "geo_zone": "South West"},
    "Nasarawa": {"bounds": (7.70, 9.30, 7.00, 9.40), "capital": "Lafia", "geo_zone": "North Central"},
    "Niger": {"bounds": (8.30, 11.50, 3.50, 7.50), "capital": "Minna", "geo_zone": "North Central"},
    "Ogun": {"bounds": (6.30, 7.80, 2.70, 4.60), "capital": "Abeokuta", "geo_zone": "South West"},
    "Ondo": {"bounds": (5.75, 7.80, 4.30, 6.00), "capital": "Akure", "geo_zone": "South West"},
    "Osun": {"bounds": (7.00, 8.10, 4.00, 5.10), "capital": "Osogbo", "geo_zone": "South West"},
    "Oyo": {"bounds": (7.10, 9.10, 2.70, 4.60), "capital": "Ibadan", "geo_zone": "South West"},
    "Plateau": {"bounds": (8.50, 10.60, 8.20, 10.10), "capital": "Jos", "geo_zone": "North Central"},
    "Rivers": {"bounds": (4.25, 5.70, 6.50, 7.60), "capital": "Port Harcourt", "geo_zone": "South South"},
    "Sokoto": {"bounds": (11.50, 13.80, 4.00, 6.50), "capital": "Sokoto", "geo_zone": "North West"},
    "Taraba": {"bounds": (6.50, 9.60, 9.30, 11.90), "capital": "Jalingo", "geo_zone": "North East"},
    "Yobe": {"bounds": (10.50, 13.30, 9.80, 12.30), "capital": "Damaturu", "geo_zone": "North East"},
    "Zamfara": {"bounds": (11.00, 13.10, 5.40, 7.50), "capital": "Gusau", "geo_zone": "North West"},
}

# Major Nigerian towns/cities with coordinates for distance calculation
NIGERIA_TOWNS: List[Dict] = [
    # Northeast (Boko Haram corridor)
    {"name": "Maiduguri", "lat": 11.8469, "lon": 13.1573, "state": "Borno", "type": "state_capital"},
    {"name": "Bama", "lat": 11.5204, "lon": 13.6856, "state": "Borno", "type": "town"},
    {"name": "Gwoza", "lat": 11.0833, "lon": 13.6953, "state": "Borno", "type": "town"},
    {"name": "Chibok", "lat": 10.9000, "lon": 12.8333, "state": "Borno", "type": "town"},
    {"name": "Konduga", "lat": 11.6500, "lon": 13.2667, "state": "Borno", "type": "town"},
    {"name": "Dikwa", "lat": 12.0333, "lon": 13.9167, "state": "Borno", "type": "town"},
    {"name": "Monguno", "lat": 12.6700, "lon": 13.6100, "state": "Borno", "type": "town"},
    {"name": "Damboa", "lat": 11.1553, "lon": 12.7564, "state": "Borno", "type": "town"},
    {"name": "Kukawa", "lat": 12.9236, "lon": 13.5656, "state": "Borno", "type": "town"},
    {"name": "Damaturu", "lat": 11.7470, "lon": 11.9609, "state": "Yobe", "type": "state_capital"},
    {"name": "Potiskum", "lat": 11.7128, "lon": 11.0780, "state": "Yobe", "type": "town"},
    {"name": "Gashua", "lat": 12.8711, "lon": 11.0469, "state": "Yobe", "type": "town"},
    {"name": "Yola", "lat": 9.2035, "lon": 12.4954, "state": "Adamawa", "type": "state_capital"},
    {"name": "Mubi", "lat": 10.2677, "lon": 13.2640, "state": "Adamawa", "type": "town"},
    {"name": "Michika", "lat": 10.6214, "lon": 13.3981, "state": "Adamawa", "type": "town"},
    {"name": "Gombe", "lat": 10.2897, "lon": 11.1711, "state": "Gombe", "type": "state_capital"},
    {"name": "Bauchi", "lat": 10.3103, "lon": 9.8439, "state": "Bauchi", "type": "state_capital"},

    # Northwest (Banditry corridor)
    {"name": "Gusau", "lat": 12.1704, "lon": 6.6612, "state": "Zamfara", "type": "state_capital"},
    {"name": "Anka", "lat": 12.1094, "lon": 5.9275, "state": "Zamfara", "type": "town"},
    {"name": "Shinkafi", "lat": 13.0667, "lon": 6.5000, "state": "Zamfara", "type": "town"},
    {"name": "Tsafe", "lat": 12.1667, "lon": 6.9167, "state": "Zamfara", "type": "town"},
    {"name": "Maru", "lat": 12.3333, "lon": 6.4000, "state": "Zamfara", "type": "town"},
    {"name": "Katsina", "lat": 13.0059, "lon": 7.5986, "state": "Katsina", "type": "state_capital"},
    {"name": "Jibia", "lat": 13.3500, "lon": 7.2333, "state": "Katsina", "type": "town"},
    {"name": "Batsari", "lat": 12.8833, "lon": 7.2667, "state": "Katsina", "type": "town"},
    {"name": "Dan Sadau", "lat": 12.4500, "lon": 6.2667, "state": "Zamfara", "type": "town"},
    {"name": "Kaduna", "lat": 10.5222, "lon": 7.4383, "state": "Kaduna", "type": "state_capital"},
    {"name": "Zaria", "lat": 11.0855, "lon": 7.7106, "state": "Kaduna", "type": "city"},
    {"name": "Kafanchan", "lat": 9.5833, "lon": 8.3000, "state": "Kaduna", "type": "town"},
    {"name": "Birnin Gwari", "lat": 10.7833, "lon": 6.5167, "state": "Kaduna", "type": "town"},
    {"name": "Sokoto", "lat": 13.0607, "lon": 5.2401, "state": "Sokoto", "type": "state_capital"},
    {"name": "Kano", "lat": 12.0022, "lon": 8.5920, "state": "Kano", "type": "state_capital"},

    # North Central (Herder-farmer belt)
    {"name": "Makurdi", "lat": 7.7337, "lon": 8.5217, "state": "Benue", "type": "state_capital"},
    {"name": "Jos", "lat": 9.8965, "lon": 8.8583, "state": "Plateau", "type": "state_capital"},
    {"name": "Lafia", "lat": 8.4966, "lon": 8.5157, "state": "Nasarawa", "type": "state_capital"},
    {"name": "Lokoja", "lat": 7.7969, "lon": 6.7433, "state": "Kogi", "type": "state_capital"},
    {"name": "Minna", "lat": 9.6139, "lon": 6.5569, "state": "Niger", "type": "state_capital"},
    {"name": "Abuja", "lat": 9.0579, "lon": 7.4951, "state": "FCT", "type": "federal_capital"},
    {"name": "Ilorin", "lat": 8.5000, "lon": 4.5500, "state": "Kwara", "type": "state_capital"},
    {"name": "Gboko", "lat": 7.3167, "lon": 9.0000, "state": "Benue", "type": "town"},
    {"name": "Otukpo", "lat": 7.1905, "lon": 8.1300, "state": "Benue", "type": "town"},

    # Niger Delta
    {"name": "Port Harcourt", "lat": 4.8156, "lon": 7.0498, "state": "Rivers", "type": "state_capital"},
    {"name": "Warri", "lat": 5.5167, "lon": 5.7500, "state": "Delta", "type": "city"},
    {"name": "Yenagoa", "lat": 4.9267, "lon": 6.2676, "state": "Bayelsa", "type": "state_capital"},
    {"name": "Asaba", "lat": 6.1944, "lon": 6.7333, "state": "Delta", "type": "state_capital"},
    {"name": "Benin City", "lat": 6.3350, "lon": 5.6037, "state": "Edo", "type": "state_capital"},
    {"name": "Calabar", "lat": 4.9517, "lon": 8.3220, "state": "Cross River", "type": "state_capital"},
    {"name": "Uyo", "lat": 5.0510, "lon": 7.9335, "state": "Akwa Ibom", "type": "state_capital"},
    {"name": "Bonny", "lat": 4.4333, "lon": 7.1667, "state": "Rivers", "type": "town"},

    # Southwest
    {"name": "Lagos", "lat": 6.5244, "lon": 3.3792, "state": "Lagos", "type": "megacity"},
    {"name": "Ibadan", "lat": 7.3878, "lon": 3.8963, "state": "Oyo", "type": "state_capital"},
    {"name": "Abeokuta", "lat": 7.1557, "lon": 3.3453, "state": "Ogun", "type": "state_capital"},
    {"name": "Akure", "lat": 7.2526, "lon": 5.1931, "state": "Ondo", "type": "state_capital"},
    {"name": "Osogbo", "lat": 7.7827, "lon": 4.5418, "state": "Osun", "type": "state_capital"},
    {"name": "Ado Ekiti", "lat": 7.6211, "lon": 5.2214, "state": "Ekiti", "type": "state_capital"},

    # Southeast
    {"name": "Enugu", "lat": 6.4584, "lon": 7.5464, "state": "Enugu", "type": "state_capital"},
    {"name": "Owerri", "lat": 5.4851, "lon": 7.0352, "state": "Imo", "type": "state_capital"},
    {"name": "Awka", "lat": 6.2106, "lon": 7.0742, "state": "Anambra", "type": "state_capital"},
    {"name": "Umuahia", "lat": 5.5264, "lon": 7.4906, "state": "Abia", "type": "state_capital"},
    {"name": "Abakaliki", "lat": 6.3249, "lon": 8.1137, "state": "Ebonyi", "type": "state_capital"},
]

# ── Local LGA Lookup (no Nominatim needed) ────────────────────

# LGA centroids for conflict-affected states
# Format: { "State": [ ("LGA Name", lat, lon), ... ] }
NIGERIA_LGAS: Dict[str, List[Tuple[str, float, float]]] = {
    "Zamfara": [
        ("Anka", 12.11, 5.93),
        ("Bakura", 12.72, 5.68),
        ("Birnin Magaji/Kiyaw", 12.78, 6.25),
        ("Bukkuyum", 11.94, 5.60),
        ("Bungudu", 12.25, 6.52),
        ("Gummi", 12.14, 5.17),
        ("Gusau", 12.17, 6.66),
        ("Kaura Namoda", 12.59, 6.59),
        ("Maradun", 12.38, 6.33),
        ("Maru", 12.33, 6.42),
        ("Shinkafi", 13.07, 6.51),
        ("Talata Mafara", 12.57, 6.07),
        ("Tsafe", 12.14, 7.08),
        ("Zurmi", 13.15, 6.77),
    ],
    "Sokoto": [
        ("Binji", 13.22, 5.24),
        ("Bodinga", 12.87, 5.17),
        ("Dange Shuni", 13.16, 5.34),
        ("Gada", 13.74, 5.79),
        ("Goronyo", 13.44, 5.68),
        ("Gudu", 13.39, 4.69),
        ("Gwadabawa", 13.36, 5.24),
        ("Illela", 13.73, 5.30),
        ("Isa", 13.22, 5.48),
        ("Kebbe", 12.37, 4.27),
        ("Kware", 13.16, 5.27),
        ("Rabah", 12.95, 5.53),
        ("Sabon Birni", 13.56, 6.14),
        ("Shagari", 12.73, 5.10),
        ("Silame", 12.87, 4.80),
        ("Sokoto North", 13.08, 5.23),
        ("Sokoto South", 13.04, 5.22),
        ("Tambuwal", 12.40, 4.65),
        ("Tangaza", 13.57, 5.42),
        ("Tureta", 12.76, 5.38),
        ("Wamako", 13.03, 5.14),
        ("Wurno", 13.29, 5.42),
        ("Yabo", 12.71, 4.93),
    ],
    "Katsina": [
        ("Bakori", 11.87, 7.42),
        ("Batagarawa", 12.88, 7.60),
        ("Batsari", 12.87, 7.33),
        ("Baure", 12.76, 8.73),
        ("Bindawa", 12.63, 7.95),
        ("Charanchi", 12.63, 7.68),
        ("Dan Musa", 11.97, 7.63),
        ("Dandume", 11.55, 7.13),
        ("Danja", 11.68, 7.55),
        ("Daura", 13.03, 8.32),
        ("Dutsi", 13.03, 8.63),
        ("Dutsin Ma", 12.45, 7.50),
        ("Faskari", 11.82, 6.87),
        ("Funtua", 11.52, 7.32),
        ("Ingawa", 12.84, 8.10),
        ("Jibia", 13.34, 7.23),
        ("Kafur", 11.65, 7.67),
        ("Kaita", 13.18, 7.85),
        ("Kankara", 11.93, 7.40),
        ("Kankia", 12.34, 7.93),
        ("Katsina", 13.00, 7.60),
        ("Kurfi", 12.24, 7.82),
        ("Kusada", 12.37, 7.37),
        ("Mai'Adua", 13.19, 8.21),
        ("Malumfashi", 11.78, 7.62),
        ("Mani", 13.00, 8.54),
        ("Mashi", 12.98, 7.95),
        ("Matazu", 12.19, 7.78),
        ("Musawa", 11.95, 7.65),
        ("Rimi", 12.42, 7.63),
        ("Sabuwa", 11.57, 7.07),
        ("Safana", 12.35, 7.38),
        ("Sandamu", 13.29, 7.59),
        ("Zango", 12.95, 8.53),
    ],
    "Kaduna": [
        ("Birnin Gwari", 11.22, 6.52),
        ("Chikun", 10.32, 7.33),
        ("Giwa", 11.25, 7.33),
        ("Igabi", 10.82, 7.42),
        ("Ikara", 11.17, 7.87),
        ("Jaba", 9.72, 8.03),
        ("Jema'a", 9.33, 8.25),
        ("Kachia", 9.87, 7.95),
        ("Kaduna North", 10.55, 7.43),
        ("Kaduna South", 10.48, 7.42),
        ("Kagarko", 9.58, 7.68),
        ("Kajuru", 10.32, 7.68),
        ("Kaura", 9.67, 8.42),
        ("Kauru", 10.62, 8.08),
        ("Kubau", 11.18, 7.72),
        ("Kudan", 11.17, 7.58),
        ("Lere", 10.37, 8.58),
        ("Makarfi", 11.38, 7.67),
        ("Sabon Gari", 11.17, 7.72),
        ("Sanga", 9.53, 8.52),
        ("Soba", 10.97, 8.05),
        ("Zangon Kataf", 9.78, 8.07),
        ("Zaria", 11.08, 7.72),
    ],
    "Borno": [
        ("Abadam", 13.35, 13.38),
        ("Askira/Uba", 10.53, 13.00),
        ("Bama", 11.52, 13.68),
        ("Bayo", 10.58, 12.45),
        ("Biu", 10.61, 12.19),
        ("Chibok", 10.87, 12.85),
        ("Damboa", 11.15, 12.77),
        ("Dikwa", 12.03, 13.92),
        ("Gubio", 12.58, 12.72),
        ("Guzamala", 12.52, 13.15),
        ("Gwoza", 11.08, 13.70),
        ("Hawul", 10.50, 12.22),
        ("Jere", 11.88, 13.10),
        ("Kaga", 12.13, 12.38),
        ("Kala/Balge", 12.15, 14.37),
        ("Konduga", 11.65, 13.27),
        ("Kukawa", 12.92, 13.60),
        ("Kwaya Kusar", 10.45, 12.32),
        ("Mafa", 11.82, 13.53),
        ("Magumeri", 12.12, 12.82),
        ("Maiduguri", 11.85, 13.15),
        ("Marte", 12.37, 13.83),
        ("Mobbar", 12.83, 13.18),
        ("Monguno", 12.67, 13.60),
        ("Ngala", 12.33, 14.17),
        ("Nganzai", 12.45, 12.92),
        ("Shani", 10.22, 12.07),
    ],
    "Niger": [
        ("Agaie", 8.95, 6.27),
        ("Agwara", 10.87, 4.62),
        ("Bida", 9.08, 6.02),
        ("Borgu", 10.23, 4.22),
        ("Bosso", 9.77, 6.48),
        ("Chanchaga", 9.62, 6.55),
        ("Edati", 9.07, 5.82),
        ("Gbako", 9.10, 6.15),
        ("Gurara", 9.32, 7.10),
        ("Katcha", 8.82, 6.42),
        ("Kontagora", 10.40, 5.47),
        ("Lapai", 9.05, 6.57),
        ("Lavun", 9.08, 5.55),
        ("Magama", 10.63, 5.12),
        ("Mariga", 10.87, 5.52),
        ("Mashegu", 10.12, 5.58),
        ("Mokwa", 9.30, 5.05),
        ("Munya", 9.55, 6.88),
        ("Paikoro", 9.43, 6.80),
        ("Rafi", 10.23, 6.37),
        ("Rijau", 10.93, 5.22),
        ("Shiroro", 9.97, 6.85),
        ("Suleja", 9.18, 7.17),
        ("Tafa", 9.15, 7.23),
        ("Wushishi", 9.73, 6.15),
    ],
    "Benue": [
        ("Ado", 7.25, 7.60),
        ("Agatu", 7.58, 7.77),
        ("Apa", 7.37, 7.57),
        ("Buruku", 7.42, 9.20),
        ("Gboko", 7.32, 9.00),
        ("Guma", 7.73, 8.62),
        ("Gwer East", 7.33, 8.57),
        ("Gwer West", 7.38, 8.35),
        ("Katsina-Ala", 7.17, 9.28),
        ("Konshisha", 6.93, 9.12),
        ("Kwande", 6.87, 9.43),
        ("Logo", 7.62, 8.87),
        ("Makurdi", 7.73, 8.53),
        ("Obi", 7.12, 8.25),
        ("Ogbadibo", 7.02, 7.80),
        ("Ohimini", 7.13, 7.88),
        ("Oju", 6.85, 8.42),
        ("Okpokwu", 7.03, 7.97),
        ("Otukpo", 7.20, 8.13),
        ("Tarka", 7.55, 8.95),
        ("Ukum", 7.08, 9.42),
        ("Ushongo", 7.15, 9.05),
        ("Vandeikya", 7.08, 9.08),
    ],
    "Plateau": [
        ("Barkin Ladi", 9.53, 8.90),
        ("Bassa", 9.93, 8.73),
        ("Bokkos", 9.30, 8.98),
        ("Jos East", 9.78, 9.00),
        ("Jos North", 9.93, 8.90),
        ("Jos South", 9.82, 8.85),
        ("Kanam", 9.58, 9.73),
        ("Kanke", 9.42, 9.42),
        ("Langtang North", 9.15, 9.78),
        ("Langtang South", 8.90, 9.62),
        ("Mangu", 9.52, 9.10),
        ("Mikang", 8.92, 9.72),
        ("Pankshin", 9.33, 9.43),
        ("Qua'an Pan", 9.07, 9.30),
        ("Riyom", 9.62, 8.75),
        ("Shendam", 8.88, 9.52),
        ("Wase", 9.10, 9.93),
    ],
    "Adamawa": [
        ("Demsa", 9.45, 12.10),
        ("Fufore", 9.22, 12.58),
        ("Ganye", 8.43, 12.05),
        ("Girei", 9.35, 12.52),
        ("Gombi", 10.17, 12.73),
        ("Guyuk", 9.88, 12.07),
        ("Hong", 10.23, 12.93),
        ("Jada", 8.77, 12.15),
        ("Lamurde", 9.62, 11.77),
        ("Madagali", 10.87, 13.70),
        ("Maiha", 10.32, 13.17),
        ("Mayo Belwa", 9.05, 12.05),
        ("Michika", 10.62, 13.40),
        ("Mubi North", 10.27, 13.27),
        ("Mubi South", 10.18, 13.23),
        ("Numan", 9.47, 12.03),
        ("Shelleng", 9.90, 12.00),
        ("Song", 9.82, 12.63),
        ("Toungo", 8.12, 12.05),
        ("Yola North", 9.23, 12.47),
        ("Yola South", 9.18, 12.43),
    ],
    "Yobe": [
        ("Bade", 12.78, 10.98),
        ("Bursari", 12.48, 11.52),
        ("Damaturu", 11.75, 11.97),
        ("Fika", 11.30, 11.32),
        ("Fune", 11.75, 11.35),
        ("Geidam", 12.90, 11.92),
        ("Gujba", 11.50, 12.25),
        ("Gulani", 11.48, 12.15),
        ("Jakusko", 12.30, 11.05),
        ("Karasuwa", 12.75, 10.75),
        ("Machina", 13.12, 10.05),
        ("Nangere", 11.88, 11.05),
        ("Nguru", 12.88, 10.45),
        ("Potiskum", 11.72, 11.07),
        ("Tarmuwa", 12.13, 11.70),
        ("Yunusari", 13.07, 11.32),
        ("Yusufari", 13.07, 11.18),
    ],
    "Nasarawa": [
        ("Akwanga", 8.90, 8.38),
        ("Awe", 8.10, 8.73),
        ("Doma", 8.38, 8.35),
        ("Karu", 8.98, 7.85),
        ("Keana", 7.87, 8.75),
        ("Keffi", 8.85, 7.87),
        ("Kokona", 8.72, 8.10),
        ("Lafia", 8.50, 8.52),
        ("Nasarawa", 8.53, 7.72),
        ("Nasarawa Egon", 8.72, 8.73),
        ("Obi", 7.78, 8.68),
        ("Toto", 8.35, 7.05),
        ("Wamba", 9.05, 8.68),
    ],
    "Taraba": [
        ("Ardo Kola", 8.48, 11.05),
        ("Bali", 7.85, 10.97),
        ("Donga", 7.72, 10.05),
        ("Gashaka", 7.35, 11.52),
        ("Gassol", 8.53, 10.45),
        ("Ibi", 8.18, 9.75),
        ("Jalingo", 8.90, 11.37),
        ("Karim Lamido", 9.32, 11.23),
        ("Kurmi", 6.95, 10.73),
        ("Lau", 9.18, 11.38),
        ("Sardauna", 6.75, 11.23),
        ("Takum", 7.27, 9.98),
        ("Ussa", 6.87, 10.07),
        ("Wukari", 7.87, 9.78),
        ("Yorro", 8.62, 11.27),
        ("Zing", 8.98, 11.73),
    ],
    "Gombe": [
        ("Akko", 10.28, 10.95),
        ("Balanga", 9.88, 11.68),
        ("Billiri", 9.87, 11.23),
        ("Dukku", 10.82, 10.78),
        ("Funakaye", 10.58, 11.38),
        ("Gombe", 10.29, 11.17),
        ("Kaltungo", 9.82, 11.32),
        ("Kwami", 10.45, 11.12),
        ("Nafada", 10.58, 11.33),
        ("Shongom", 9.73, 11.38),
        ("Yamaltu/Deba", 10.12, 11.32),
    ],
    "Bauchi": [
        ("Alkaleri", 10.27, 10.33),
        ("Bauchi", 10.31, 9.84),
        ("Bogoro", 9.73, 9.63),
        ("Dambam", 11.68, 10.83),
        ("Darazo", 10.98, 10.42),
        ("Dass", 9.97, 9.52),
        ("Gamawa", 11.88, 10.53),
        ("Ganjuwa", 10.42, 9.85),
        ("Giade", 11.38, 10.18),
        ("Itas/Gadau", 11.72, 10.10),
        ("Jama'are", 11.67, 9.93),
        ("Katagum", 12.28, 10.27),
        ("Kirfi", 10.40, 10.47),
        ("Misau", 11.32, 10.45),
        ("Ningi", 10.93, 9.55),
        ("Shira", 11.55, 10.22),
        ("Tafawa Balewa", 9.75, 9.77),
        ("Toro", 10.03, 9.10),
        ("Warji", 10.77, 9.57),
        ("Zaki", 11.82, 10.62),
    ],
    "Kebbi": [
        ("Aleiro", 12.28, 4.27),
        ("Arewa Dandi", 11.82, 4.18),
        ("Argungu", 12.75, 4.52),
        ("Augie", 12.75, 4.13),
        ("Bagudo", 11.43, 4.22),
        ("Birnin Kebbi", 12.45, 4.20),
        ("Bunza", 11.93, 4.72),
        ("Dandi", 11.55, 4.35),
        ("Fakai", 11.42, 3.87),
        ("Gwandu", 12.50, 4.63),
        ("Jega", 12.22, 4.38),
        ("Kalgo", 12.32, 4.20),
        ("Koko/Besse", 11.42, 4.52),
        ("Maiyama", 12.07, 4.37),
        ("Ngaski", 11.78, 4.08),
        ("Sakaba", 10.82, 4.52),
        ("Shanga", 11.20, 3.78),
        ("Suru", 12.48, 3.95),
        ("Wasagu/Danko", 10.73, 4.42),
        ("Yauri", 10.83, 4.77),
        ("Zuru", 11.43, 5.23),
    ],
    "Jigawa": [
        ("Auyo", 12.33, 9.95),
        ("Babura", 12.77, 9.02),
        ("Biriniwa", 12.75, 10.23),
        ("Birnin Kudu", 11.45, 9.48),
        ("Buji", 11.55, 9.62),
        ("Dutse", 11.77, 9.33),
        ("Gagarawa", 12.42, 9.52),
        ("Garki", 12.20, 9.80),
        ("Gumel", 12.63, 9.38),
        ("Guri", 12.78, 10.38),
        ("Gwaram", 11.28, 9.83),
        ("Gwiwa", 12.35, 9.32),
        ("Hadejia", 12.45, 10.05),
        ("Jahun", 12.17, 9.33),
        ("Kafin Hausa", 12.23, 10.32),
        ("Kaugama", 12.38, 10.38),
        ("Kazaure", 12.65, 8.42),
        ("Kiri Kasama", 12.23, 9.87),
        ("Kiyawa", 11.77, 9.62),
        ("Maigatari", 12.82, 9.45),
        ("Malam Madori", 12.58, 9.95),
        ("Miga", 12.15, 9.58),
        ("Ringim", 12.15, 9.17),
        ("Roni", 12.65, 9.72),
        ("Sule Tankarkar", 12.70, 9.18),
        ("Taura", 12.33, 9.68),
        ("Yankwashi", 12.17, 9.17),
    ],
    "Kano": [
        ("Ajingi", 11.97, 9.38),
        ("Albasu", 11.62, 9.20),
        ("Bagwai", 12.15, 8.13),
        ("Bebeji", 11.63, 8.45),
        ("Bichi", 12.23, 8.23),
        ("Bunkure", 11.70, 8.55),
        ("Dala", 12.00, 8.52),
        ("Dambatta", 12.42, 8.52),
        ("Dawakin Kudu", 11.83, 8.67),
        ("Dawakin Tofa", 12.08, 8.22),
        ("Doguwa", 11.05, 8.80),
        ("Fagge", 12.00, 8.55),
        ("Gabasawa", 12.18, 8.85),
        ("Garko", 11.65, 8.78),
        ("Garun Mallam", 11.57, 8.40),
        ("Gaya", 11.87, 9.00),
        ("Gezawa", 12.07, 8.87),
        ("Gwale", 11.97, 8.50),
        ("Gwarzo", 12.17, 7.93),
        ("Kabo", 12.37, 8.15),
        ("Kano Municipal", 12.00, 8.52),
        ("Karaye", 11.78, 8.07),
        ("Kibiya", 11.48, 8.67),
        ("Kiru", 11.53, 8.12),
        ("Kumbotso", 11.87, 8.52),
        ("Kunchi", 12.37, 8.52),
        ("Kura", 11.77, 8.43),
        ("Madobi", 11.68, 8.28),
        ("Makoda", 12.33, 8.25),
        ("Minjibir", 12.20, 8.67),
        ("Nassarawa", 12.02, 8.55),
        ("Rano", 11.55, 8.58),
        ("Rimin Gado", 12.13, 8.27),
        ("Rogo", 11.55, 8.15),
        ("Shanono", 12.08, 7.97),
        ("Sumaila", 11.53, 9.03),
        ("Takai", 11.77, 9.13),
        ("Tarauni", 11.95, 8.55),
        ("Tofa", 11.93, 8.28),
        ("Tsanyawa", 12.33, 8.55),
        ("Tudun Wada", 11.42, 8.95),
        ("Ungogo", 12.07, 8.50),
        ("Warawa", 11.93, 8.72),
        ("Wudil", 11.82, 8.85),
    ],
    "FCT": [
        ("Abaji", 8.47, 6.94),
        ("Abuja Municipal", 9.06, 7.49),
        ("Bwari", 9.28, 7.38),
        ("Gwagwalada", 8.94, 7.08),
        ("Kuje", 8.88, 7.23),
        ("Kwali", 8.73, 7.02),
    ],
}

# ── Data Classes ──────────────────────────────────────────────

@dataclass
class LocationInfo:
    """Structured location information for a coordinate."""
    latitude: float
    longitude: float
    state: str
    lga: str
    nearest_town: str
    nearest_town_distance_km: float
    nearest_town_direction: str
    geo_zone: str
    state_capital: str
    coords_dms: str
    google_maps_url: str
    operational_description: str
    nominatim_place: Optional[str] = None
    road: Optional[str] = None
    additional_context: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Haversine ─────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate bearing in degrees from point 1 to point 2."""
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlon_r = radians(lon2 - lon1)
    x = sin(dlon_r) * cos(lat2_r)
    y = cos(lat1_r) * sin(lat2_r) - sin(lat1_r) * cos(lat2_r) * cos(dlon_r)
    bearing = degrees(asin(min(1, max(-1, x / max(sqrt(x**2 + y**2), 1e-10)))))
    # Normalize to 0-360
    import math
    bearing_deg = math.degrees(math.atan2(x, y))
    return (bearing_deg + 360) % 360


def _bearing_to_compass(bearing: float) -> str:
    """Convert bearing in degrees to compass direction."""
    directions = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = round(bearing / 22.5) % 16
    return directions[idx]


def _decimal_to_dms(lat: float, lon: float) -> str:
    """Convert decimal degrees to DMS format (military standard)."""
    def _to_dms(deg: float, is_lat: bool) -> str:
        direction = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
        deg = abs(deg)
        d = int(deg)
        m = int((deg - d) * 60)
        s = ((deg - d) * 60 - m) * 60
        return f"{d}°{m:02d}'{s:05.2f}\"{direction}"

    return f"{_to_dms(lat, True)} {_to_dms(lon, False)}"


# ── State Lookup ──────────────────────────────────────────────

def _find_state(lat: float, lon: float) -> Tuple[str, str, str]:
    """
    Find the Nigerian state for a given coordinate.
    Returns (state_name, state_capital, geo_zone).
    Uses bounding box containment with overlap resolution.
    """
    candidates: List[Tuple[str, Dict, float]] = []

    for state_name, info in NIGERIA_STATES.items():
        min_lat, max_lat, min_lon, max_lon = info["bounds"]
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            # Calculate distance to bbox center for tie-breaking
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2
            dist = _haversine(lat, lon, center_lat, center_lon)
            candidates.append((state_name, info, dist))

    if candidates:
        # Pick the closest center (handles overlapping bboxes)
        candidates.sort(key=lambda x: x[2])
        best = candidates[0]
        return best[0], best[1]["capital"], best[1]["geo_zone"]

    # Fallback: find nearest state center
    best_dist = float("inf")
    best_state = "Unknown"
    best_capital = "Unknown"
    best_zone = "Unknown"

    for state_name, info in NIGERIA_STATES.items():
        min_lat, max_lat, min_lon, max_lon = info["bounds"]
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        dist = _haversine(lat, lon, center_lat, center_lon)
        if dist < best_dist:
            best_dist = dist
            best_state = state_name
            best_capital = info["capital"]
            best_zone = info["geo_zone"]

    return best_state, best_capital, best_zone


# ── Nearest Town Lookup ───────────────────────────────────────

def _find_nearest_town(
    lat: float, lon: float, max_results: int = 3,
) -> List[Dict]:
    """Find the nearest known towns to a coordinate."""
    distances: List[Dict] = []

    for town in NIGERIA_TOWNS:
        dist = _haversine(lat, lon, town["lat"], town["lon"])
        bearing = _bearing(town["lat"], town["lon"], lat, lon)
        compass = _bearing_to_compass(bearing)

        distances.append({
            "name": town["name"],
            "state": town["state"],
            "type": town["type"],
            "distance_km": round(dist, 1),
            "direction": compass,
            "bearing": round(bearing, 1),
        })

    distances.sort(key=lambda x: x["distance_km"])
    return distances[:max_results]


# ── Nominatim Reverse Geocoding ───────────────────────────────

def _nominatim_reverse(
    lat: float, lon: float,
) -> Optional[Dict]:
    """
    Reverse geocode using OpenStreetMap Nominatim.
    Rate-limited to 1 request per second.
    Results are cached to disk.
    """
    global _last_nominatim_call

    # Round to ~100m precision for cache efficiency
    cache_lat = round(lat, 3)
    cache_lon = round(lon, 3)
    cache_key = f"{cache_lat}_{cache_lon}"

    # Check in-memory cache
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    # Check disk cache
    cache_file = GEOCODE_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                _geocode_cache[cache_key] = data
                return data
        except Exception:
            pass

    # Rate limiting
    now = time.time()
    elapsed = now - _last_nominatim_call
    if elapsed < NOMINATIM_MIN_INTERVAL:
        time.sleep(NOMINATIM_MIN_INTERVAL - elapsed)

    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "zoom": 14,
            "addressdetails": 1,
        }
        headers = {
            "User-Agent": "EagleEye-Nigeria/1.0 (security monitoring)",
        }

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        _last_nominatim_call = time.time()

        if resp.status_code == 200:
            data = resp.json()
            # Cache to memory and disk
            _geocode_cache[cache_key] = data
            try:
                with open(cache_file, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass
            return data

    except Exception as e:
        logger.warning("Nominatim reverse geocoding failed: %s", e)

    return None


def _find_lga_local(
    lat: float, lon: float, state: str,
) -> str:
    """
    Find the nearest LGA for a coordinate within a given state.
    Uses local centroid data — no API calls.
    Returns LGA name or 'Unknown LGA' if state not in database.
    """
    lgas = NIGERIA_LGAS.get(state, [])
    if not lgas:
        # State not in our LGA database — use nearest town as fallback
        return ""

    best_lga = ""
    best_dist = float("inf")

    for lga_name, l_lat, l_lon in lgas:
        dist = _haversine(lat, lon, l_lat, l_lon)
        if dist < best_dist:
            best_dist = dist
            best_lga = lga_name

    # Sanity check: if the nearest LGA centroid is >80km away,
    # the state match might be wrong
    if best_dist > 80:
        return f"Near {best_lga}"

    return best_lga

# ── Main Geocoding Function ──────────────────────────────────

def reverse_geocode(
    lat: float,
    lon: float,
    use_nominatim: bool = True,
) -> LocationInfo:
    """
    Full reverse geocoding for a Nigerian coordinate.

    Returns structured location info including:
    - State, LGA, geopolitical zone
    - Nearest known town with distance and direction
    - DMS coordinates
    - Google Maps link
    - Operational description for military briefings
    - Optional Nominatim place name
    """
    # ── Local lookups (instant) ──
    state, state_capital, geo_zone = _find_state(lat, lon)
    nearest_towns = _find_nearest_town(lat, lon)
    nearest = nearest_towns[0] if nearest_towns else {
        "name": "Unknown",
        "distance_km": 0,
        "direction": "N",
    }

    coords_dms = _decimal_to_dms(lat, lon)

    # Google Maps URL with zoom level 15 (street level)
    google_maps_url = (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={lat},{lon}"
    )

       # ── Nominatim lookup (optional, cached) ──
    nominatim_place = None
    road = None
    lga = ""

    if use_nominatim:
        nom = _nominatim_reverse(lat, lon)
        if nom:
            address = nom.get("address", {})
            nominatim_place = nom.get("display_name", "")

            # Extract LGA (various Nominatim field names)
            lga = (
                address.get("county", "")
                or address.get("state_district", "")
                or address.get("city_district", "")
                or address.get("municipality", "")
                or ""
            )

            road = address.get("road", "") or address.get("hamlet", "")

            # Try to get more specific place name
            for field in ("village", "town", "city", "hamlet", "suburb", "neighbourhood"):
                place = address.get(field)
                if place:
                    nominatim_place = place
                    break

    # ── Local LGA fallback (instant, no API) ──
    if not lga:
        lga = _find_lga_local(lat, lon, state)

    if not lga:
        lga = f"Near {nearest['name']}"

    # ── Build operational description ──
    dist = nearest["distance_km"]
    direction = nearest["direction"]

    if dist < 2:
        proximity = f"within {nearest['name']}"
    elif dist < 10:
        proximity = f"{dist:.1f}km {direction} of {nearest['name']}"
    elif dist < 50:
        proximity = f"{dist:.0f}km {direction} of {nearest['name']}"
    else:
        proximity = f"approx {dist:.0f}km {direction} of {nearest['name']}"

    specific_place = ""
    if nominatim_place and nominatim_place != nearest["name"]:
        specific_place = f" ({nominatim_place})"

    operational_description = (
        f"{proximity}{specific_place}, "
        f"{lga}, {state} State, {geo_zone}"
    )

    # ── Additional context for military ──
    additional_context = None
    if len(nearest_towns) >= 2:
        t2 = nearest_towns[1]
        additional_context = (
            f"Also {t2['distance_km']:.0f}km {t2['direction']} of "
            f"{t2['name']}. State capital {state_capital} is "
            f"{_haversine(lat, lon, *_get_town_coords(state_capital)):.0f}km away."
        )

    return LocationInfo(
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        state=state,
        lga=lga,
        nearest_town=nearest["name"],
        nearest_town_distance_km=nearest["distance_km"],
        nearest_town_direction=direction,
        geo_zone=geo_zone,
        state_capital=state_capital,
        coords_dms=coords_dms,
        google_maps_url=google_maps_url,
        operational_description=operational_description,
        nominatim_place=nominatim_place,
        road=road,
        additional_context=additional_context,
    )


def _get_town_coords(town_name: str) -> Tuple[float, float]:
    """Get coordinates for a town name."""
    for town in NIGERIA_TOWNS:
        if town["name"] == town_name:
            return town["lat"], town["lon"]
    return 9.0, 7.5  # Default to Abuja


# ── Batch Geocoding ───────────────────────────────────────────

def enrich_features_with_location(
    geojson: Dict,
    use_nominatim: bool = True,
    max_nominatim_calls: int = 50,
) -> Dict:
    """
    Enrich a GeoJSON FeatureCollection by adding location info
    to every feature's properties.

    For efficiency:
    - Local state/town lookup for ALL features (instant)
    - Nominatim calls are batched and capped at max_nominatim_calls
    - Nearby features share the same Nominatim result (grid-based)
    """
    features = geojson.get("features", [])
    if not features:
        return geojson

    print(f"[GEO] Enriching {len(features)} features with location data...")

    nominatim_calls = 0
    # Grid-based Nominatim dedup (round to ~1km cells)
    nominatim_grid: Dict[str, Optional[Dict]] = {}

    enriched_features: List[Dict] = []

    for i, feature in enumerate(features):
        coords = feature.get("geometry", {}).get("coordinates", [0, 0])
        lon = float(coords[0]) if len(coords) > 0 else 0.0
        lat = float(coords[1]) if len(coords) > 1 else 0.0

        if lat == 0 and lon == 0:
            enriched_features.append(feature)
            continue

        # Decide whether to use Nominatim for this feature
        grid_key = f"{round(lat, 2)}_{round(lon, 2)}"
        do_nominatim = (
            use_nominatim
            and nominatim_calls < max_nominatim_calls
            and grid_key not in nominatim_grid
        )

        if do_nominatim:
            nominatim_calls += 1

        # Check if we already have Nominatim data for this grid cell
        skip_nominatim = grid_key in nominatim_grid

        location = reverse_geocode(
            lat, lon,
            use_nominatim=do_nominatim or skip_nominatim,
        )

        if do_nominatim:
            nominatim_grid[grid_key] = {
                "place": location.nominatim_place,
                "road": location.road,
            }

        # Merge location into feature properties
        props = feature.get("properties", {})
        props["location"] = {
            "state": location.state,
            "lga": location.lga,
            "nearest_town": location.nearest_town,
            "distance_km": location.nearest_town_distance_km,
            "direction": location.nearest_town_direction,
            "geo_zone": location.geo_zone,
            "coords_dms": location.coords_dms,
            "operational_description": location.operational_description,
        }
        props["google_maps_url"] = location.google_maps_url
        props["state"] = location.state
        props["lga"] = location.lga
        props["nearest_town"] = location.nearest_town

        if location.nominatim_place:
            props["location"]["place_name"] = location.nominatim_place
        if location.road:
            props["location"]["road"] = location.road
        if location.additional_context:
            props["location"]["additional_context"] = location.additional_context

        enriched_feature = {**feature, "properties": props}
        enriched_features.append(enriched_feature)

    print(
        f"[GEO] ✓ Enriched {len(enriched_features)} features "
        f"({nominatim_calls} Nominatim calls)"
    )

    return {
        **geojson,
        "features": enriched_features,
    }


# ── Quick Location Label ─────────────────────────────────────

def quick_label(lat: float, lon: float) -> str:
    """
    Fast location label without Nominatim.
    Returns e.g. "12.5km NE of Maiduguri, Borno State"
    """
    state, _, _ = _find_state(lat, lon)
    nearest = _find_nearest_town(lat, lon, max_results=1)

    if nearest:
        t = nearest[0]
        if t["distance_km"] < 2:
            return f"{t['name']}, {state} State"
        return (
            f"{t['distance_km']:.1f}km {t['direction']} of "
            f"{t['name']}, {state} State"
        )

    return f"{lat:.4f}°N, {lon:.4f}°E, {state} State"