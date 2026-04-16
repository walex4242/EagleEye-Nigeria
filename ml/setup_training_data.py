"""
setup_training_data.py
───────────────────────
Sets up the training data directory structure and downloads
sample satellite imagery for the CampDetector model.

Creates:
    ml/data/
        train/
            legal_activity/
            suspicious_encampment/
        val/
            legal_activity/
            suspicious_encampment/

Run: python -m ml.setup_training_data
"""

import os
import sys
import json
import random
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

DATA_DIR = Path(__file__).parent / "data"
TRAIN_DIR = DATA_DIR / "train"
VAL_DIR = DATA_DIR / "val"

CLASSES = ["legal_activity", "suspicious_encampment"]

# Image size for training patches
PATCH_SIZE = 224


def create_directory_structure():
    """Create the required folder structure."""
    for split_dir in [TRAIN_DIR, VAL_DIR]:
        for cls in CLASSES:
            (split_dir / cls).mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created: {split_dir / cls}")


def generate_synthetic_legal(index: int, output_dir: Path):
    """
    Generate a synthetic 'legal_activity' image.
    Simulates farmland, villages, cleared fields with:
    - Regular rectangular patterns (farm plots)
    - Uniform colors (green/brown)
    - Organized road patterns
    """
    img = Image.new("RGB", (PATCH_SIZE, PATCH_SIZE))
    draw = ImageDraw.Draw(img)

    # Background: earth/vegetation tones
    bg_color = random.choice([
        (34, 85, 34),    # Dark green (forest)
        (85, 107, 47),   # Olive (farmland)
        (139, 119, 101), # Brown (dry soil)
        (107, 142, 35),  # Yellow-green (crops)
        (160, 140, 100), # Sandy (cleared)
    ])
    draw.rectangle([0, 0, PATCH_SIZE, PATCH_SIZE], fill=bg_color)

    # Add regular farm plot grid (characteristic of legal activity)
    plot_size = random.randint(30, 60)
    for x in range(0, PATCH_SIZE, plot_size):
        for y in range(0, PATCH_SIZE, plot_size):
            # Slight color variation per plot
            r = bg_color[0] + random.randint(-20, 20)
            g = bg_color[1] + random.randint(-20, 20)
            b = bg_color[2] + random.randint(-10, 10)
            r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            draw.rectangle([x+1, y+1, x+plot_size-1, y+plot_size-1], fill=(r, g, b))

    # Add roads (straight lines — organized infrastructure)
    num_roads = random.randint(1, 3)
    for _ in range(num_roads):
        if random.random() > 0.5:
            y = random.randint(0, PATCH_SIZE)
            draw.line([(0, y), (PATCH_SIZE, y)], fill=(180, 160, 130), width=random.randint(2, 4))
        else:
            x = random.randint(0, PATCH_SIZE)
            draw.line([(x, 0), (x, PATCH_SIZE)], fill=(180, 160, 130), width=random.randint(2, 4))

    # Add some buildings (regular rectangles — village)
    if random.random() > 0.5:
        num_buildings = random.randint(3, 8)
        cluster_x = random.randint(40, PATCH_SIZE - 60)
        cluster_y = random.randint(40, PATCH_SIZE - 60)
        for _ in range(num_buildings):
            bx = cluster_x + random.randint(-30, 30)
            by = cluster_y + random.randint(-30, 30)
            bw = random.randint(6, 12)
            bh = random.randint(6, 12)
            draw.rectangle([bx, by, bx+bw, by+bh], fill=(200, 190, 170))

    # Apply slight blur for realism
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))

    # Add noise
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, 5, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    img.save(output_dir / f"legal_{index:04d}.png")


def generate_synthetic_suspicious(index: int, output_dir: Path):
    """
    Generate a synthetic 'suspicious_encampment' image.
    Simulates hidden camps with:
    - Irregular clearing in dense vegetation
    - Scattered non-uniform structures
    - No organized roads
    - Tent-like shapes
    """
    img = Image.new("RGB", (PATCH_SIZE, PATCH_SIZE))
    draw = ImageDraw.Draw(img)

    # Dense forest background
    bg_color = random.choice([
        (20, 60, 20),   # Deep forest
        (25, 70, 25),   # Dark canopy
        (30, 55, 20),   # Dense vegetation
    ])
    draw.rectangle([0, 0, PATCH_SIZE, PATCH_SIZE], fill=bg_color)

    # Add canopy texture
    for _ in range(500):
        x = random.randint(0, PATCH_SIZE - 1)
        y = random.randint(0, PATCH_SIZE - 1)
        r = bg_color[0] + random.randint(-15, 15)
        g = bg_color[1] + random.randint(-15, 15)
        b = bg_color[2] + random.randint(-10, 10)
        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        size = random.randint(2, 6)
        draw.ellipse([x, y, x+size, y+size], fill=(r, g, b))

    # Irregular clearing (the camp area)
    cx = random.randint(60, PATCH_SIZE - 60)
    cy = random.randint(60, PATCH_SIZE - 60)
    clearing_radius = random.randint(25, 50)

    # Draw clearing as irregular polygon
    points = []
    for angle in range(0, 360, random.randint(20, 40)):
        import math
        r = clearing_radius + random.randint(-15, 15)
        px = cx + int(r * math.cos(math.radians(angle)))
        py = cy + int(r * math.sin(math.radians(angle)))
        points.append((px, py))

    if len(points) >= 3:
        clearing_color = random.choice([
            (100, 90, 70),    # Bare earth
            (120, 100, 75),   # Trampled ground
            (90, 80, 60),     # Dirt
        ])
        draw.polygon(points, fill=clearing_color)

    # Scattered irregular structures (tents, makeshift shelters)
    num_structures = random.randint(3, 10)
    for _ in range(num_structures):
        sx = cx + random.randint(-clearing_radius, clearing_radius)
        sy = cy + random.randint(-clearing_radius, clearing_radius)

        struct_type = random.choice(["circle", "irregular", "triangle"])
        struct_color = random.choice([
            (80, 75, 65),     # Tarp
            (60, 55, 50),     # Dark shelter
            (140, 130, 110),  # Light tent
            (100, 95, 85),    # Canvas
        ])

        if struct_type == "circle":
            r = random.randint(3, 8)
            draw.ellipse([sx-r, sy-r, sx+r, sy+r], fill=struct_color)
        elif struct_type == "triangle":
            size = random.randint(5, 12)
            draw.polygon([
                (sx, sy - size),
                (sx - size, sy + size),
                (sx + size, sy + size),
            ], fill=struct_color)
        else:
            # Irregular quadrilateral
            pts = [(sx + random.randint(-8, 8), sy + random.randint(-8, 8)) for _ in range(4)]
            draw.polygon(pts, fill=struct_color)

    # Irregular paths (not roads — dirt tracks)
    num_paths = random.randint(1, 3)
    for _ in range(num_paths):
        path_points = [(cx, cy)]
        for _ in range(random.randint(3, 6)):
            last = path_points[-1]
            next_pt = (
                last[0] + random.randint(-30, 30),
                last[1] + random.randint(-30, 30),
            )
            path_points.append(next_pt)
        for i in range(len(path_points) - 1):
            draw.line([path_points[i], path_points[i+1]], fill=(110, 95, 75), width=1)

    # Fire pit (heat source)
    if random.random() > 0.3:
        fx = cx + random.randint(-15, 15)
        fy = cy + random.randint(-15, 15)
        draw.ellipse([fx-3, fy-3, fx+3, fy+3], fill=(200, 100, 50))
        draw.ellipse([fx-5, fy-5, fx+5, fy+5], outline=(150, 80, 40), width=1)

    # Apply slight blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    # Add noise
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, 8, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    img.save(output_dir / f"suspicious_{index:04d}.png")


def generate_dataset(num_train: int = 200, num_val: int = 50):
    """Generate the full synthetic training dataset."""
    print(f"\n  Generating {num_train} training + {num_val} validation images per class...")

    for i in range(num_train):
        generate_synthetic_legal(i, TRAIN_DIR / "legal_activity")
        generate_synthetic_suspicious(i, TRAIN_DIR / "suspicious_encampment")
        if (i + 1) % 50 == 0:
            print(f"    Training: {i+1}/{num_train} per class")

    for i in range(num_val):
        generate_synthetic_legal(num_train + i, VAL_DIR / "legal_activity")
        generate_synthetic_suspicious(num_train + i, VAL_DIR / "suspicious_encampment")

    print(f"  ✓ Generated {num_train * 2} training images")
    print(f"  ✓ Generated {num_val * 2} validation images")


def print_dataset_stats():
    """Print stats about the current dataset."""
    print("\n  Dataset structure:")
    for split in ["train", "val"]:
        split_dir = DATA_DIR / split
        if not split_dir.exists():
            print(f"    {split}/: NOT FOUND")
            continue
        for cls in CLASSES:
            cls_dir = split_dir / cls
            if cls_dir.exists():
                count = len(list(cls_dir.glob("*.png"))) + len(list(cls_dir.glob("*.jpg")))
                print(f"    {split}/{cls}: {count} images")
            else:
                print(f"    {split}/{cls}: NOT FOUND")


def main():
    print("=" * 60)
    print("  EagleEye-Nigeria — ML Training Data Setup")
    print("=" * 60)

    if not PILLOW_AVAILABLE:
        print("\n  ❌ Pillow and NumPy are required.")
        print("  Run: pip install Pillow numpy")
        sys.exit(1)

    # Step 1: Create directories
    print("\n  Step 1: Creating directory structure...")
    create_directory_structure()

    # Step 2: Check for existing data
    existing_train = sum(
        len(list((TRAIN_DIR / cls).glob("*.*")))
        for cls in CLASSES
        if (TRAIN_DIR / cls).exists()
    )

    if existing_train > 0:
        print(f"\n  Found {existing_train} existing training images.")
        response = input("  Regenerate synthetic data? (y/N): ").strip().lower()
        if response != "y":
            print("  Keeping existing data.")
            print_dataset_stats()
            return

    # Step 3: Generate synthetic data
    print("\n  Step 2: Generating synthetic satellite imagery...")
    print("  ⚠️  These are SYNTHETIC images for initial model testing.")
    print("  For production, replace with real satellite patches.")

    generate_dataset(num_train=200, num_val=50)

    # Step 4: Create dataset metadata
    metadata = {
        "created": str(Path(os.path.abspath(__file__))),
        "classes": CLASSES,
        "train_per_class": 200,
        "val_per_class": 50,
        "image_size": PATCH_SIZE,
        "type": "synthetic",
        "note": "Replace with real satellite imagery for production use.",
    }

    with open(DATA_DIR / "dataset_info.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Step 5: Print stats
    print_dataset_stats()

    print(f"\n  ✓ Dataset ready at: {DATA_DIR}")
    print(f"\n  Next steps:")
    print(f"    1. python -m ml.train          ← Train the model")
    print(f"    2. Replace synthetic images with real satellite patches")
    print(f"    3. Re-train for production accuracy")
    print("=" * 60)


if __name__ == "__main__":
    main()