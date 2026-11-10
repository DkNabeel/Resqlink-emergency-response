import unittest

from app.services.geospatial_service import (
    haversine_km,
    match_alert_location,
    point_in_polygon,
)
from app.services.sachet_service import parse_sachet_feed


SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
 xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <channel>
    <title>Sample CAP feed</title>
    <item>
      <title>Flood warning for Example District</title>
      <description>Heavy rainfall may cause flooding in low-lying areas.</description>
      <guid>sample-alert-001</guid>
      <link>https://example.gov.invalid/alerts/001</link>
      <pubDate>Tue, 10 Nov 2026 10:00:00 GMT</pubDate>
      <cap:status>Actual</cap:status>
      <cap:msgType>Alert</cap:msgType>
      <cap:info>
        <cap:category>Met</cap:category>
        <cap:event>Flood</cap:event>
        <cap:urgency>Immediate</cap:urgency>
        <cap:severity>Severe</cap:severity>
        <cap:certainty>Likely</cap:certainty>
        <cap:area>
          <cap:areaDesc>Example District</cap:areaDesc>
          <cap:circle>12.0000,77.0000 10</cap:circle>
        </cap:area>
      </cap:info>
    </item>
  </channel>
</rss>
"""


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
        alert = alerts[0]
        self.assertEqual(alert["alert_id"], "sample-alert-001")
        self.assertEqual(alert["event"], "Flood")
        self.assertEqual(alert["severity"], "Severe")
        self.assertEqual(alert["area_description"], "Example District")
        self.assertEqual(len(alert["circles"]), 1)
        self.assertEqual(alert["status"], "Actual")


if __name__ == "__main__":
    unittest.main()
