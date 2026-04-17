"""
analysis/vegetation.py
──────────────────────
Vegetation index computation and change detection from Sentinel-2 imagery.
Supports NDVI, EVI, SAVI, NBR, and NDMI for comprehensive vegetation monitoring.
Includes defensive cloud-mask handling and band validation.
"""

import logging
import numpy as np
from enum import Enum
from typing import Dict, Optional, List, Set, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger("eagleeye.vegetation")

# Thresholds calibrated for Nigerian vegetation zones
# Sources: FAO Land Cover Classification, literature on Sahel/Guinea savanna
VEGETATION_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "sahel": {
        "ndvi_healthy_min": 0.15,
        "ndvi_sparse_max": 0.25,
        "ndvi_dense_min": 0.45,
        "clearing_drop_threshold": -0.15,
        "regrowth_rise_threshold": 0.10,
    },
    "sudan_savanna": {
        "ndvi_healthy_min": 0.20,
        "ndvi_sparse_max": 0.30,
        "ndvi_dense_min": 0.55,
        "clearing_drop_threshold": -0.18,
        "regrowth_rise_threshold": 0.12,
    },
    "guinea_savanna": {
        "ndvi_healthy_min": 0.30,
        "ndvi_sparse_max": 0.40,
        "ndvi_dense_min": 0.65,
        "clearing_drop_threshold": -0.20,
        "regrowth_rise_threshold": 0.12,
    },
    "tropical_forest": {
        "ndvi_healthy_min": 0.45,
        "ndvi_sparse_max": 0.55,
        "ndvi_dense_min": 0.75,
        "clearing_drop_threshold": -0.25,
        "regrowth_rise_threshold": 0.15,
    },
    "mangrove": {
        "ndvi_healthy_min": 0.35,
        "ndvi_sparse_max": 0.45,
        "ndvi_dense_min": 0.70,
        "clearing_drop_threshold": -0.22,
        "regrowth_rise_threshold": 0.13,
    },
    "default": {
        "ndvi_healthy_min": 0.25,
        "ndvi_sparse_max": 0.35,
        "ndvi_dense_min": 0.60,
        "clearing_drop_threshold": -0.20,
        "regrowth_rise_threshold": 0.12,
    },
}

# Minimum contiguous pixels to flag as a clearing event
MIN_CLEARING_PIXELS = 25  # ~0.25 ha at 10m resolution

# If cloud masking removes more than this fraction, relax the mask
CLOUD_MASK_MAX_FRACTION = 0.95

# SCL classes
SCL_INVALID_STRICT: Set[int] = {0, 1, 3, 8, 9, 10}
SCL_INVALID_RELAXED: Set[int] = {0, 1, 9}  # Only worst offenders

# Required bands per index
INDEX_REQUIRED_BANDS: Dict[str, List[str]] = {
    "ndvi": ["B04", "B08"],
    "evi":  ["B02", "B04", "B08"],
    "savi": ["B04", "B08"],
    "nbr":  ["B08", "B12"],
    "ndmi": ["B08", "B11"],
}


class VegetationIndex(str, Enum):
    """Supported vegetation indices."""
    NDVI = "ndvi"
    EVI = "evi"
    SAVI = "savi"
    NBR = "nbr"
    NDMI = "ndmi"


class AlertSeverity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ChangeEvent:
    """A detected vegetation change event."""
    event_id: str
    latitude: float
    longitude: float
    bbox: List[float]
    date_before: str
    date_after: str
    index_used: str
    mean_change: float
    max_change: float
    area_pixels: int
    area_hectares: float
    severity: str
    classification: str   # "clearing" | "burn_scar" | "regrowth" | "seasonal"
    confidence: float
    vegetation_zone: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class VegetationSnapshot:
    """Vegetation index statistics for a single scene."""
    date: str
    bbox: List[float]
    index_name: str
    mean: float
    median: float
    std: float
    min_val: float
    max_val: float
    valid_pixels: int
    total_pixels: int
    cloud_fraction: float
    histogram: Optional[List[int]] = None
    mask_mode: str = "strict"  # "strict" | "relaxed" | "none"

    def to_dict(self) -> Dict:
        return asdict(self)


class VegetationAnalyzer:
    """
    Computes vegetation indices and detects changes between
    Sentinel-2 temporal pairs.
    """

    def __init__(self, vegetation_zone: str = "default"):
        if vegetation_zone not in VEGETATION_THRESHOLDS:
            print(
                f"[VEG] ⚠ Unknown zone '{vegetation_zone}', "
                f"falling back to 'default'"
            )
            logger.warning(
                "Unknown zone '%s', falling back to 'default'",
                vegetation_zone,
            )
            vegetation_zone = "default"
        self.zone = vegetation_zone
        self.thresholds = VEGETATION_THRESHOLDS[vegetation_zone]
        print(f"[VEG] Analyzer initialized: zone={vegetation_zone}")

    # ── Band Validation ───────────────────────────────────────

    @staticmethod
    def validate_bands(
        bands: Dict[str, np.ndarray],
        index: "VegetationIndex",
    ) -> Tuple[bool, str]:
        """
        Check that all bands required for a given index are present
        and contain usable data.

        Returns (is_valid, reason_string).
        """
        required = INDEX_REQUIRED_BANDS.get(index.value, [])
        missing = [b for b in required if b not in bands]

        if missing:
            reason = (
                f"Missing bands for {index.value}: {missing}. "
                f"Available: {list(bands.keys())}"
            )
            return False, reason

        for band_name in required:
            arr = bands[band_name]
            if arr is None or arr.size == 0:
                return False, f"Band {band_name} is None or empty"

            finite_count = int(np.sum(np.isfinite(arr)))
            if finite_count == 0:
                return False, f"Band {band_name} has no finite values"

            nonzero = int(np.sum(arr[np.isfinite(arr)] != 0))
            if nonzero == 0:
                return False, f"Band {band_name} is all zeros"

        return True, "OK"

    # ── Index Computation ─────────────────────────────────────

    @staticmethod
    def compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        """
        Normalized Difference Vegetation Index.
        NDVI = (NIR - Red) / (NIR + Red)
        Bands: B04 (Red), B08 (NIR)   Range: -1 to +1
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            nir_f = nir.astype(np.float64)
            red_f = red.astype(np.float64)
            denom = nir_f + red_f
            ndvi = np.where(
                denom != 0,
                (nir_f - red_f) / denom,
                0.0,
            )
            ndvi = np.where(np.isfinite(ndvi), ndvi, 0.0)
        return np.clip(ndvi, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def compute_evi(
        red: np.ndarray,
        nir: np.ndarray,
        blue: np.ndarray,
        gain: float = 2.5,
        c1: float = 6.0,
        c2: float = 7.5,
        soil_l: float = 1.0,
    ) -> np.ndarray:
        """
        Enhanced Vegetation Index — reduces atmospheric and soil noise.
        EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)
        Bands: B02 (Blue), B04 (Red), B08 (NIR)
        """
        nir_f = nir.astype(np.float64)
        red_f = red.astype(np.float64)
        blue_f = blue.astype(np.float64)
        denom = nir_f + c1 * red_f - c2 * blue_f + soil_l
        with np.errstate(divide="ignore", invalid="ignore"):
            evi = np.where(
                denom != 0,
                gain * (nir_f - red_f) / denom,
                0.0,
            )
            evi = np.where(np.isfinite(evi), evi, 0.0)
        return np.clip(evi, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def compute_savi(
        red: np.ndarray, nir: np.ndarray, soil_l: float = 0.5,
    ) -> np.ndarray:
        """
        Soil-Adjusted Vegetation Index — useful for sparse vegetation (Sahel).
        SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)
        Bands: B04 (Red), B08 (NIR)
        """
        nir_f = nir.astype(np.float64)
        red_f = red.astype(np.float64)
        denom = nir_f + red_f + soil_l
        with np.errstate(divide="ignore", invalid="ignore"):
            savi = np.where(
                denom != 0,
                ((nir_f - red_f) / denom) * (1.0 + soil_l),
                0.0,
            )
            savi = np.where(np.isfinite(savi), savi, 0.0)
        return np.clip(savi, -1.5, 1.5).astype(np.float32)

    @staticmethod
    def compute_nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
        """
        Normalized Burn Ratio — detects burn scars and fire damage.
        NBR = (NIR - SWIR2) / (NIR + SWIR2)
        Bands: B08 (NIR), B12 (SWIR2)
        """
        nir_f = nir.astype(np.float64)
        swir_f = swir2.astype(np.float64)
        denom = nir_f + swir_f
        with np.errstate(divide="ignore", invalid="ignore"):
            nbr = np.where(
                denom != 0,
                (nir_f - swir_f) / denom,
                0.0,
            )
            nbr = np.where(np.isfinite(nbr), nbr, 0.0)
        return np.clip(nbr, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def compute_ndmi(nir: np.ndarray, swir1: np.ndarray) -> np.ndarray:
        """
        Normalized Difference Moisture Index — vegetation water content.
        NDMI = (NIR - SWIR1) / (NIR + SWIR1)
        Bands: B08 (NIR), B11 (SWIR1)
        """
        nir_f = nir.astype(np.float64)
        swir_f = swir1.astype(np.float64)
        denom = nir_f + swir_f
        with np.errstate(divide="ignore", invalid="ignore"):
            ndmi = np.where(
                denom != 0,
                (nir_f - swir_f) / denom,
                0.0,
            )
            ndmi = np.where(np.isfinite(ndmi), ndmi, 0.0)
        return np.clip(ndmi, -1.0, 1.0).astype(np.float32)

    def compute_index(
        self, bands: Dict[str, np.ndarray], index: VegetationIndex,
    ) -> np.ndarray:
        """Dispatch to the appropriate index computation with validation."""
        # Validate required bands exist
        valid, reason = self.validate_bands(bands, index)
        if not valid:
            print(f"[VEG] ✗ Band validation failed for {index.value}: {reason}")
            raise ValueError(
                f"Cannot compute {index.value}: {reason}"
            )

        dispatch = {
            VegetationIndex.NDVI: lambda: self.compute_ndvi(
                bands["B04"], bands["B08"],
            ),
            VegetationIndex.EVI: lambda: self.compute_evi(
                bands["B04"], bands["B08"], bands["B02"],
            ),
            VegetationIndex.SAVI: lambda: self.compute_savi(
                bands["B04"], bands["B08"],
            ),
            VegetationIndex.NBR: lambda: self.compute_nbr(
                bands["B08"], bands["B12"],
            ),
            VegetationIndex.NDMI: lambda: self.compute_ndmi(
                bands["B08"], bands["B11"],
            ),
        }

        fn = dispatch.get(index)
        if fn is None:
            raise ValueError(f"Unsupported index: {index}")

        result = fn()

        # Quick diagnostic
        finite_count = int(np.sum(np.isfinite(result)))
        nonzero = int(np.sum(result[np.isfinite(result)] != 0)) if finite_count > 0 else 0
        print(
            f"[VEG]   {index.value} computed: "
            f"range=[{np.nanmin(result):.4f}, {np.nanmax(result):.4f}], "
            f"mean={np.nanmean(result):.4f}, "
            f"finite={finite_count}/{result.size}, "
            f"nonzero={nonzero}"
        )

        return result

    # ── Cloud Masking ─────────────────────────────────────────

    @staticmethod
    def create_cloud_mask(
        scl: np.ndarray,
        invalid_classes: Optional[Set[int]] = None,
    ) -> np.ndarray:
        """
        Create a boolean cloud mask from the Sentinel-2 Scene Classification
        Layer (SCL).

        Default masked (True = invalid):
          0 = No data, 1 = Saturated/defective, 3 = Cloud shadow,
          8 = Cloud medium prob, 9 = Cloud high prob, 10 = Thin cirrus

        Can be called with a custom set of invalid classes.
        """
        if invalid_classes is None:
            invalid_classes = SCL_INVALID_STRICT
        return np.isin(scl.astype(int), list(invalid_classes))

    @staticmethod
    def apply_mask(
        data: np.ndarray,
        mask: np.ndarray,
        fill_value: float = np.nan,
    ) -> np.ndarray:
        """Apply a boolean mask, setting invalid pixels to fill_value."""
        result = data.copy().astype(np.float32)
        result[mask] = fill_value
        return result

    def _smart_cloud_mask(
        self,
        scl: np.ndarray,
        label: str = "",
    ) -> Tuple[np.ndarray, str]:
        """
        Create a cloud mask with automatic relaxation.

        If strict masking (classes 0,1,3,8,9,10) removes >95% of pixels,
        fall back to relaxed masking (classes 0,1,9 only).

        If relaxed masking STILL removes >95%, disable masking entirely.

        Returns (mask_array, mode_string).
        """
        total_pixels = scl.size
        if total_pixels == 0:
            return np.zeros(scl.shape, dtype=bool), "none"

        # Check if SCL is entirely one class (likely no-data)
        unique_classes = np.unique(scl)
        if len(unique_classes) == 1 and unique_classes[0] == 0:
            print(
                f"[VEG] ⚠ {label}: SCL is entirely class 0 (no data) "
                f"— disabling cloud mask"
            )
            return np.zeros(scl.shape, dtype=bool), "none"

        # Try strict mask first
        strict_mask = self.create_cloud_mask(scl, SCL_INVALID_STRICT)
        strict_invalid = float(np.sum(strict_mask)) / total_pixels

        if strict_invalid <= CLOUD_MASK_MAX_FRACTION:
            valid_pct = (1.0 - strict_invalid) * 100
            print(
                f"[VEG]   {label}: Strict cloud mask OK — "
                f"{valid_pct:.1f}% valid pixels"
            )
            return strict_mask, "strict"

        # Strict mask too aggressive — try relaxed
        print(
            f"[VEG] ⚠ {label}: Strict mask removes "
            f"{strict_invalid * 100:.1f}% of pixels — trying relaxed mask"
        )

        relaxed_mask = self.create_cloud_mask(scl, SCL_INVALID_RELAXED)
        relaxed_invalid = float(np.sum(relaxed_mask)) / total_pixels

        if relaxed_invalid <= CLOUD_MASK_MAX_FRACTION:
            valid_pct = (1.0 - relaxed_invalid) * 100
            print(
                f"[VEG]   {label}: Relaxed cloud mask OK — "
                f"{valid_pct:.1f}% valid pixels"
            )
            return relaxed_mask, "relaxed"

        # Even relaxed mask is too aggressive — disable
        print(
            f"[VEG] ⚠ {label}: Even relaxed mask removes "
            f"{relaxed_invalid * 100:.1f}% — disabling cloud mask entirely"
        )
        return np.zeros(scl.shape, dtype=bool), "none"

    # ── Snapshot Statistics ────────────────────────────────────

    def compute_snapshot(
        self,
        bands: Dict[str, np.ndarray],
        date: str,
        bbox: List[float],
        index: VegetationIndex = VegetationIndex.NDVI,
    ) -> VegetationSnapshot:
        """Compute vegetation index statistics for a single date."""
        print(f"[VEG] Computing snapshot: date={date}, index={index.value}")

        # Validate bands
        valid, reason = self.validate_bands(bands, index)
        if not valid:
            print(f"[VEG] ✗ Cannot compute snapshot: {reason}")
            return VegetationSnapshot(
                date=date, bbox=bbox, index_name=index.value,
                mean=0.0, median=0.0, std=0.0,
                min_val=0.0, max_val=0.0,
                valid_pixels=0,
                total_pixels=0,
                cloud_fraction=1.0,
                mask_mode="failed",
            )

        index_array = self.compute_index(bands, index)

        cloud_fraction = 0.0
        mask_mode = "none"

        if "SCL" in bands:
            cloud_mask, mask_mode = self._smart_cloud_mask(
                bands["SCL"], label=f"snapshot-{date}",
            )
            cloud_fraction = float(np.sum(cloud_mask)) / max(
                cloud_mask.size, 1,
            )
            index_array = self.apply_mask(index_array, cloud_mask)
        else:
            print(f"[VEG]   No SCL band available — skipping cloud mask")

        valid = index_array[np.isfinite(index_array)]

        if len(valid) == 0:
            print(
                f"[VEG] ⚠ No valid pixels for date {date} "
                f"(cloud_fraction={cloud_fraction:.2%}, mask_mode={mask_mode})"
            )
            logger.warning("No valid pixels for date %s", date)
            return VegetationSnapshot(
                date=date, bbox=bbox, index_name=index.value,
                mean=0.0, median=0.0, std=0.0,
                min_val=0.0, max_val=0.0,
                valid_pixels=0,
                total_pixels=int(index_array.size),
                cloud_fraction=cloud_fraction,
                mask_mode=mask_mode,
            )

        hist, _ = np.histogram(valid, bins=20, range=(-1.0, 1.0))

        mean_val = float(np.mean(valid))
        median_val = float(np.median(valid))

        print(
            f"[VEG] ✓ Snapshot {date}: {index.value}="
            f"mean={mean_val:.4f}, median={median_val:.4f}, "
            f"valid={len(valid)}/{index_array.size} "
            f"({100.0 * len(valid) / max(index_array.size, 1):.1f}%), "
            f"cloud={cloud_fraction:.1%}, mask={mask_mode}"
        )

        return VegetationSnapshot(
            date=date, bbox=bbox, index_name=index.value,
            mean=mean_val,
            median=median_val,
            std=float(np.std(valid)),
            min_val=float(np.min(valid)),
            max_val=float(np.max(valid)),
            valid_pixels=int(len(valid)),
            total_pixels=int(index_array.size),
            cloud_fraction=cloud_fraction,
            histogram=hist.tolist(),
            mask_mode=mask_mode,
        )

    # ── Change Detection ──────────────────────────────────────

    def detect_changes(
        self,
        bands_before: Dict[str, np.ndarray],
        bands_after: Dict[str, np.ndarray],
        date_before: str,
        date_after: str,
        bbox: List[float],
        index: VegetationIndex = VegetationIndex.NDVI,
        min_area_pixels: Optional[int] = None,
    ) -> List[ChangeEvent]:
        """
        Detect vegetation change events between two temporal scenes.
        Computes difference image (after − before) and identifies contiguous
        regions of significant vegetation loss or gain.
        """
        if min_area_pixels is None:
            min_area_pixels = MIN_CLEARING_PIXELS

        print(
            f"[VEG] Detecting changes: {date_before} → {date_after}, "
            f"index={index.value}, zone={self.zone}"
        )

        # Validate bands for both dates
        for label, bands in [
            ("before", bands_before),
            ("after", bands_after),
        ]:
            valid, reason = self.validate_bands(bands, index)
            if not valid:
                print(f"[VEG] ✗ Band validation failed ({label}): {reason}")
                raise ValueError(
                    f"Cannot detect changes — {label} bands invalid: {reason}"
                )

        idx_before = self.compute_index(bands_before, index)
        idx_after = self.compute_index(bands_after, index)

        # Combined cloud masking with smart relaxation
        combined_mask = np.zeros(idx_before.shape, dtype=bool)
        mask_mode = "none"

        if "SCL" in bands_before:
            mask_b, mode_b = self._smart_cloud_mask(
                bands_before["SCL"], label=f"change-before-{date_before}",
            )
            combined_mask |= mask_b
            mask_mode = mode_b

        if "SCL" in bands_after:
            mask_a, mode_a = self._smart_cloud_mask(
                bands_after["SCL"], label=f"change-after-{date_after}",
            )
            combined_mask |= mask_a
            # Use the more permissive mode
            if mode_a == "none" or mask_mode == "none":
                mask_mode = "none"
            elif mode_a == "relaxed" or mask_mode == "relaxed":
                mask_mode = "relaxed"

        cloud_pct = float(np.sum(combined_mask)) / max(
            combined_mask.size, 1,
        )
        print(
            f"[VEG]   Combined cloud mask: "
            f"{cloud_pct:.1%} masked, mode={mask_mode}"
        )

        idx_before = self.apply_mask(idx_before, combined_mask)
        idx_after = self.apply_mask(idx_after, combined_mask)

        diff = idx_after - idx_before

        # Check we have enough valid difference pixels
        valid_diff = np.sum(np.isfinite(diff))
        total_pixels = diff.size
        valid_frac = valid_diff / max(total_pixels, 1)

        print(
            f"[VEG]   Difference image: "
            f"valid={valid_diff}/{total_pixels} ({valid_frac:.1%}), "
            f"range=[{np.nanmin(diff):.4f}, {np.nanmax(diff):.4f}], "
            f"mean={np.nanmean(diff):.4f}"
        )

        if valid_frac < 0.05:
            print(
                f"[VEG] ⚠ Less than 5% valid pixels in difference image "
                f"— change detection may be unreliable"
            )
            logger.warning(
                "Only %.1f%% valid pixels in change detection for %s→%s",
                valid_frac * 100, date_before, date_after,
            )

        clearing_threshold = self.thresholds["clearing_drop_threshold"]
        regrowth_threshold = self.thresholds["regrowth_rise_threshold"]

        clearing_mask = diff < clearing_threshold
        regrowth_mask = diff > regrowth_threshold

        clearing_count = int(np.sum(clearing_mask & np.isfinite(diff)))
        regrowth_count = int(np.sum(regrowth_mask & np.isfinite(diff)))
        print(
            f"[VEG]   Thresholds: clearing<{clearing_threshold}, "
            f"regrowth>{regrowth_threshold}"
        )
        print(
            f"[VEG]   Flagged pixels: "
            f"clearing={clearing_count}, regrowth={regrowth_count}"
        )

        events: List[ChangeEvent] = []

        events.extend(self._extract_change_regions(
            diff, clearing_mask, "clearing", bbox,
            date_before, date_after, index, min_area_pixels,
        ))

        events.extend(self._extract_change_regions(
            diff, regrowth_mask, "regrowth", bbox,
            date_before, date_after, index, min_area_pixels,
        ))

        # Burn scar cross-check using NBR if SWIR bands available
        if (
            "B12" in bands_before
            and "B12" in bands_after
            and "B08" in bands_before
            and "B08" in bands_after
        ):
            print("[VEG]   Computing burn scar check (NBR)...")
            nbr_before = self.compute_nbr(
                bands_before["B08"], bands_before["B12"],
            )
            nbr_after = self.compute_nbr(
                bands_after["B08"], bands_after["B12"],
            )
            nbr_before = self.apply_mask(nbr_before, combined_mask)
            nbr_after = self.apply_mask(nbr_after, combined_mask)
            nbr_diff = nbr_after - nbr_before
            burn_mask = nbr_diff < -0.27
            burn_count = int(np.sum(burn_mask & np.isfinite(nbr_diff)))
            print(f"[VEG]   Burn scar pixels: {burn_count}")

            burn_events = self._extract_change_regions(
                nbr_diff, burn_mask, "burn_scar", bbox,
                date_before, date_after, VegetationIndex.NBR,
                min_area_pixels,
            )
            events.extend(burn_events)

        # Summary
        by_type: Dict[str, int] = {}
        for e in events:
            by_type[e.classification] = by_type.get(e.classification, 0) + 1

        print(
            f"[VEG] ✓ Detected {len(events)} change events "
            f"between {date_before} and {date_after}: {by_type}"
        )
        logger.info(
            "Detected %d change events between %s and %s: %s",
            len(events), date_before, date_after, by_type,
        )
        return events

    # ── Region Extraction ─────────────────────────────────────

    def _extract_change_regions(
        self,
        diff: np.ndarray,
        mask: np.ndarray,
        classification: str,
        bbox: List[float],
        date_before: str,
        date_after: str,
        index: VegetationIndex,
        min_area_pixels: int,
    ) -> List[ChangeEvent]:
        """Label connected components and extract change events."""
        try:
            from scipy.ndimage import label as scipy_label
            return self._extract_with_scipy(
                diff, mask, classification, bbox,
                date_before, date_after, index, min_area_pixels,
                scipy_label,
            )
        except ImportError:
            logger.warning(
                "scipy not available — using simple pixel counting."
            )
            return self._extract_change_simple(
                diff, mask, classification, bbox,
                date_before, date_after, index, min_area_pixels,
            )

    def _extract_with_scipy(
        self,
        diff: np.ndarray,
        mask: np.ndarray,
        classification: str,
        bbox: List[float],
        date_before: str,
        date_after: str,
        index: VegetationIndex,
        min_area_pixels: int,
        scipy_label,
    ) -> List[ChangeEvent]:
        valid_mask = mask & np.isfinite(diff)
        labeled, num_features = scipy_label(valid_mask)

        events: List[ChangeEvent] = []
        west, south, east, north = bbox
        h, w = diff.shape
        if h == 0 or w == 0:
            return events

        pixel_lat_m = (north - south) / h * 111_000
        cos_lat = np.cos(np.radians((north + south) / 2))
        pixel_lon_m = (east - west) / w * 111_000 * cos_lat
        pixel_area_ha = (pixel_lat_m * pixel_lon_m) / 10_000

        regions_checked = 0
        regions_too_small = 0

        for region_id in range(1, num_features + 1):
            region_mask = labeled == region_id
            area_pixels = int(np.sum(region_mask))
            regions_checked += 1

            if area_pixels < min_area_pixels:
                regions_too_small += 1
                continue

            region_values = diff[region_mask & np.isfinite(diff)]
            if len(region_values) == 0:
                continue

            rows, cols = np.where(region_mask)
            centroid_row = float(np.mean(rows))
            centroid_col = float(np.mean(cols))
            lat = north - (centroid_row / h) * (north - south)
            lon = west + (centroid_col / w) * (east - west)

            row_min, row_max = int(np.min(rows)), int(np.max(rows))
            col_min, col_max = int(np.min(cols)), int(np.max(cols))
            region_bbox = [
                west + (col_min / w) * (east - west),
                north - (row_max / h) * (north - south),
                west + (col_max / w) * (east - west),
                north - (row_min / h) * (north - south),
            ]

            mean_change = float(np.mean(region_values))
            max_change = (
                float(np.min(region_values))
                if classification != "regrowth"
                else float(np.max(region_values))
            )
            area_ha = area_pixels * pixel_area_ha
            severity = self._classify_severity(
                mean_change, area_ha, classification,
            )
            confidence = self._estimate_confidence(
                area_pixels, mean_change, classification,
            )

            event_id = (
                f"{classification}_{date_after}_{lat:.4f}_{lon:.4f}"
            ).replace("-", "").replace(".", "")

            events.append(ChangeEvent(
                event_id=event_id,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                bbox=region_bbox,
                date_before=date_before,
                date_after=date_after,
                index_used=index.value,
                mean_change=round(mean_change, 4),
                max_change=round(max_change, 4),
                area_pixels=area_pixels,
                area_hectares=round(area_ha, 2),
                severity=severity,
                classification=classification,
                confidence=round(confidence, 2),
                vegetation_zone=self.zone,
            ))

        if regions_checked > 0:
            print(
                f"[VEG]   {classification}: {num_features} regions found, "
                f"{regions_too_small} too small (<{min_area_pixels}px), "
                f"{len(events)} events kept"
            )

        return events

    def _extract_change_simple(
        self,
        diff: np.ndarray,
        mask: np.ndarray,
        classification: str,
        bbox: List[float],
        date_before: str,
        date_after: str,
        index: VegetationIndex,
        min_area_pixels: int,
    ) -> List[ChangeEvent]:
        """Fallback: treat entire masked region as one event."""
        valid_mask = mask & np.isfinite(diff)
        area_pixels = int(np.sum(valid_mask))
        if area_pixels < min_area_pixels:
            print(
                f"[VEG]   {classification} (simple): "
                f"{area_pixels}px < {min_area_pixels}px threshold — skipped"
            )
            return []

        region_values = diff[valid_mask]
        west, south, east, north = bbox
        h, w = diff.shape
        if h == 0 or w == 0:
            return []

        rows, cols = np.where(valid_mask)
        lat = north - (float(np.mean(rows)) / h) * (north - south)
        lon = west + (float(np.mean(cols)) / w) * (east - west)

        pixel_lat_m = (north - south) / h * 111_000
        cos_lat = np.cos(np.radians((north + south) / 2))
        pixel_lon_m = (east - west) / w * 111_000 * cos_lat
        area_ha = area_pixels * (pixel_lat_m * pixel_lon_m) / 10_000

        mean_change = float(np.mean(region_values))
        max_change = (
            float(np.min(region_values))
            if classification != "regrowth"
            else float(np.max(region_values))
        )
        severity = self._classify_severity(
            mean_change, area_ha, classification,
        )
        confidence = self._estimate_confidence(
            area_pixels, mean_change, classification,
        )

        event_id = (
            f"{classification}_{date_after}_{lat:.4f}_{lon:.4f}"
        ).replace("-", "").replace(".", "")

        print(
            f"[VEG]   {classification} (simple): "
            f"{area_pixels}px, {area_ha:.2f}ha, "
            f"severity={severity}"
        )

        return [ChangeEvent(
            event_id=event_id,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            bbox=bbox,
            date_before=date_before,
            date_after=date_after,
            index_used=index.value,
            mean_change=round(mean_change, 4),
            max_change=round(max_change, 4),
            area_pixels=area_pixels,
            area_hectares=round(area_ha, 2),
            severity=severity,
            classification=classification,
            confidence=round(confidence, 2),
            vegetation_zone=self.zone,
        )]

    # ── Severity & Confidence ─────────────────────────────────

    def _classify_severity(
        self, mean_change: float, area_ha: float, classification: str,
    ) -> str:
        if classification == "regrowth":
            return AlertSeverity.LOW.value
        abs_change = abs(mean_change)
        if abs_change > 0.40 and area_ha > 5.0:
            return AlertSeverity.CRITICAL.value
        elif abs_change > 0.30 or area_ha > 3.0:
            return AlertSeverity.HIGH.value
        elif abs_change > 0.20 or area_ha > 1.0:
            return AlertSeverity.MODERATE.value
        return AlertSeverity.LOW.value

    def _estimate_confidence(
        self,
        area_pixels: int,
        mean_change: float,
        classification: str,
    ) -> float:
        area_factor = min(area_pixels / 100.0, 1.0)
        signal_factor = min(abs(mean_change) / 0.5, 1.0)
        type_bonus = 0.1 if classification == "burn_scar" else 0.0
        confidence = (
            0.3 * area_factor
            + 0.5 * signal_factor
            + 0.2
            + type_bonus
        )
        return min(confidence, 0.99)