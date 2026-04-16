"""
tests/test_vegetation.py
────────────────────────
Unit tests for vegetation index computation, cloud masking,
snapshot statistics, and change detection.

Run: pytest tests/test_vegetation.py -v
"""

import numpy as np
import pytest

from analysis.vegetation import (
    VegetationAnalyzer,
    VegetationIndex,
    AlertSeverity,
    ChangeEvent,
    VegetationSnapshot,
    VEGETATION_THRESHOLDS,
    MIN_CLEARING_PIXELS,
)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def analyzer():
    return VegetationAnalyzer(vegetation_zone="guinea_savanna")


@pytest.fixture
def sahel_analyzer():
    return VegetationAnalyzer(vegetation_zone="sahel")


@pytest.fixture
def default_analyzer():
    return VegetationAnalyzer(vegetation_zone="default")


@pytest.fixture
def test_bbox():
    """Zamfara corridor bbox for tests."""
    return [6.0, 11.5, 7.5, 12.8]


def _make_bands(
    red_val=500.0, nir_val=4000.0, blue_val=300.0,
    swir1_val=1000.0, swir2_val=800.0,
    size=64, scl_val=4,
):
    """Create synthetic Sentinel-2 bands with uniform values."""
    return {
        "B02": np.full((size, size), blue_val, dtype=np.float32),
        "B04": np.full((size, size), red_val, dtype=np.float32),
        "B08": np.full((size, size), nir_val, dtype=np.float32),
        "B11": np.full((size, size), swir1_val, dtype=np.float32),
        "B12": np.full((size, size), swir2_val, dtype=np.float32),
        "SCL": np.full((size, size), scl_val, dtype=np.float32),
    }


# ── NDVI ──────────────────────────────────────────────────────

class TestNDVI:
    def test_healthy_vegetation(self, analyzer):
        """High NIR, low Red → NDVI close to +1."""
        red = np.full((10, 10), 500, dtype=np.float32)
        nir = np.full((10, 10), 4000, dtype=np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert ndvi.shape == (10, 10)
        assert np.all(ndvi > 0.7)

    def test_bare_soil(self, analyzer):
        """Similar Red and NIR → NDVI near 0."""
        red = np.full((10, 10), 2000, dtype=np.float32)
        nir = np.full((10, 10), 2200, dtype=np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert np.all(np.abs(ndvi) < 0.1)

    def test_water_body(self, analyzer):
        """High Red, low NIR → negative NDVI."""
        red = np.full((10, 10), 3000, dtype=np.float32)
        nir = np.full((10, 10), 500, dtype=np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert np.all(ndvi < 0)

    def test_zero_division_safe(self, analyzer):
        """Both bands zero → 0, not NaN or inf."""
        red = np.zeros((5, 5), dtype=np.float32)
        nir = np.zeros((5, 5), dtype=np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert np.all(np.isfinite(ndvi))
        assert np.all(ndvi == 0.0)

    def test_output_range(self, analyzer):
        """NDVI always in [-1, 1]."""
        rng = np.random.default_rng(42)
        red = rng.uniform(0, 10000, (50, 50)).astype(np.float32)
        nir = rng.uniform(0, 10000, (50, 50)).astype(np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert np.all(ndvi >= -1.0)
        assert np.all(ndvi <= 1.0)

    def test_dtype_is_float32(self, analyzer):
        red = np.full((5, 5), 500, dtype=np.float32)
        nir = np.full((5, 5), 4000, dtype=np.float32)
        ndvi = analyzer.compute_ndvi(red, nir)
        assert ndvi.dtype == np.float32


# ── EVI ───────────────────────────────────────────────────────

class TestEVI:
    def test_basic_positive(self, analyzer):
        red = np.full((10, 10), 500, dtype=np.float32)
        nir = np.full((10, 10), 4000, dtype=np.float32)
        blue = np.full((10, 10), 300, dtype=np.float32)
        evi = analyzer.compute_evi(red, nir, blue)
        assert evi.shape == (10, 10)
        assert np.all(evi > 0)

    def test_clipped_to_range(self, analyzer):
        rng = np.random.default_rng(42)
        red = rng.uniform(0, 10000, (20, 20)).astype(np.float32)
        nir = rng.uniform(0, 10000, (20, 20)).astype(np.float32)
        blue = rng.uniform(0, 10000, (20, 20)).astype(np.float32)
        evi = analyzer.compute_evi(red, nir, blue)
        assert np.all(evi >= -1.0)
        assert np.all(evi <= 1.0)


# ── SAVI ──────────────────────────────────────────────────────

class TestSAVI:
    def test_sparse_vegetation(self, sahel_analyzer):
        """SAVI responds to sparse cover in arid zones."""
        red = np.full((10, 10), 1800, dtype=np.float32)
        nir = np.full((10, 10), 2500, dtype=np.float32)
        savi = sahel_analyzer.compute_savi(red, nir)
        assert np.all(savi > 0)

    def test_zero_safe(self, analyzer):
        red = np.zeros((5, 5), dtype=np.float32)
        nir = np.zeros((5, 5), dtype=np.float32)
        savi = analyzer.compute_savi(red, nir)
        assert np.all(np.isfinite(savi))


# ── NBR ───────────────────────────────────────────────────────

class TestNBR:
    def test_burn_scar(self, analyzer):
        """Post-fire: low NIR, high SWIR → negative NBR."""
        nir = np.full((10, 10), 500, dtype=np.float32)
        swir2 = np.full((10, 10), 3000, dtype=np.float32)
        nbr = analyzer.compute_nbr(nir, swir2)
        assert np.all(nbr < 0)

    def test_healthy_forest(self, analyzer):
        """Healthy: high NIR, low SWIR → positive NBR."""
        nir = np.full((10, 10), 4000, dtype=np.float32)
        swir2 = np.full((10, 10), 800, dtype=np.float32)
        nbr = analyzer.compute_nbr(nir, swir2)
        assert np.all(nbr > 0)

    def test_output_range(self, analyzer):
        rng = np.random.default_rng(7)
        nir = rng.uniform(0, 10000, (30, 30)).astype(np.float32)
        swir = rng.uniform(0, 10000, (30, 30)).astype(np.float32)
        nbr = analyzer.compute_nbr(nir, swir)
        assert np.all(nbr >= -1.0)
        assert np.all(nbr <= 1.0)


# ── NDMI ──────────────────────────────────────────────────────

class TestNDMI:
    def test_moist_vegetation(self, analyzer):
        nir = np.full((10, 10), 4000, dtype=np.float32)
        swir1 = np.full((10, 10), 1500, dtype=np.float32)
        ndmi = analyzer.compute_ndmi(nir, swir1)
        assert np.all(ndmi > 0)

    def test_dry_vegetation(self, analyzer):
        """When SWIR > NIR, NDMI is negative (water stress)."""
        nir = np.full((10, 10), 1000, dtype=np.float32)
        swir1 = np.full((10, 10), 3000, dtype=np.float32)
        ndmi = analyzer.compute_ndmi(nir, swir1)
        assert np.all(ndmi < 0)


# ── compute_index dispatch ────────────────────────────────────

class TestComputeIndex:
    def test_all_indices_run(self, analyzer):
        """Every VegetationIndex enum value dispatches correctly."""
        bands = _make_bands()
        for idx in VegetationIndex:
            result = analyzer.compute_index(bands, idx)
            assert result.shape == (64, 64), f"Failed for {idx}"
            assert np.all(np.isfinite(result)), f"NaN/inf for {idx}"

    def test_invalid_index_raises(self, analyzer):
        bands = _make_bands()
        with pytest.raises((ValueError, KeyError)):
            analyzer.compute_index(bands, "not_an_index")


# ── Cloud Masking ─────────────────────────────────────────────

class TestCloudMasking:
    def test_clear_sky(self, analyzer):
        """SCL=4 (vegetation) → no mask."""
        scl = np.full((10, 10), 4, dtype=np.float32)
        mask = analyzer.create_cloud_mask(scl)
        assert np.sum(mask) == 0

    def test_full_cloud(self, analyzer):
        """SCL=9 (cloud high prob) → all masked."""
        scl = np.full((10, 10), 9, dtype=np.float32)
        mask = analyzer.create_cloud_mask(scl)
        assert np.all(mask)

    def test_mixed_scene(self, analyzer):
        scl = np.full((10, 10), 4, dtype=np.float32)
        scl[0:3, :] = 9   # cloud band at top
        scl[5, 5] = 3     # cloud shadow spot
        mask = analyzer.create_cloud_mask(scl)
        assert np.sum(mask) == 3 * 10 + 1

    def test_all_invalid_classes(self, analyzer):
        """Every invalid SCL class produces True."""
        for cls in [0, 1, 3, 8, 9, 10]:
            scl = np.full((5, 5), cls, dtype=np.float32)
            mask = analyzer.create_cloud_mask(scl)
            assert np.all(mask), f"Class {cls} should be masked"

    def test_all_valid_classes(self, analyzer):
        """Valid SCL classes produce False."""
        for cls in [2, 4, 5, 6, 7, 11]:
            scl = np.full((5, 5), cls, dtype=np.float32)
            mask = analyzer.create_cloud_mask(scl)
            assert not np.any(mask), f"Class {cls} should not be masked"

    def test_apply_mask(self, analyzer):
        data = np.ones((5, 5), dtype=np.float32)
        mask = np.zeros((5, 5), dtype=bool)
        mask[2, 2] = True
        masked = analyzer.apply_mask(data, mask)
        assert np.isnan(masked[2, 2])
        assert masked[0, 0] == 1.0


# ── Snapshot Statistics ───────────────────────────────────────

class TestSnapshot:
    def test_basic_snapshot(self, analyzer, test_bbox):
        bands = _make_bands()
        snap = analyzer.compute_snapshot(
            bands, "2024-01-15", test_bbox, VegetationIndex.NDVI,
        )
        assert isinstance(snap, VegetationSnapshot)
        assert snap.valid_pixels > 0
        assert snap.mean > 0  # healthy veg bands
        assert snap.cloud_fraction == 0.0  # SCL=4 = clear
        assert snap.histogram is not None
        assert len(snap.histogram) == 20

    def test_cloudy_snapshot(self, analyzer, test_bbox):
        bands = _make_bands(scl_val=9)  # all cloud
        snap = analyzer.compute_snapshot(
            bands, "2024-01-15", test_bbox, VegetationIndex.NDVI,
        )
        assert snap.valid_pixels == 0
        assert snap.cloud_fraction == 1.0
        assert snap.mean == 0.0

    def test_no_scl_band(self, analyzer, test_bbox):
        bands = _make_bands()
        del bands["SCL"]
        snap = analyzer.compute_snapshot(
            bands, "2024-01-15", test_bbox, VegetationIndex.NDVI,
        )
        assert snap.cloud_fraction == 0.0
        assert snap.valid_pixels > 0

    def test_to_dict(self, analyzer, test_bbox):
        bands = _make_bands()
        snap = analyzer.compute_snapshot(
            bands, "2024-01-15", test_bbox, VegetationIndex.NDVI,
        )
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert "mean" in d
        assert "bbox" in d
        assert "histogram" in d

    def test_different_indices(self, analyzer, test_bbox):
        """All indices produce valid snapshots."""
        bands = _make_bands()
        for idx in VegetationIndex:
            snap = analyzer.compute_snapshot(
                bands, "2024-01-15", test_bbox, idx,
            )
            assert snap.total_pixels == 64 * 64


# ── Change Detection ──────────────────────────────────────────

class TestChangeDetection:
    def test_no_change(self, analyzer, test_bbox):
        """Identical scenes → no events."""
        bands = _make_bands(size=64)
        events = analyzer.detect_changes(
            bands, bands,
            "2024-01-01", "2024-01-15",
            test_bbox,
        )
        assert len(events) == 0

    def test_clearing_detected(self, analyzer, test_bbox):
        """NIR drops in a contiguous block → clearing event."""
        bands_before = _make_bands(
            red_val=500, nir_val=4000, size=64,
        )
        bands_after = {k: v.copy() for k, v in bands_before.items()}

        # Simulate clearing: NIR drops, Red rises in 10×10 block
        bands_after["B08"][20:30, 20:30] = 600
        bands_after["B04"][20:30, 20:30] = 2000

        events = analyzer.detect_changes(
            bands_before, bands_after,
            "2024-01-01", "2024-01-15",
            test_bbox,
            min_area_pixels=10,
        )

        clearings = [
            e for e in events if e.classification == "clearing"
        ]
        assert len(clearings) >= 1
        assert clearings[0].mean_change < 0
        assert clearings[0].area_pixels >= 10

    def test_burn_scar_detected(self, analyzer, test_bbox):
        """SWIR rises, NIR drops → burn scar detected via dNBR."""
        bands_before = _make_bands(
            nir_val=4000, swir2_val=800, size=64,
        )
        bands_after = {k: v.copy() for k, v in bands_before.items()}

        # Burn scar block: NIR crashes, SWIR spikes
        bands_after["B08"][30:42, 30:42] = 800
        bands_after["B12"][30:42, 30:42] = 3500
        bands_after["B04"][30:42, 30:42] = 2500

        events = analyzer.detect_changes(
            bands_before, bands_after,
            "2024-01-01", "2024-01-15",
            test_bbox,
            min_area_pixels=10,
        )

        burns = [
            e for e in events if e.classification == "burn_scar"
        ]
        assert len(burns) >= 1

    def test_small_change_ignored(self, analyzer, test_bbox):
        """Change smaller than min_area_pixels is not reported."""
        bands_before = _make_bands(size=64)
        bands_after = {k: v.copy() for k, v in bands_before.items()}

        # Tiny 2×2 clearing (only 4 pixels)
        bands_after["B08"][10:12, 10:12] = 600
        bands_after["B04"][10:12, 10:12] = 2000

        events = analyzer.detect_changes(
            bands_before, bands_after,
            "2024-01-01", "2024-01-15",
            test_bbox,
            min_area_pixels=10,
        )
        assert len(events) == 0

    def test_cloud_masked_change_excluded(self, analyzer, test_bbox):
        """Change under cloud cover should not trigger an event."""
        bands_before = _make_bands(size=64)
        bands_after = {k: v.copy() for k, v in bands_before.items()}

        # Change in area that is cloud-masked in after image
        bands_after["B08"][20:30, 20:30] = 600
        bands_after["B04"][20:30, 20:30] = 2000
        bands_after["SCL"][20:30, 20:30] = 9  # cloud

        events = analyzer.detect_changes(
            bands_before, bands_after,
            "2024-01-01", "2024-01-15",
            test_bbox,
            min_area_pixels=10,
        )
        clearings = [
            e for e in events if e.classification == "clearing"
        ]
        assert len(clearings) == 0

    def test_event_fields_correct(self, analyzer, test_bbox):
        """Events have all required fields with correct types."""
        bands_before = _make_bands(size=64)
        bands_after = {k: v.copy() for k, v in bands_before.items()}
        bands_after["B08"][15:30, 15:30] = 600
        bands_after["B04"][15:30, 15:30] = 2000

        events = analyzer.detect_changes(
            bands_before, bands_after,
            "2024-01-01", "2024-01-15",
            test_bbox,
            min_area_pixels=10,
        )
        assert len(events) > 0
        e = events[0]
        assert isinstance(e, ChangeEvent)
        assert e.event_id
        assert e.latitude > 0
        assert e.longitude > 0
        assert e.date_before == "2024-01-01"
        assert e.date_after == "2024-01-15"
        assert e.severity in [s.value for s in AlertSeverity]
        assert 0 <= e.confidence <= 1.0
        assert e.area_hectares > 0
        assert len(e.bbox) == 4

    def test_event_to_dict(self, analyzer, test_bbox):
        bands_before = _make_bands(size=64)
        bands_after = {k: v.copy() for k, v in bands_before.items()}
        bands_after["B08"][15:30, 15:30] = 600
        bands_after["B04"][15:30, 15:30] = 2000

        