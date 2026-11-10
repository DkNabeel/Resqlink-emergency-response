import hashlib
import html
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree

from app.database.alert_repository import (
    get_feed_state,
    update_feed_state,
    upsert_alerts,
)


DEFAULT_SACHET_FEED = (
    "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
)


def _local_name(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    if ":" in tag:
        return tag.rsplit(":", 1)[1].lower()
    return tag.lower()


def _clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_datetime(value):
    value = _clean_text(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _descendant_values(element):
    values = {}
    for node in element.iter():
        name = _local_name(node.tag)
        text = _clean_text(" ".join(node.itertext()))
        if text:
            values.setdefault(name, []).append(text)
        href = node.attrib.get("href")
        if href and name == "link":
            values.setdefault("link_href", []).append(href)
    return values


def _first(values, *names):
    for name in names:
        entries = values.get(name.lower(), [])
        if entries:
            return entries[0]
    return None


def _parse_polygon(value):
    points = []
    for token in _clean_text(value).split():
        parts = token.split(",")
        if len(parts) != 2:
            continue
        try:
            latitude, longitude = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            points.append([latitude, longitude])
    return points if len(points) >= 3 else None


def _parse_circle(value):
    parts = _clean_text(value).split()
    if len(parts) != 2 or "," not in parts[0]:
        return None
    try:
        latitude, longitude = (float(item) for item in parts[0].split(",", 1))
        radius_km = float(parts[1])
    except ValueError:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and radius_km > 0):
        return None
    return {"latitude": latitude, "longitude": longitude, "radius_km": radius_km}


def parse_sachet_feed(xml_content):
    """
    Parse SACHET's RSS/CAP feed.

    CAP geometry is retained when the feed includes polygon/circle elements.
    If the RSS item only contains a title/description, no location is invented.
    """
    root = ElementTree.fromstring(xml_content)
    items = [
        node for node in root.iter()
        if _local_name(node.tag) in {"item", "entry"}
    ]

    alerts = []
    for item in items:
        values = _descendant_values(item)
        title = _first(values, "title")
        description = _first(values, "description", "summary", "content", "instruction")
        link = _first(values, "link_href", "link")
        guid = _first(values, "identifier", "guid", "id")
        published = _first(values, "sent", "pubdate", "published", "updated", "date")

        if not title and not description:
            continue

        polygons = []
        for raw_polygon in values.get("polygon", []):
            polygon = _parse_polygon(raw_polygon)
            if polygon:
                polygons.append(polygon)

        circles = []
        for raw_circle in values.get("circle", []):
            circle = _parse_circle(raw_circle)
            if circle:
                circles.append(circle)

        geocodes = []
        for node in item.iter():
            if _local_name(node.tag) != "geocode":
                continue
            pair = _descendant_values(node)
            value_name = _first(pair, "valuename")
            value = _first(pair, "value")
            if value_name and value:
                geocodes.append({"name": value_name, "value": value})

        stable_key = guid or "|".join((link or "", title or "", published or ""))
        alert_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()

        area_description = _first(values, "areadesc")
        source_url = link
        if source_url and urlparse(source_url).scheme not in {"http", "https"}:
            source_url = None

        alerts.append({
            "alert_id": alert_id,
            "source": "NDMA SACHET",
            "title": _clean_text(title)[:500] or "Official public-safety alert",
            "description": _clean_text(description)[:3000],
            "event": _first(values, "event"),
            "category": _first(values, "category"),
            "severity": _first(values, "severity"),
            "urgency": _first(values, "urgency"),
            "certainty": _first(values, "certainty"),
            "status": _first(values, "status") or "Unknown",
            "message_type": _first(values, "msgtype", "message_type"),
            "effective_at": _parse_datetime(_first(values, "effective")),
            "expires_at": _parse_datetime(_first(values, "expires")),
            "published_at": _parse_datetime(published),
            "area_description": area_description,
            "polygons": polygons,
            "circles": circles,
            "geocodes": geocodes,
            "references": values.get("references", []),
            "source_url": source_url,
            "raw_content": _clean_text(description)[:4000],
        })

    return alerts


async def sync_sachet_feed(feed_url=None):
    """Fetch the official RSS feed using ETag/Last-Modified conditional requests."""
    feed_url = feed_url or os.getenv("SACHET_FEED_URL", DEFAULT_SACHET_FEED)
    if not feed_url.startswith("https://"):
        raise ValueError("SACHET_FEED_URL must use HTTPS.")

    previous = get_feed_state(feed_url) or {}
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
        "User-Agent": "ResQLink-Student-Project/1.0",
    }
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    if previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]

    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(feed_url, headers=headers)

    if response.status_code == 304:
        update_feed_state(feed_url, http_status=304, success=True)
        return {
            "status": "not_modified",
            "new_alerts": 0,
            "feed_url": feed_url,
            "http_status": 304,
        }

    response.raise_for_status()
    alerts = parse_sachet_feed(response.content)
    upsert_alerts(alerts)

    update_feed_state(
        feed_url,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
        http_status=response.status_code,
        success=True,
    )

    return {
        "status": "updated",
        "new_alerts": len(alerts),
        "feed_url": feed_url,
        "http_status": response.status_code,
    }
