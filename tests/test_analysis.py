"""
test_analysis.py
─────────────────
Run: python -m pytest tests/test_analysis.py -v
Or:  python tests/test_analysis.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_test_geojson():
    """Create a small test GeoJSON with known hotspots."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                "properties": {
                    "brightness": 350.0,
                    "confidence": "H",
                    "acq_date": "2026-04-15",
                    "acq_time": "0130",
                    "frp": "45.0",
                    "red_zone": "Northwest Corridor",
                    "source": "VIIRS_SNPP_NRT",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [13.5, 11.5]},  # Borno
                "properties": {
                    "brightness": 310.0,
                    "confidence": "N",
                    "acq_date": "2026-04-15",
                    "acq_time": "1400",
                    "frp": "10.0",
                    "red_zone": "Northeast Corridor",
                    "source": "VIIRS_SNPP_NRT",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [4.5, 8.3]},
                "properties": {
                    "brightness": 300.0,
                    "confidence": "L",
                    "acq_date": "2026-04-15",
                    "acq_time": "1200",
                    "frp": "2.0",
                    "red_zone": "Other",
                    "source": "VIIRS_SNPP_NRT",
                },
            },
        ],
        "metadata": {"count": 3, "source": "TEST"},
    }


class TestAnomalyScore:
    def test_score_hotspot_high_confidence(self):
        from analysis.anomaly_score import score_hotspot

        props = {
            "confidence": "H",
            "frp": "45.0",
            "brightness": 350.0,
            "acq_time": "0130",
            "red_zone": "Northwest Corridor",
        }
        score = score_hotspot(props)
        assert score >= 70, f"High confidence night detection should score >= 70, got {score}"
        assert score <= 100

    def test_score_hotspot_low_confidence(self):
        from analysis.anomaly_score import score_hotspot

        props = {
            "confidence": "L",
            "frp": "2.0",
            "brightness": 300.0,
            "acq_time": "1200",
            "red_zone": "Other",
        }
        score = score_hotspot(props)
        assert score <= 30, f"Low confidence daytime should score <= 30, got {score}"

    def test_score_hotspots_collection(self):
        from analysis.anomaly_score import score_hotspots

        geojson = _make_test_geojson()
        result = score_hotspots(geojson)

        assert "features" in result
        assert len(result["features"]) == 3
        assert result["metadata"]["scored"] is True

        scores = [f["properties"]["threat_score"] for f in result["features"]]
        assert scores == sorted(scores, reverse=True), f"Scores not sorted descending: {scores}"

        for f in result["features"]:
            assert "threat_score" in f["properties"]
            assert "priority" in f["properties"]
            assert f["properties"]["priority"] in ("CRITICAL", "HIGH", "ELEVATED", "MONITOR")

    def test_night_bonus(self):
        from analysis.anomaly_score import score_hotspot

        day_props = {"confidence": "H", "frp": "20", "brightness": 330, "acq_time": "1200", "red_zone": "Other"}
        night_props = {"confidence": "H", "frp": "20", "brightness": 330, "acq_time": "0200", "red_zone": "Other"}

        day_score = score_hotspot(day_props)
        night_score = score_hotspot(night_props)

        assert night_score > day_score, f"Night ({night_score}) should score higher than day ({day_score})"

    def test_red_zone_multiplier(self):
        from analysis.anomaly_score import score_hotspot

        base_props = {"confidence": "H", "frp": "20", "brightness": 330, "acq_time": "1200", "red_zone": "Other"}
        zone_props = {"confidence": "H", "frp": "20", "brightness": 330, "acq_time": "1200", "red_zone": "Northwest Corridor"}

        base_score = score_hotspot(base_props)
        zone_score = score_hotspot(zone_props)

        assert zone_score > base_score, f"Red zone ({zone_score}) should score higher than Other ({base_score})"


class TestRegionClassifier:
    def test_classify_zamfara(self):
        from analysis.region_classifier import classify_region

        result = classify_region(lat=12.5, lon=6.5)
        assert result["state"] == "Zamfara", f"Expected Zamfara, got {result['state']}"
        assert "Tier 1" in result["threat_tier"]

    def test_classify_borno(self):
        from analysis.region_classifier import classify_region

        # Use coordinates clearly inside Borno (Maiduguri area: 11.8°N, 13.2°E)
        result = classify_region(lat=11.8, lon=13.2)
        assert result["state"] == "Borno", f"Expected Borno, got {result['state']}"
        assert "Tier 1" in result["threat_tier"]

    def test_classify_yobe(self):
        from analysis.region_classifier import classify_region

        # Yobe: Damaturu area (11.7°N, 11.9°E)
        result = classify_region(lat=11.7, lon=11.9)
        assert result["state"] == "Yobe", f"Expected Yobe, got {result['state']}"
        assert "Tier 1" in result["threat_tier"]

    def test_classify_lagos(self):
        from analysis.region_classifier import classify_region

        result = classify_region(lat=6.5, lon=3.4)
        assert result["state"] == "Lagos", f"Expected Lagos, got {result['state']}"
        assert "Tier 4" in result["threat_tier"]

    def test_classify_kaduna(self):
        from analysis.region_classifier import classify_region

        result = classify_region(lat=10.5, lon=7.4)
        assert result["state"] == "Kaduna", f"Expected Kaduna, got {result['state']}"
        assert "Tier 2" in result["threat_tier"]

    def test_classify_unknown(self):
        from analysis.region_classifier import classify_region

        # Coordinates in the ocean
        result = classify_region(lat=0.0, lon=0.0)
        assert result["state"] == "Unknown"
        assert "Tier 4" in result["threat_tier"]

    def test_enrich_geojson(self):
        from analysis.region_classifier import enrich_with_regions

        geojson = _make_test_geojson()
        enriched = enrich_with_regions(geojson)

        assert len(enriched["features"]) == len(geojson["features"])
        for f in enriched["features"]:
            assert "state" in f["properties"]
            assert "threat_tier" in f["properties"]

    def test_get_all_states(self):
        from analysis.region_classifier import get_all_states

        states = get_all_states()
        assert len(states) >= 30, f"Expected 30+ states, got {len(states)}"
        assert "Borno" in states
        assert "Lagos" in states

    def test_get_threat_tier_states(self):
        from analysis.region_classifier import get_threat_tier_states

        tier1 = get_threat_tier_states("Tier 1")
        assert "Borno" in tier1
        assert "Zamfara" in tier1
        assert len(tier1) == 5


class TestChangeDetection:
    def test_detect_new_hotspots(self):
        from analysis.change_detection import detect_changes

        previous = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "H"},
                }
            ],
        }

        current = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "H"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [13.0, 11.0]},
                    "properties": {"confidence": "H"},
                },
            ],
        }

        result = detect_changes(previous, current)

        assert result["summary"]["persistent_count"] == 1
        assert result["summary"]["new_count"] == 1
        assert result["summary"]["resolved_count"] == 0
        assert result["summary"]["risk_level"] in ("ELEVATED", "HIGH", "CRITICAL")

    def test_detect_resolved_hotspots(self):
        from analysis.change_detection import detect_changes

        previous = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "N"},
                },
            ],
        }

        current = {
            "type": "FeatureCollection",
            "features": [],
        }

        result = detect_changes(previous, current)

        assert result["summary"]["resolved_count"] == 1
        assert result["summary"]["new_count"] == 0
        assert result["summary"]["persistent_count"] == 0
        assert result["summary"]["risk_level"] == "LOW"

    def test_all_new(self):
        from analysis.change_detection import detect_changes

        previous = {"type": "FeatureCollection", "features": []}
        current = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "H"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [13.0, 11.0]},
                    "properties": {"confidence": "H"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [6.0, 9.5]},
                    "properties": {"confidence": "H"},
                },
            ],
        }

        result = detect_changes(previous, current)

        assert result["summary"]["new_count"] == 3
        assert result["summary"]["high_confidence_new"] == 3
        assert result["summary"]["risk_level"] in ("HIGH", "CRITICAL")

    def test_change_tags(self):
        from analysis.change_detection import detect_changes

        previous = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "H"},
                },
            ],
        }
        current = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [8.5, 12.0]},
                    "properties": {"confidence": "H"},
                },
            ],
        }

        result = detect_changes(previous, current)

        for f in result["persistent"]:
            assert f["properties"]["change_tag"] == "persistent"


class TestFullPipeline:
    def test_end_to_end(self):
        """Test the full pipeline: FIRMS → regions → scoring."""
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        geojson = _make_test_geojson()

        # Step 1: Enrich with regions
        enriched = enrich_with_regions(geojson)
        assert all("state" in f["properties"] for f in enriched["features"])
        assert all("threat_tier" in f["properties"] for f in enriched["features"])

        # Step 2: Score
        scored = score_hotspots(enriched)
        assert scored["metadata"]["scored"] is True
        assert all("threat_score" in f["properties"] for f in scored["features"])
        assert all("priority" in f["properties"] for f in scored["features"])

        # Step 3: Verify first feature (should be highest scored)
        top = scored["features"][0]["properties"]
        assert top["threat_score"] > 0
        print(f"\n  [PIPELINE] Top threat: {top['threat_score']} ({top['priority']}) "
              f"in {top.get('state', '?')} — {top.get('threat_tier', '?')}")

    def test_pipeline_with_change_detection(self):
        """Test full pipeline including change detection."""
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions
        from analysis.change_detection import detect_changes

        previous = _make_test_geojson()
        current = _make_test_geojson()

        # Add a new hotspot to current
        current["features"].append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [7.0, 12.5]},
            "properties": {
                "brightness": 400.0,
                "confidence": "H",
                "acq_date": "2026-04-16",
                "acq_time": "0300",
                "frp": "60.0",
                "red_zone": "Northwest Corridor",
                "source": "VIIRS_SNPP_NRT",
            },
        })

        # Enrich both
        previous = enrich_with_regions(previous)
        current = enrich_with_regions(current)

        # Detect changes
        changes = detect_changes(previous, current)

        assert changes["summary"]["new_count"] >= 1
        assert changes["summary"]["persistent_count"] >= 2

        # Score the current data
        scored = score_hotspots(current)
        assert scored["metadata"]["critical_count"] >= 1

        print(f"\n  [PIPELINE] Changes: {changes['summary']}")
        print(f"  [PIPELINE] Scored: {scored['metadata']['critical_count']} CRITICAL, "
              f"{scored['metadata']['high_count']} HIGH")


if __name__ == "__main__":
    print("=" * 60)
    print("  EagleEye-Nigeria — Analysis Module Tests")
    print("=" * 60)

    tests = [
        TestAnomalyScore(),
        TestRegionClassifier(),
        TestChangeDetection(),
        TestFullPipeline(),
    ]

    passed = 0
    failed = 0

    for test_class in tests:
        class_name = test_class.__class__.__name__
        print(f"\n  {class_name}:")
        methods = sorted([m for m in dir(test_class) if m.startswith("test_")])
        for method_name in methods:
            try:
                getattr(test_class, method_name)()
                print(f"    ✅ {method_name}")
                passed += 1
            except AssertionError as e:
                print(f"    ❌ {method_name}: {e}")
                failed += 1
            except Exception as e:
                print(f"    ❌ {method_name}: {type(e).__name__}: {e}")
                failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)