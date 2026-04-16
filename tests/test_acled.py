"""
test_acled.py
──────────────
Tests for ACLED integration.
Run: python tests/test_acled.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestACLED:
    def test_mock_events_structure(self):
        from ingestion.acled import _mock_acled_events

        data = _mock_acled_events()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 0
        assert "metadata" in data

        f = data["features"][0]
        assert f["type"] == "Feature"
        assert "coordinates" in f["geometry"]
        assert "event_type" in f["properties"]
        assert "fatalities" in f["properties"]
        assert "data_source" in f["properties"]

    def test_correlation(self):
        from ingestion.acled import _mock_acled_events, correlate_with_hotspots

        # Mock hotspots near known ACLED events
        hotspots = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [7.5, 12.0]},
                    "properties": {"confidence": "H", "brightness": 350},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [3.0, 6.5]},
                    "properties": {"confidence": "L", "brightness": 300},
                },
            ],
            "metadata": {"count": 2},
        }

        acled = _mock_acled_events()
        result = correlate_with_hotspots(hotspots, acled, radius_km=50)

        assert "features" in result
        assert result["metadata"]["acled_correlated"] is True

        # First hotspot (near Zamfara) should have correlations
        first = result["features"][0]["properties"]
        assert "nearby_conflict_events" in first
        assert "conflict_correlation" in first

    def test_events_to_geojson(self):
        from ingestion.acled import _events_to_geojson

        events = [
            {
                "event_id_cnty": "NGA123",
                "event_date": "2026-04-10",
                "event_type": "Battles",
                "sub_event_type": "Armed clash",
                "actor1": "Military",
                "actor2": "Bandits",
                "admin1": "Zamfara",
                "admin2": "Anka",
                "location": "Anka",
                "latitude": "12.0",
                "longitude": "7.5",
                "fatalities": "5",
                "notes": "Test event",
                "source": "Test",
            }
        ]

        result = _events_to_geojson(events)
        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 1
        assert result["features"][0]["properties"]["fatalities"] == 5


if __name__ == "__main__":
    print("=" * 60)
    print("  EagleEye-Nigeria — ACLED Integration Tests")
    print("=" * 60)

    tests = TestACLED()
    passed = 0
    failed = 0

    for method in sorted(dir(tests)):
        if not method.startswith("test_"):
            continue
        try:
            getattr(tests, method)()
            print(f"  ✅ {method}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {method}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {method}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n  Results: {passed} passed, {failed} failed")
    print("=" * 60)