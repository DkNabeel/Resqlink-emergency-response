import math
import re


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Return great-circle distance between two latitude/longitude points."""
    values = (lat1, lon1, lat2, lon2)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Coordinates must be finite numbers.")
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Longitude must be between -180 and 180.")

    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def point_in_polygon(latitude, longitude, polygon):
    """Ray-casting point-in-polygon test; polygon points are [latitude, longitude]."""
    if len(polygon) < 3:
        return False

    x, y = longitude, latitude
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        point_i = polygon[i]
        point_j = polygon[j]
        yi, xi = float(point_i[0]), float(point_i[1])
        yj, xj = float(point_j[0]), float(point_j[1])

        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i

    return inside


def _contains_location_name(text, name):
    if not text or not name:
        return False
    pattern = r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def match_alert_location(alert, latitude, longitude, city=None, district=None, state=None):
    """
    Match a CAP alert against a point.

    Returns True for a confirmed geometry/locality match, False for a geometry
    exclusion, or None when the feed does not provide enough location detail.
    """
    polygons = alert.get("polygons") or []
    circles = alert.get("circles") or []

    if polygons:
        if any(point_in_polygon(latitude, longitude, polygon) for polygon in polygons):
            return {"matched": True, "method": "cap_polygon", "distance_km": 0.0}
        return {"matched": False, "method": "outside_cap_polygon", "distance_km": None}

    if circles:
        distances = []
        for circle in circles:
            distance = haversine_km(
                latitude, longitude, float(circle["latitude"]), float(circle["longitude"])
            )
            distances.append((distance, float(circle["radius_km"])))
        for distance, radius in distances:
            if distance <= radius:
                return {
                    "matched": True,
                    "method": "cap_circle",
                    "distance_km": round(distance, 2),
                }
        nearest = min(distances, key=lambda item: item[0])
        return {
            "matched": False,
            "method": "outside_cap_circle",
            "distance_km": round(nearest[0], 2),
        }

    area_text = " ".join(
        str(value or "")
        for value in (
            alert.get("area_description"),
            alert.get("description"),
            alert.get("title"),
        )
    )

    for name, method in ((city, "city_text"), (district, "district_text")):
        if _contains_location_name(area_text, name):
            return {"matched": True, "method": method, "distance_km": None}

    if state and _contains_location_name(area_text, state):
        return {"matched": None, "method": "state_only_unconfirmed", "distance_km": None}

    return {"matched": None, "method": "area_not_geocoded", "distance_km": None}
