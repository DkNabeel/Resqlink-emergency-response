import json
from datetime import datetime, timezone

from app.database.connection import get_connection


def _now():
    return datetime.now(timezone.utc).isoformat()


def _decode_alert(row):
    alert = dict(row)
    for column, key, fallback in (
        ("polygons_json", "polygons", []),
        ("circles_json", "circles", []),
        ("geocodes_json", "geocodes", []),
        ("references_json", "references", []),
        ("languages_json", "languages", {}),
        ("parameters_json", "parameters", []),
    ):
        raw = alert.pop(column, None)
        try:
            alert[key] = json.loads(raw or ("{}" if fallback == {} else "[]"))
        except (TypeError, json.JSONDecodeError):
            alert[key] = fallback
    return alert


def upsert_alert(alert):
    """Insert an alert or update it when the same official identifier appears."""
    now = _now()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, source, title, description, event, category,
                severity, urgency, certainty, status, message_type,
                effective_at, expires_at, published_at, area_description,
                polygons_json, circles_json, geocodes_json, references_json,
                source_url, raw_content, first_seen_at, last_seen_at,
                sender, scope, onset_at, cap_identifier,
                languages_json, parameters_json
            ) VALUES (
                :alert_id, :source, :title, :description, :event, :category,
                :severity, :urgency, :certainty, :status, :message_type,
                :effective_at, :expires_at, :published_at, :area_description,
                :polygons_json, :circles_json, :geocodes_json, :references_json,
                :source_url, :raw_content, :first_seen_at, :last_seen_at,
                :sender, :scope, :onset_at, :cap_identifier,
                :languages_json, :parameters_json
            )
            ON CONFLICT(alert_id) DO UPDATE SET
                source = excluded.source,
                title = excluded.title,
                description = excluded.description,
                event = excluded.event,
                category = excluded.category,
                severity = excluded.severity,
                urgency = excluded.urgency,
                certainty = excluded.certainty,
                status = excluded.status,
                message_type = excluded.message_type,
                effective_at = excluded.effective_at,
                expires_at = excluded.expires_at,
                published_at = excluded.published_at,
                area_description = excluded.area_description,
                polygons_json = excluded.polygons_json,
                circles_json = excluded.circles_json,
                geocodes_json = excluded.geocodes_json,
                references_json = excluded.references_json,
                source_url = excluded.source_url,
                raw_content = excluded.raw_content,
                sender = excluded.sender,
                scope = excluded.scope,
                onset_at = excluded.onset_at,
                cap_identifier = excluded.cap_identifier,
                languages_json = excluded.languages_json,
                parameters_json = excluded.parameters_json,
                last_seen_at = excluded.last_seen_at
            """,
            {
                "alert_id": alert["alert_id"],
                "source": alert.get("source", "NDMA SACHET"),
                "title": alert.get("title") or "Official public-safety alert",
                "description": alert.get("description"),
                "event": alert.get("event"),
                "category": alert.get("category"),
                "severity": alert.get("severity"),
                "urgency": alert.get("urgency"),
                "certainty": alert.get("certainty"),
                "status": alert.get("status") or "Unknown",
                "message_type": alert.get("message_type"),
                "effective_at": alert.get("effective_at"),
                "expires_at": alert.get("expires_at"),
                "published_at": alert.get("published_at"),
                "area_description": alert.get("area_description"),
                "polygons_json": json.dumps(alert.get("polygons", []), ensure_ascii=False),
                "circles_json": json.dumps(alert.get("circles", []), ensure_ascii=False),
                "geocodes_json": json.dumps(alert.get("geocodes", []), ensure_ascii=False),
                "references_json": json.dumps(alert.get("references", []), ensure_ascii=False),
                "source_url": alert.get("source_url"),
                "raw_content": (alert.get("raw_content") or "")[:4000],
                "first_seen_at": now,
                "last_seen_at": now,
                "sender": alert.get("sender"),
                "scope": alert.get("scope"),
                "onset_at": alert.get("onset_at"),
                "cap_identifier": alert.get("cap_identifier"),
                "languages_json": json.dumps(alert.get("languages", {}), ensure_ascii=False),
                "parameters_json": json.dumps(alert.get("parameters", []), ensure_ascii=False),
            },
        )
        connection.commit()
    finally:
        connection.close()


def upsert_alerts(alerts):
    for alert in alerts:
        upsert_alert(alert)


def get_active_alerts(limit=100):
    now = _now()
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT *
            FROM alerts
            WHERE UPPER(status) NOT IN ('CANCELLED', 'TEST', 'EXERCISE')
              AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)
            ORDER BY COALESCE(published_at, first_seen_at) DESC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [_decode_alert(row) for row in rows]
    finally:
        connection.close()


def get_recent_alerts(limit=100):
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT *
            FROM alerts
            ORDER BY COALESCE(published_at, first_seen_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_decode_alert(row) for row in rows]
    finally:
        connection.close()


def get_feed_state(feed_url):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM feed_sync_state WHERE feed_url = ?",
            (feed_url,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def update_feed_state(
    feed_url,
    *,
    etag=None,
    last_modified=None,
    http_status=None,
    error=None,
    success=False,
):
    now = _now()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO feed_sync_state (
                feed_url, etag, last_modified, last_checked_at,
                last_success_at, last_http_status, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feed_url) DO UPDATE SET
                etag = COALESCE(excluded.etag, feed_sync_state.etag),
                last_modified = COALESCE(excluded.last_modified, feed_sync_state.last_modified),
                last_checked_at = excluded.last_checked_at,
                last_success_at = CASE
                    WHEN ? THEN excluded.last_checked_at
                    ELSE feed_sync_state.last_success_at
                END,
                last_http_status = excluded.last_http_status,
                last_error = excluded.last_error
            """,
            (
                feed_url,
                etag,
                last_modified,
                now,
                now if success else None,
                http_status,
                error,
                1 if success else 0,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_alert_count():
    connection = get_connection()
    try:
        row = connection.execute("SELECT COUNT(*) AS count FROM alerts").fetchone()
        return int(row["count"])
    finally:
        connection.close()


def get_document_cache(document_url):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM external_document_cache WHERE document_url = ?",
            (document_url,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def save_document_cache(
    document_url, content, *, etag=None, last_modified=None, http_status=200
):
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO external_document_cache (
                document_url, etag, last_modified, content, fetched_at,
                last_http_status
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_url) DO UPDATE SET
                etag = COALESCE(excluded.etag, external_document_cache.etag),
                last_modified = COALESCE(excluded.last_modified, external_document_cache.last_modified),
                content = excluded.content,
                fetched_at = excluded.fetched_at,
                last_http_status = excluded.last_http_status
            """,
            (
                document_url,
                etag,
                last_modified,
                content,
                _now(),
                http_status,
            ),
        )
        connection.commit()
    finally:
        connection.close()
