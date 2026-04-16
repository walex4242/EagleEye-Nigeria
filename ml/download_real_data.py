"""
download_real_data.py
──────────────────────
Downloads real satellite imagery from free sources for CampDetector training.

Sources:
  1. Sentinel-2 via Copernicus Browser (ESA) — 10m resolution optical
  2. Google Static Maps API — high-res aerial imagery
  3. Esri World Imagery — free satellite basemap tiles
  4. OpenAerialMap — crowd-sourced aerial imagery

Strategy:
  - legal_activity: Farm grids, villages, organized settlements in Nigeria
  - suspicious_encampment: Forest clearings, IDP camps, remote settlements

Run: python -m ml.download_real_data
"""

from __future__ import annotations
import os
import sys
import json
import time
import random
import hashlib
import requests
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
    import numpy as np
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

DATA_DIR = Path(__file__).parent / "data"
TRAIN_DIR = DATA_DIR / "train"
VAL_DIR = DATA_DIR / "val"
RAW_DIR = DATA_DIR / "raw"

CLASSES = ["legal_activity", "suspicious_encampment"]
PATCH_SIZE = 224

# ════════════════════════════════════════════════════════════
# COORDINATE SETS FOR NIGERIA
# ════════════════════════════════════════════════════════════

# Legal activity locations:
# Known farmland, villages, organized settlements, markets
LEGAL_LOCATIONS = [
    # ── Major farmland areas ──
    {"lat": 12.0000, "lon": 8.5167, "label": "Kano farmland", "zoom": 16},
    {"lat": 12.0500, "lon": 8.4800, "label": "Kano irrigated farms", "zoom": 17},
    {"lat": 11.7500, "lon": 8.5000, "label": "Kano south farms", "zoom": 16},
    {"lat": 10.2833, "lon": 9.6833, "label": "Bauchi farmland", "zoom": 16},
    {"lat": 10.3100, "lon": 9.7200, "label": "Bauchi irrigated", "zoom": 17},
    {"lat": 9.0600, "lon": 7.4900, "label": "FCT Abuja suburbs", "zoom": 16},
    {"lat": 9.0200, "lon": 7.5300, "label": "Abuja farmland", "zoom": 16},
    {"lat": 7.3775, "lon": 3.9470, "label": "Ibadan farmland", "zoom": 16},
    {"lat": 7.4000, "lon": 3.9100, "label": "Ibadan outskirts", "zoom": 17},
    {"lat": 9.9000, "lon": 8.8800, "label": "Jos plateau farms", "zoom": 16},
    {"lat": 9.9500, "lon": 8.9200, "label": "Jos south farming", "zoom": 16},
    {"lat": 7.7200, "lon": 4.5500, "label": "Osun farmland", "zoom": 16},
    {"lat": 8.5000, "lon": 4.5500, "label": "Kwara farms", "zoom": 16},
    {"lat": 6.4500, "lon": 3.4000, "label": "Lagos mainland", "zoom": 17},
    {"lat": 6.5200, "lon": 3.3700, "label": "Lagos Ikeja area", "zoom": 17},
    {"lat": 11.1000, "lon": 7.7000, "label": "Kaduna farmland", "zoom": 16},
    {"lat": 11.0500, "lon": 7.7500, "label": "Kaduna south", "zoom": 16},
    # ── Organized villages ──
    {"lat": 12.4300, "lon": 6.2500, "label": "Zamfara village", "zoom": 17},
    {"lat": 10.5200, "lon": 7.4300, "label": "Kaduna village", "zoom": 17},
    {"lat": 11.5000, "lon": 8.0000, "label": "Katsina village", "zoom": 17},
    {"lat": 8.9000, "lon": 7.0000, "label": "Niger state village", "zoom": 17},
    {"lat": 7.5000, "lon": 4.0000, "label": "Oyo village", "zoom": 17},
    {"lat": 6.8000, "lon": 3.2000, "label": "Ogun village", "zoom": 17},
    {"lat": 10.0000, "lon": 9.0000, "label": "Plateau village", "zoom": 17},
    {"lat": 7.8000, "lon": 6.7000, "label": "Kogi village", "zoom": 17},
    # ── Large-scale farms ──
    {"lat": 11.9500, "lon": 8.4500, "label": "Kano large farm", "zoom": 15},
    {"lat": 10.1000, "lon": 9.5000, "label": "Bauchi large farm", "zoom": 15},
    {"lat": 9.5000, "lon": 6.0000, "label": "Niger large farm", "zoom": 15},
    {"lat": 8.0000, "lon": 4.0000, "label": "Kwara large farm", "zoom": 15},
    # ── Markets / urban ──
    {"lat": 9.0579, "lon": 7.4951, "label": "Abuja central", "zoom": 17},
    {"lat": 6.4541, "lon": 3.3947, "label": "Lagos Island", "zoom": 17},
    {"lat": 11.9964, "lon": 8.5167, "label": "Kano city center", "zoom": 17},
    {"lat": 7.3876, "lon": 3.8930, "label": "Ibadan center", "zoom": 17},
]

# Suspicious encampment locations:
# Known conflict areas, IDP camps, remote forest clearings,
# areas with documented bandit/insurgent activity
SUSPICIOUS_LOCATIONS = [
    # ── Sambisa Forest / Boko Haram areas ──
    {"lat": 11.2000, "lon": 13.5000, "label": "Sambisa Forest edge", "zoom": 16},
    {"lat": 11.1500, "lon": 13.4500, "label": "Sambisa clearing", "zoom": 17},
    {"lat": 11.3000, "lon": 13.6000, "label": "Sambisa deep", "zoom": 16},
    {"lat": 11.1000, "lon": 13.3000, "label": "Sambisa south", "zoom": 17},
    {"lat": 11.2500, "lon": 13.5500, "label": "Sambisa central", "zoom": 16},
    {"lat": 10.8000, "lon": 13.2000, "label": "Borno forest south", "zoom": 16},
    {"lat": 10.9000, "lon": 13.1000, "label": "Borno forest clearing", "zoom": 17},
    # ── Lake Chad region ──
    {"lat": 13.0000, "lon": 13.5000, "label": "Lake Chad islands", "zoom": 16},
    {"lat": 13.1000, "lon": 13.4000, "label": "Lake Chad marshes", "zoom": 16},
    {"lat": 12.8000, "lon": 13.6000, "label": "Lake Chad south", "zoom": 17},
    # ── Northwest bandit corridors ──
    {"lat": 12.5000, "lon": 6.5000, "label": "Zamfara forest", "zoom": 16},
    {"lat": 12.3000, "lon": 6.3000, "label": "Zamfara clearing", "zoom": 17},
    {"lat": 12.4000, "lon": 6.8000, "label": "Zamfara remote", "zoom": 16},
    {"lat": 12.6000, "lon": 6.0000, "label": "Zamfara deep forest", "zoom": 17},
    {"lat": 11.8000, "lon": 5.5000, "label": "Kebbi forest", "zoom": 16},
    {"lat": 12.2000, "lon": 5.8000, "label": "Kebbi/Zamfara border", "zoom": 16},
    # ── Kaduna-Zamfara forest corridor ──
    {"lat": 11.5000, "lon": 7.0000, "label": "Kaduna forest north", "zoom": 16},
    {"lat": 11.3000, "lon": 7.2000, "label": "Birnin Gwari forest", "zoom": 17},
    {"lat": 11.4000, "lon": 7.1000, "label": "Kaduna bandit zone", "zoom": 16},
    # ── IDP camp areas ──
    {"lat": 11.8500, "lon": 13.1600, "label": "Maiduguri IDP area", "zoom": 17},
    {"lat": 11.8300, "lon": 13.1400, "label": "Maiduguri camp zone", "zoom": 17},
    {"lat": 10.2900, "lon": 9.8500, "label": "Bauchi IDP", "zoom": 17},
    {"lat": 12.0000, "lon": 8.5500, "label": "Kano IDP outskirts", "zoom": 17},
    # ── Remote forest clearings ──
    {"lat": 11.0000, "lon": 12.0000, "label": "Yobe forest", "zoom": 16},
    {"lat": 10.5000, "lon": 12.5000, "label": "Gombe forest", "zoom": 16},
    {"lat": 8.5000, "lon": 11.0000, "label": "Taraba forest", "zoom": 16},
    {"lat": 7.5000, "lon": 9.0000, "label": "Benue forest", "zoom": 16},
    # ── Niger Delta (militancy) ──
    {"lat": 4.8000, "lon": 6.0000, "label": "Niger Delta creeks", "zoom": 16},
    {"lat": 4.7000, "lon": 6.2000, "label": "Bayelsa creeks", "zoom": 17},
    {"lat": 5.0000, "lon": 5.8000, "label": "Delta creeks", "zoom": 16},
    # ── Additional suspicious areas ──
    {"lat": 13.2000, "lon": 5.5000, "label": "Sokoto forest", "zoom": 16},
    {"lat": 12.8000, "lon": 7.0000, "label": "Katsina forest", "zoom": 16},
    {"lat": 10.3000, "lon": 11.5000, "label": "Adamawa forest", "zoom": 16},
]


# ════════════════════════════════════════════════════════════
# TILE DOWNLOAD ENGINE
# ════════════════════════════════════════════════════════════

def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to tile coordinates at given zoom level."""
    import math
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def download_esri_tile(lat: float, lon: float, zoom: int = 17, size: int = PATCH_SIZE) -> Image.Image | None:
    """
    Download a satellite tile from Esri World Imagery.
    Free, no API key required, good resolution.
    """
    x, y = _lat_lon_to_tile(lat, lon, zoom)

    # Download a 3x3 grid of tiles and crop the center
    tiles = []
    for dy in range(-1, 2):
        row = []
        for dx in range(-1, 2):
            url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y + dy}/{x + dx}"
            try:
                resp = requests.get(url, timeout=15, headers={
                    "User-Agent": "EagleEye-Nigeria/0.3 (satellite-research)",
                    "Referer": "https://www.arcgis.com/",
                })
                if resp.status_code == 200 and len(resp.content) > 1000:
                    tile = Image.open(BytesIO(resp.content)).convert("RGB")
                    row.append(tile)
                else:
                    return None
            except Exception:
                return None
        tiles.append(row)

    # Stitch tiles (each tile is 256x256)
    tile_size = 256
    stitched = Image.new("RGB", (tile_size * 3, tile_size * 3))
    for row_idx, row in enumerate(tiles):
        for col_idx, tile in enumerate(row):
            stitched.paste(tile.resize((tile_size, tile_size)), (col_idx * tile_size, row_idx * tile_size))

    # Crop center to desired size
    center_x = (tile_size * 3) // 2
    center_y = (tile_size * 3) // 2
    half = size // 2

    # Add some random offset for variety
    offset_x = random.randint(-80, 80)
    offset_y = random.randint(-80, 80)

    left = center_x - half + offset_x
    top = center_y - half + offset_y
    right = left + size
    bottom = top + size

    # Clamp
    left = max(0, left)
    top = max(0, top)
    right = min(tile_size * 3, right)
    bottom = min(tile_size * 3, bottom)

    crop = stitched.crop((left, top, right, bottom))

    # Ensure exact size
    if crop.size != (size, size):
        crop = crop.resize((size, size), Image.LANCZOS)

    return crop


def download_google_static(
    lat: float, lon: float, zoom: int = 17,
    size: int = PATCH_SIZE, api_key: str = ""
) -> Image.Image | None:
    """
    Download from Google Static Maps (requires API key).
    Falls back to Esri if no key available.
    """
    if not api_key:
        return None

    url = (
        f"https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat},{lon}&zoom={zoom}&size={size}x{size}"
        f"&maptype=satellite&key={api_key}"
    )

    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:
            return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception:
        pass
    return None


def _generate_augmented_variants(img: Image.Image, count: int = 4) -> list[Image.Image]:
    """Generate augmented variants of an image for dataset expansion."""
    from PIL import ImageEnhance, ImageFilter

    variants = []
    arr = np.array(img)

    for i in range(count):
        aug = img.copy()

        # Random horizontal flip
        if random.random() > 0.5:
            aug = aug.transpose(Image.FLIP_LEFT_RIGHT)

        # Random vertical flip
        if random.random() > 0.5:
            aug = aug.transpose(Image.FLIP_TOP_BOTTOM)

        # Random rotation (90-degree increments)
        rot = random.choice([0, 90, 180, 270])
        if rot > 0:
            aug = aug.rotate(rot)

        # Random brightness
        enhancer = ImageEnhance.Brightness(aug)
        aug = enhancer.enhance(random.uniform(0.8, 1.2))

        # Random contrast
        enhancer = ImageEnhance.Contrast(aug)
        aug = enhancer.enhance(random.uniform(0.8, 1.2))

        # Random slight blur (simulates different atmospheric conditions)
        if random.random() > 0.7:
            aug = aug.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.3, 0.8)))

        # Random noise
        if random.random() > 0.5:
            aug_arr = np.array(aug).astype(np.float32)
            noise = np.random.normal(0, random.uniform(2, 8), aug_arr.shape)
            aug_arr = np.clip(aug_arr + noise, 0, 255).astype(np.uint8)
            aug = Image.fromarray(aug_arr)

        # Ensure size
        if aug.size != (PATCH_SIZE, PATCH_SIZE):
            aug = aug.resize((PATCH_SIZE, PATCH_SIZE), Image.LANCZOS)

        variants.append(aug)

    return variants


def _image_hash(img: Image.Image) -> str:
    """Generate a hash to detect duplicate images."""
    small = img.resize((8, 8), Image.LANCZOS).convert("L")
    pixels = list(small.tobytes())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return hashlib.md5(bits.encode()).hexdigest()[:12]


def _is_valid_satellite_image(img: Image.Image) -> bool:
    """Check if the image looks like valid satellite imagery (not blank/error)."""
    arr = np.array(img)

    # Check if mostly one color (blank tile)
    std = np.std(arr)
    if std < 10:
        return False

    # Check if too dark (ocean/night)
    mean = np.mean(arr)
    if mean < 20:
        return False

    # Check if too bright (cloud cover)
    if mean > 240:
        return False

    return True


# ════════════════════════════════════════════════════════════
# MAIN DOWNLOAD PIPELINE
# ════════════════════════════════════════════════════════════

def download_dataset(
    augment_factor: int = 5,
    val_split: float = 0.2,
    max_retries: int = 3,
    delay: float = 0.5,
):
    """
    Download real satellite imagery and build the training dataset.

    Args:
        augment_factor: Number of augmented variants per original image.
        val_split: Fraction of images for validation.
        max_retries: Retries per download.
        delay: Delay between downloads (be polite to servers).
    """
    print("\n  ═══════════════════════════════════════════════════")
    print("  Downloading Real Satellite Imagery")
    print("  ═══════════════════════════════════════════════════")
    print(f"  Source: Esri World Imagery (free, no API key)")
    print(f"  Legal locations: {len(LEGAL_LOCATIONS)}")
    print(f"  Suspicious locations: {len(SUSPICIOUS_LOCATIONS)}")
    print(f"  Augmentation factor: {augment_factor}x")
    print()

    google_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # Create directories
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for split in [TRAIN_DIR, VAL_DIR]:
        for cls in CLASSES:
            (split / cls).mkdir(parents=True, exist_ok=True)

    seen_hashes: set[str] = set()
    stats = {"legal": {"downloaded": 0, "augmented": 0, "skipped": 0},
             "suspicious": {"downloaded": 0, "augmented": 0, "skipped": 0}}

    def download_and_save(locations, class_name, stats_key):
        images = []
        total = len(locations)

        for idx, loc in enumerate(locations):
            lat, lon, label, zoom = loc["lat"], loc["lon"], loc["label"], loc["zoom"]

            success = False
            for attempt in range(max_retries):
                # Try Google first, then Esri
                img = None
                if google_key:
                    img = download_google_static(lat, lon, zoom, PATCH_SIZE, google_key)

                if img is None:
                    img = download_esri_tile(lat, lon, zoom, PATCH_SIZE)

                if img is not None and _is_valid_satellite_image(img):
                    # Check for duplicates
                    h = _image_hash(img)
                    if h in seen_hashes:
                        stats[stats_key]["skipped"] += 1
                        break

                    seen_hashes.add(h)
                    images.append(img)
                    stats[stats_key]["downloaded"] += 1
                    success = True

                    # Also download nearby variants
                    for offset_idx in range(3):
                        offset_lat = lat + random.uniform(-0.005, 0.005)
                        offset_lon = lon + random.uniform(-0.005, 0.005)
                        nearby = download_esri_tile(offset_lat, offset_lon, zoom, PATCH_SIZE)
                        if nearby and _is_valid_satellite_image(nearby):
                            nh = _image_hash(nearby)
                            if nh not in seen_hashes:
                                seen_hashes.add(nh)
                                images.append(nearby)
                                stats[stats_key]["downloaded"] += 1
                        time.sleep(delay * 0.5)

                    break
                else:
                    time.sleep(delay)

            if (idx + 1) % 5 == 0 or idx == total - 1:
                print(f"    [{class_name}] {idx + 1}/{total} locations processed "
                      f"({stats[stats_key]['downloaded']} images)")

            time.sleep(delay)

        # Generate augmented variants
        print(f"    [{class_name}] Generating {augment_factor}x augmented variants...")
        augmented = []
        for img in images:
            variants = _generate_augmented_variants(img, count=augment_factor)
            augmented.extend(variants)
            stats[stats_key]["augmented"] += len(variants)

        all_images = images + augmented
        random.shuffle(all_images)

        # Split into train/val
        val_count = max(1, int(len(all_images) * val_split))
        val_images = all_images[:val_count]
        train_images = all_images[val_count:]

        # Save
        for i, img in enumerate(train_images):
            img.save(TRAIN_DIR / class_name / f"real_{class_name}_{i:04d}.png")

        for i, img in enumerate(val_images):
            img.save(VAL_DIR / class_name / f"real_{class_name}_{i:04d}.png")

        print(f"    [{class_name}] Saved: {len(train_images)} train, {len(val_images)} val")
        return len(train_images), len(val_images)

    # Download legal activity images
    print(f"\n  📥 Downloading legal_activity imagery...")
    legal_train, legal_val = download_and_save(
        LEGAL_LOCATIONS, "legal_activity", "legal"
    )

    # Download suspicious encampment images
    print(f"\n  📥 Downloading suspicious_encampment imagery...")
    susp_train, susp_val = download_and_save(
        SUSPICIOUS_LOCATIONS, "suspicious_encampment", "suspicious"
    )

    # Save metadata
    metadata = {
        "source": "Esri World Imagery + augmentation",
        "legal_locations": len(LEGAL_LOCATIONS),
        "suspicious_locations": len(SUSPICIOUS_LOCATIONS),
        "augment_factor": augment_factor,
        "stats": stats,
        "train": {"legal": legal_train, "suspicious": susp_train},
        "val": {"legal": legal_val, "suspicious": susp_val},
        "image_size": PATCH_SIZE,
        "type": "real_satellite",
    }

    with open(DATA_DIR / "real_dataset_info.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n  ═══════════════════════════════════════════════════")
    print(f"  ✅ Download Complete!")
    print(f"  ═══════════════════════════════════════════════════")
    print(f"  Legal:      {stats['legal']['downloaded']} originals + {stats['legal']['augmented']} augmented")
    print(f"  Suspicious: {stats['suspicious']['downloaded']} originals + {stats['suspicious']['augmented']} augmented")
    print(f"  Train set:  {legal_train} legal + {susp_train} suspicious")
    print(f"  Val set:    {legal_val} legal + {susp_val} suspicious")
    print(f"  Metadata:   {DATA_DIR / 'real_dataset_info.json'}")
    print(f"\n  Next: python -m ml.train")
    print(f"  ═══════════════════════════════════════════════════")


def print_current_stats():
    """Print current dataset statistics."""
    print("\n  Current dataset:")
    total = 0
    for split in ["train", "val"]:
        split_dir = DATA_DIR / split
        if not split_dir.exists():
            continue
        for cls in CLASSES:
            cls_dir = split_dir / cls
            if cls_dir.exists():
                png = len(list(cls_dir.glob("*.png")))
                jpg = len(list(cls_dir.glob("*.jpg")))
                count = png + jpg
                real = len(list(cls_dir.glob("real_*")))
                synth = count - real
                total += count
                print(f"    {split}/{cls}: {count} total ({real} real, {synth} synthetic)")

    print(f"    Total: {total} images")


def main():
    print("=" * 60)
    print("  EagleEye-Nigeria — Real Satellite Data Download")
    print("=" * 60)

    if not PILLOW_AVAILABLE:
        print("\n  ❌ Pillow and NumPy required: pip install Pillow numpy")
        sys.exit(1)

    print_current_stats()

    print("\n  This will download satellite tiles from Esri World Imagery.")
    print("  Estimated time: 10-20 minutes (depends on connection)")
    print("  Images will be augmented 5x for robust training.\n")

    response = input("  Continue? (Y/n): ").strip().lower()
    if response == "n":
        print("  Aborted.")
        return

    download_dataset(augment_factor=5, val_split=0.2, delay=0.3)

    print_current_stats()


if __name__ == "__main__":
    main()