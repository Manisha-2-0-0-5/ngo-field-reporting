"""
maps_client.py — OpenStreetMap + Nominatim (FREE, no API key, no card)
Replaces Google Maps Platform entirely.

Nominatim = OpenStreetMap's free geocoding API
Overpass API = OpenStreetMap's free POI search API
Both are 100% free, no registration, no key needed.
"""

import requests
from math import radians, sin, cos, sqrt, atan2

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL  = "https://overpass-api.de/api/interpreter"
HEADERS       = {"User-Agent": "NGO-Adapter-Hackathon/1.0"}

CRISIS_TO_OSM = {
    "health_kit":       ("amenity", "clinic"),
    "sanitation":       ("amenity", "toilets"),
    "food_access":      ("amenity", "food_bank"),
    "water_stagnation": ("amenity", "water_point"),
    "power_outage":     ("office",  "government"),
    "livelihood":       ("office",  "ngo"),
    "elderly_care":     ("amenity", "social_facility"),
    "child_welfare":    ("amenity", "social_facility"),
    "shelter":          ("amenity", "shelter"),
    "infrastructure":   ("office",  "government"),
}

RADIUS_METERS = 5000


def _geocode(location: str) -> tuple:
    """Returns (lat, lon) for a location string. Falls back to Chennai center."""
    try:
        r = requests.get(NOMINATIM_URL, params={
            "q": f"{location}, Chennai, Tamil Nadu, India",
            "format": "json", "limit": 1,
        }, headers=HEADERS, timeout=5)
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[maps] Geocode error: {e}")
    return 13.0827, 80.2707  # Chennai center fallback


def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def _overpass_search(lat, lon, osm_key, osm_value, radius=RADIUS_METERS) -> list:
    """Search OpenStreetMap for POIs near a location."""
    query = f"""
    [out:json][timeout:10];
    (
      node["{osm_key}"="{osm_value}"](around:{radius},{lat},{lon});
      way["{osm_key}"="{osm_value}"](around:{radius},{lat},{lon});
    );
    out center 5;
    """
    try:
        r = requests.post(OVERPASS_URL, data=query, timeout=12)
        elements = r.json().get("elements", [])
        results = []
        for el in elements[:5]:
            name = el.get("tags", {}).get("name", "Unnamed facility")
            elat = el.get("lat") or el.get("center", {}).get("lat")
            elon = el.get("lon") or el.get("center", {}).get("lon")
            if not elat:
                continue
            dist = _haversine(lat, lon, elat, elon)
            results.append({
                "name":     name,
                "address":  el.get("tags", {}).get("addr:street", ""),
                "lat":      elat,
                "lon":      elon,
                "distance_km": round(dist, 1),
                "maps_link": f"https://www.openstreetmap.org/?mlat={elat}&mlon={elon}#map=17/{elat}/{elon}",
            })
        results.sort(key=lambda x: x["distance_km"])
        return results[:3]
    except Exception as e:
        print(f"[maps] Overpass error: {e}")
        return []


def find_nearest_resources(location: str, crisis_tags: list) -> list:
    """
    Main function: geocode location, search OSM for relevant facilities.
    Returns list of nearby resources per crisis tag.
    """
    if not location:
        return []

    lat, lon = _geocode(location)
    results = []
    seen = set()

    for tag in crisis_tags:
        osm_key, osm_value = CRISIS_TO_OSM.get(tag, ("office", "ngo"))
        places = _overpass_search(lat, lon, osm_key, osm_value)

        for place in places:
            key = place["name"] + str(place["lat"])
            if key in seen:
                continue
            seen.add(key)
            place["crisis_tag"] = tag
            place["status"] = "matched" if place["distance_km"] < 3 else "partial"
            results.append(place)

    results.sort(key=lambda x: x["distance_km"])
    return results
