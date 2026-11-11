import hashlib
import unittest

from app.services.geospatial_service import (
    haversine_km,
    match_alert_location,
    point_in_polygon,
)
from app.services.sachet_service import (
    parse_cap_document,
    parse_polygon_document,
    parse_sachet_feed,
)


SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample CAP feed</title>
    <item>
      <title>Flood warning for Example District</title>
      <description>Heavy rainfall may cause flooding in low-lying areas.</description>
      <guid>sample-alert-001</guid>
      <link>https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=sample001</link>
      <pubDate>Tue, 10 Nov 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_CAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<cap:alert xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <cap:identifier>IN-sample001_17</cap:identifier>
  <cap:sender>West-Bengal-SDMA</cap:sender>
  <cap:sent>2026-11-11T09:51:21+05:30</cap:sent>
  <cap:status>Actual</cap:status>
  <cap:msgType>Update</cap:msgType>
  <cap:scope>Public</cap:scope>
  <cap:info>
    <cap:language>BN</cap:language>
    <cap:category>Met</cap:category>
    <cap:event>Light Thunderstorms</cap:event>
    <cap:urgency>Expected</cap:urgency>
    <cap:severity>Moderate</cap:severity>
    <cap:certainty>Likely</cap:certainty>
    <cap:headline>বাংলা সতর্কতা</cap:headline>
    <cap:area>
      <cap:areaDesc>4 districts of West Bengal</cap:areaDesc>
      <cap:geocode><cap:valueName>LGD District Code</cap:valueName><cap:value>313</cap:value></cap:geocode>
    </cap:area>
  </cap:info>
  <cap:info>
    <cap:language>en-IN</cap:language>
    <cap:category>Met</cap:category>
    <cap:event>Light Thunderstorms</cap:event>
    <cap:urgency>Expected</cap:urgency>
    <cap:severity>Moderate</cap:severity>
    <cap:certainty>Likely</cap:certainty>
    <cap:effective>2026-11-11T09:35:00+05:30</cap:effective>
    <cap:onset>2026-11-11T09:51:21+05:30</cap:onset>
    <cap:expires>2026-11-11T17:35:00+05:30</cap:expires>
    <cap:headline>Light to moderate rain and thunderstorm</cap:headline>
    <cap:instruction>Follow SDMA guidelines.</cap:instruction>
    <cap:parameter><cap:valueName>Polygon URL</cap:valueName><cap:value>https://sachet.ndma.gov.in/cap_public_website/FetchPolygonXMLFile?identifier=sample001</cap:value></cap:parameter>
    <cap:area>
      <cap:areaDesc>4 districts of West Bengal</cap:areaDesc>
      <cap:geocode><cap:valueName>LGD District Code</cap:valueName><cap:value>313</cap:value></cap:geocode>
      <cap:geocode><cap:valueName>LGD District Code</cap:valueName><cap:value>315</cap:value></cap:geocode>
    </cap:area>
  </cap:info>
</cap:alert>
"""

SAMPLE_POLYGON = b"""<PolygonData>
  <Polygon>12.0,77.0 12.0,78.0 13.0,78.0 13.0,77.0</Polygon>
</PolygonData>"""


class GeospatialTests(unittest.TestCase):
    def test_same_point_distance_is_zero(self):
        self.assertAlmostEqual(haversine_km(12.0, 77.0, 12.0, 77.0), 0.0)

    def test_point_inside_polygon(self):
        polygon = [[10, 10], [10, 20], [20, 20], [20, 10]]
        self.assertTrue(point_in_polygon(15, 15, polygon))
        self.assertFalse(point_in_polygon(25, 25, polygon))

    def test_alert_circle_match(self):
        alert = {"circles": [{"latitude": 12.0, "longitude": 77.0, "radius_km": 10}]}
        result = match_alert_location(alert, 12.01, 77.01)
        self.assertTrue(result["matched"])
        self.assertEqual(result["method"], "cap_circle")

    def test_missing_geometry_is_unverified_not_false(self):
        alert = {"area_description": "District warning"}
        result = match_alert_location(alert, 12.0, 77.0)
        self.assertIsNone(result["matched"])


class SachetParserTests(unittest.TestCase):
    def test_parse_rss_cap_item(self):
        alerts = parse_sachet_feed(SAMPLE_FEED)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            alerts[0]["alert_id"],
            hashlib.sha256(b"sample-alert-001").hexdigest(),
        )
        self.assertEqual(alerts[0]["source_url"].split("/")[-1].split("?")[0], "FetchXMLFile")

    def test_parse_bilingual_cap_document(self):
        alert = parse_cap_document(
            SAMPLE_CAP,
            {
                "alert_id": "stable-rss-id",
                "title": "RSS headline",
                "source_url": "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=sample001",
            },
        )
        self.assertEqual(alert["title"], "Light to moderate rain and thunderstorm")
        self.assertEqual(alert["event"], "Light Thunderstorms")
        self.assertEqual(alert["severity"], "Moderate")
        self.assertEqual(alert["urgency"], "Expected")
        self.assertEqual(alert["status"], "Actual")
        self.assertEqual(alert["sender"], "West-Bengal-SDMA")
        self.assertEqual(alert["area_description"], "4 districts of West Bengal")
        self.assertEqual(len(alert["geocodes"]), 2)
        self.assertIn("BN", alert["languages"])
        self.assertIn("en-IN", alert["languages"])
        self.assertEqual(alert["expires_at"], "2026-11-11T12:05:00+00:00")
        self.assertTrue(alert["polygon_url"].endswith("identifier=sample001"))

    def test_parse_polygon_xml(self):
        polygons = parse_polygon_document(SAMPLE_POLYGON)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(polygons[0][0], [12.0, 77.0])


if __name__ == "__main__":
    unittest.main()
