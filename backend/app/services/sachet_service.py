import asyncio
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
    get_document_cache,
    get_feed_state,
    save_document_cache,
    update_feed_state,
    upsert_alerts,
)


DEFAULT_SACHET_FEED = (
    "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
)
ALLOWED_SACHET_HOST = "sachet.ndma.gov.in"


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
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _descendant_values(element):
    values = {}
    for node in element.iter():
        name = _local_name(node.tag)
        text_value = _clean_text(" ".join(node.itertext()))
        if text_value:
            values.setdefault(name, []).append(text_value)
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


def _child_text(parent, name):
    for child in list(parent):
        if _local_name(child.tag) == name.lower():
            return _clean_text(" ".join(child.itertext()))
    return None


def _children(parent, name):
    return [child for child in list(parent) if _local_name(child.tag) == name.lower()]


def _parse_polygon_text(value):
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


def _valid_sachet_url(url):
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == ALLOWED_SACHET_HOST


def _extract_info(info):
    payload = {
        key: _child_text(info, key)
        for key in (
            "language", "category", "event", "urgency", "severity",
            "certainty", "effective", "onset", "expires", "headline",
            "description", "instruction",
        )
    }
    payload["areas"] = []
    for area in _children(info, "area"):
        area_data = {
            "area_description": _child_text(area, "areaDesc"),
            "polygons": [],
            "circles": [],
            "geocodes": [],
        }
        for polygon_node in _children(area, "polygon"):
            polygon = _parse_polygon_text(" ".join(polygon_node.itertext()))
            if polygon:
                area_data["polygons"].append(polygon)
        for circle_node in _children(area, "circle"):
            circle = _parse_circle(" ".join(circle_node.itertext()))
            if circle:
                area_data["circles"].append(circle)
        for geocode in _children(area, "geocode"):
            name = _child_text(geocode, "valueName")
            value = _child_text(geocode, "value")
            if name and value:
                area_data["geocodes"].append({"name": name, "value": value})
        area_data["areas_description"] = area_data["area_description"]
        payload["areas"].append(area_data)

    payload["parameters"] = []
    for parameter in _children(info, "parameter"):
        name = _child_text(parameter, "valueName")
        value = _child_text(parameter, "value")
        if name and value:
            payload["parameters"].append({"name": name, "value": value})
    return payload


def parse_cap_document(xml_content, base_alert=None):
    """Parse one CAP 1.2 alert, preserving every language-specific info block."""
    root = ElementTree.fromstring(xml_content)
    if _local_name(root.tag) != "alert":
        raise ValueError("CAP document root must be <alert>.")

    root_fields = {
        key: _child_text(root, key)
        for key in (
            "identifier", "sender", "sent", "status", "msgType",
            "scope", "references",
        )
    }
    info_blocks = [_extract_info(node) for node in _children(root, "info")]
    if not info_blocks:
        raise ValueError("CAP document contains no <info> block.")

    languages = {}
    for index, info in enumerate(info_blocks):
        language = (info.get("language") or f"unknown-{index + 1}").strip()
        key = language
        if key in languages:
            key = f"{language}-{index + 1}"
        languages[key] = info

    # Prefer English for the primary display fields; retain all translations.
    primary = next(
        (info for info in info_blocks if (info.get("language") or "").lower().startswith("en")),
        info_blocks[0],
    )
    area = next(
        (item for item in primary["areas"] if item.get("area_description")),
        primary["areas"][0] if primary["areas"] else {},
    )

    alert = dict(base_alert or {})
    alert.update({
        "cap_identifier": root_fields.get("identifier"),
        "sender": root_fields.get("sender"),
        "scope": root_fields.get("scope"),
        "status": root_fields.get("status") or alert.get("status") or "Unknown",
        "message_type": root_fields.get("msgType") or alert.get("message_type"),
        "published_at": _parse_datetime(root_fields.get("sent")) or alert.get("published_at"),
        "title": primary.get("headline") or alert.get("title") or "Official public-safety alert",
        "description": primary.get("description") or primary.get("instruction") or alert.get("description") or "",
        "event": primary.get("event") or alert.get("event"),
        "category": primary.get("category") or alert.get("category"),
        "severity": primary.get("severity") or alert.get("severity"),
        "urgency": primary.get("urgency") or alert.get("urgency"),
        "certainty": primary.get("certainty") or alert.get("certainty"),
        "effective_at": _parse_datetime(primary.get("effective")) or alert.get("effective_at"),
        "onset_at": _parse_datetime(primary.get("onset")),
        "expires_at": _parse_datetime(primary.get("expires")) or alert.get("expires_at"),
        "area_description": area.get("area_description") or alert.get("area_description"),
        "polygons": area.get("polygons", []) or alert.get("polygons", []),
        "circles": area.get("circles", []) or alert.get("circles", []),
        "geocodes": area.get("geocodes", []) or alert.get("geocodes", []),
        "references": [root_fields["references"]] if root_fields.get("references") else alert.get("references", []),
        "languages": languages,
        "parameters": primary.get("parameters", []),
        "raw_content": primary.get("description") or primary.get("instruction") or alert.get("raw_content") or "",
    })

    polygon_urls = [
        item["value"] for item in alert["parameters"]
        if item.get("name", "").strip().lower() == "polygon url"
        and _valid_sachet_url(item.get("value"))
    ]
    alert["polygon_url"] = polygon_urls[0] if polygon_urls else None
    return alert


def parse_polygon_document(xml_content):
    """Extract CAP-style lat,lon polygons or KML lon,lat coordinate sequences."""
    root = ElementTree.fromstring(xml_content)
    polygons = []
    for node in root.iter():
        name = _local_name(node.tag)
        text_value = _clean_text(" ".join(node.itertext()))
        if not text_value:
            continue
        if name in {"polygon", "latlon", "latlong"}:
            polygon = _parse_polygon_text(text_value)
            if polygon:
                polygons.append(polygon)
        elif name == "coordinates":
            points = []
            for token in text_value.split():
                parts = token.split(",")
                if len(parts) < 2:
                    continue
                try:
                    longitude, latitude = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    points.append([latitude, longitude])
            if len(points) >= 3:
                polygons.append(points)

    # De-duplicate identical rings which may be nested in wrapper elements.
    unique = []
    seen = set()
    for polygon in polygons:
        key = tuple((round(p[0], 7), round(p[1], 7)) for p in polygon)
        if key not in seen:
            seen.add(key)
            unique.append(polygon)
    return unique


async def _get_cached_document(client, url):
    if not _valid_sachet_url(url):
        raise ValueError("Only HTTPS documents hosted on sachet.ndma.gov.in are allowed.")

    cached = get_document_cache(url)
    headers = {
        "Accept": "application/xml, text/xml, application/rss+xml;q=0.9, */*;q=0.1",
        "User-Agent": "ResQLink-Student-Project/1.0",
    }
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cached and cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]

    response = await client.get(url, headers=headers)
    if response.status_code == 304 and cached and cached.get("content"):
        return cached["content"], "not_modified"
    if response.status_code == 304:
        response = await client.get(url, headers={
            "Accept": headers["Accept"],
            "User-Agent": headers["User-Agent"],
        })
    response.raise_for_status()
    content = response.text
    save_document_cache(
        url,
        content,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
        http_status=response.status_code,
    )
    return content, "updated"


async def _enrich_one_alert(client, alert, semaphore):
    detail_url = alert.get("source_url")
    if not _valid_sachet_url(detail_url):
        return alert, False, False

    async with semaphore:
        try:
            cap_xml, _ = await _get_cached_document(client, detail_url)
            enriched = parse_cap_document(cap_xml, alert)
        except Exception as exc:
            alert["enrichment_error"] = f"{type(exc).__name__}: {exc}"[:300]
            return alert, False, False

        polygon_url = enriched.get("polygon_url")
        polygon_added = False
        if polygon_url:
            try:
                polygon_xml, _ = await _get_cached_document(client, polygon_url)
                polygons = parse_polygon_document(polygon_xml)
                if polygons:
                    enriched["polygons"] = polygons
                    polygon_added = True
            except Exception as exc:
                # Keep CAP metadata and district geocodes even if polygon retrieval fails.
                enriched["polygon_fetch_error"] = f"{type(exc).__name__}: {exc}"[:300]

        return enriched, True, polygon_added


async def _enrich_alerts(client, alerts):
    max_concurrent = max(1, min(20, int(os.getenv("SACHET_DETAIL_CONCURRENCY", "8"))))
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [_enrich_one_alert(client, alert, semaphore) for alert in alerts]
    results = await asyncio.gather(*tasks)
    enriched_alerts = []
    cap_count = 0
    polygon_count = 0
    for alert, cap_ok, polygon_ok in results:
        enriched_alerts.append(alert)
        cap_count += int(cap_ok)
        polygon_count += int(polygon_ok)
    return enriched_alerts, cap_count, polygon_count


def parse_sachet_feed(xml_content):
    """Parse the public RSS index; full CAP content is fetched by sync_sachet_feed."""
    root = ElementTree.fromstring(xml_content)
    items = [
        node for node in root.iter()
        if _local_name(node.tag) in {"item", "entry"}
    ]

    alerts = []
    for item in items:
        values = _descendant_values(item)
        title = _first(values, "title")
        description = _first(values, "description", "summary", "content")
        link = _first(values, "link_href", "link")
        guid = _first(values, "guid", "id", "identifier")
        published = _first(values, "pubdate", "published", "updated", "date")

        if not title and not description:
            continue

        source_url = link if _valid_sachet_url(link) else None
        stable_key = guid or "|".join((source_url or "", title or "", published or ""))
        alert_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()

        alerts.append({
            "alert_id": alert_id,
            "source": "NDMA SACHET",
            "title": _clean_text(title)[:500] or "Official public-safety alert",
            "description": _clean_text(description)[:3000],
            "event": None,
            "category": None,
            "severity": None,
            "urgency": None,
            "certainty": None,
            "status": "Unknown",
            "message_type": None,
            "effective_at": None,
            "onset_at": None,
            "expires_at": None,
            "published_at": _parse_datetime(published),
            "area_description": None,
            "polygons": [],
            "circles": [],
            "geocodes": [],
            "references": [],
            "languages": {},
            "parameters": [],
            "source_url": source_url,
            "raw_content": _clean_text(description)[:4000],
        })

    return alerts


async def sync_sachet_feed(feed_url=None):
    """Fetch RSS, enrich linked CAP documents, and cache CAP/polygon XML by ETag."""
    feed_url = feed_url or os.getenv("SACHET_FEED_URL", DEFAULT_SACHET_FEED)
    if not _valid_sachet_url(feed_url):
        raise ValueError("SACHET_FEED_URL must be HTTPS on sachet.ndma.gov.in.")

    previous = get_feed_state(feed_url) or {}
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
        "User-Agent": "ResQLink-Student-Project/1.0",
    }
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    if previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]

    timeout = httpx.Timeout(30.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(feed_url, headers=headers)
            feed_headers = response.headers
            feed_http_status = response.status_code

            if response.status_code == 304:
                # Reuse the cached RSS body so the existing alert list is still
                # re-enriched with CAP documents on every collector cycle.
                cached_rss = get_document_cache(feed_url)
                if cached_rss and cached_rss.get("content"):
                    rss_content = cached_rss["content"]
                else:
                    # Older installations may have an ETag but no cached body.
                    unconditional_headers = {
                        "Accept": headers["Accept"],
                        "User-Agent": headers["User-Agent"],
                    }
                    full_response = await client.get(
                        feed_url, headers=unconditional_headers
                    )
                    full_response.raise_for_status()
                    rss_content = full_response.text
                    feed_headers = full_response.headers
                    feed_http_status = full_response.status_code
                    save_document_cache(
                        feed_url,
                        rss_content,
                        etag=feed_headers.get("ETag"),
                        last_modified=feed_headers.get("Last-Modified"),
                        http_status=feed_http_status,
                    )
            else:
                response.raise_for_status()
                rss_content = response.text
                save_document_cache(
                    feed_url,
                    rss_content,
                    etag=feed_headers.get("ETag"),
                    last_modified=feed_headers.get("Last-Modified"),
                    http_status=feed_http_status,
                )

            alerts = parse_sachet_feed(rss_content)
            alerts, enriched_count, polygon_count = await _enrich_alerts(client, alerts)
            upsert_alerts(alerts)

        update_feed_state(
            feed_url,
            etag=feed_headers.get("ETag"),
            last_modified=feed_headers.get("Last-Modified"),
            http_status=feed_http_status,
            success=True,
        )

        return {
            "status": "updated",
            "new_alerts": len(alerts),
            "enriched_alerts": enriched_count,
            "polygon_alerts": polygon_count,
            "feed_url": feed_url,
            "http_status": response.status_code,
        }
    except Exception as exc:
        update_feed_state(
            feed_url,
            http_status=getattr(getattr(exc, "response", None), "status_code", None),
            error=f"{type(exc).__name__}: {exc}"[:500],
            success=False,
        )
        raise
