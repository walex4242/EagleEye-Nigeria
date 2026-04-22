"""
setup_training_data.py
───────────────────────
Sets up the training data directory structure and generates
improved synthetic satellite imagery for the CampDetector model.

Key improvements:
  - More realistic textures and patterns
  - Better class separation (harder negatives, subtler positives)
  - Edge cases (partial clearings, mixed scenes)
  - More diverse color palettes matching real satellite imagery

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

from __future__ import annotations

import math
import os
import sys
import json
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

PILLOW_AVAILABLE = False

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    PILLOW_AVAILABLE = True
except ImportError:
    pass

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

DATA_DIR = Path(__file__).parent / "data"
TRAIN_DIR = DATA_DIR / "train"
VAL_DIR = DATA_DIR / "val"

CLASSES = ["legal_activity", "suspicious_encampment"]

PATCH_SIZE = 224


def create_directory_structure() -> None:
    """Create the required folder structure."""
    for split_dir in [TRAIN_DIR, VAL_DIR]:
        for cls in CLASSES:
            (split_dir / cls).mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created: {split_dir / cls}")


# ═══════════════════════════════════════════════════════
# TEXTURE GENERATION HELPERS
# ═══════════════════════════════════════════════════════

def _perlin_noise_simple(
    size: int, scale: float = 30.0
) -> np.ndarray:
    """
    Generate simple pseudo-Perlin noise for natural-looking textures.
    Returns array of shape (size, size) with values in [0, 1].
    """
    # Resolve BILINEAR across Pillow versions
    # Pillow >= 9.1 moved it to Image.Resampling.BILINEAR
    _resampling = getattr(Image, "Resampling", None)
    if _resampling is not None:
        bilinear = getattr(_resampling, "BILINEAR", None)
    else:
        bilinear = None
    if bilinear is None:
        bilinear = getattr(Image, "BILINEAR", 2)

    noise = np.zeros((size, size), dtype=np.float32)

    for octave in range(4):
        freq = 2 ** octave
        amp = 0.5 ** octave
        dim_size = max(2, size // max(1, int(scale / freq)))
        base = np.random.rand(dim_size, dim_size).astype(np.float32)

        # Simple bilinear upsample
        base_img = Image.fromarray(
            (base * 255).astype(np.uint8), mode="L"
        )
        upsampled = base_img.resize((size, size), bilinear)
        layer = np.array(upsampled).astype(np.float32) / 255.0
        noise += layer * amp

    # Normalize to [0, 1]
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-8)
    return noise


def _add_vegetation_texture(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    base_color: tuple[int, int, int],
    density: float = 0.7,
) -> Image.Image:
    """Add realistic vegetation texture to an image region."""
    arr = np.array(img).astype(np.float32)
    noise = _perlin_noise_simple(PATCH_SIZE, scale=20.0)

    for c in range(3):
        variation = (noise - 0.5) * 40 * density
        arr[:, :, c] = np.clip(arr[:, :, c] + variation, 0, 255)

    # Add individual tree-like dots
    num_dots = int(300 * density)
    for _ in range(num_dots):
        x = random.randint(0, PATCH_SIZE - 1)
        y = random.randint(0, PATCH_SIZE - 1)
        r = max(0, min(255, base_color[0] + random.randint(-25, 25)))
        g = max(0, min(255, base_color[1] + random.randint(-25, 25)))
        b = max(0, min(255, base_color[2] + random.randint(-15, 15)))
        dot_size = random.randint(2, 7)
        draw.ellipse(
            [x, y, x + dot_size, y + dot_size],
            fill=(r, g, b),
        )

    return Image.fromarray(arr.astype(np.uint8))


# ═══════════════════════════════════════════════════════
# LEGAL ACTIVITY IMAGE GENERATION
# ═══════════════════════════════════════════════════════

def generate_synthetic_legal(index: int, output_dir: Path) -> None:
    """
    Generate a synthetic 'legal_activity' image with improved realism.

    Simulates:
    - Regular farm plot grids with seasonal color variation
    - Organized village layouts with uniform building patterns
    - Straight roads and infrastructure
    - Cleared fields with regular boundaries
    - Market areas and organized settlements
    """
    img = Image.new("RGB", (PATCH_SIZE, PATCH_SIZE))
    draw = ImageDraw.Draw(img)

    scene_type = random.choice([
        "farmland", "village", "cleared_field",
        "mixed_farm_village", "large_farm", "urban_edge",
    ])

    # Background palette (realistic satellite tones)
    bg_palettes = {
        "farmland": [
            (85, 107, 47), (107, 142, 35), (120, 130, 60),
            (90, 110, 50), (100, 120, 55),
        ],
        "village": [
            (160, 140, 100), (150, 135, 95), (170, 150, 110),
            (140, 125, 90), (155, 140, 105),
        ],
        "cleared_field": [
            (139, 119, 101), (150, 130, 100), (160, 140, 110),
            (130, 115, 90), (145, 125, 100),
        ],
        "mixed_farm_village": [
            (100, 115, 60), (110, 120, 65), (95, 110, 55),
        ],
        "large_farm": [
            (75, 100, 40), (80, 105, 45), (85, 110, 50),
        ],
        "urban_edge": [
            (165, 155, 140), (170, 160, 145), (160, 150, 135),
        ],
    }

    bg_color = random.choice(bg_palettes.get(scene_type, bg_palettes["farmland"]))
    draw.rectangle([0, 0, PATCH_SIZE, PATCH_SIZE], fill=bg_color)

    # Add natural texture
    img = _add_vegetation_texture(draw, img, bg_color, density=0.3)
    draw = ImageDraw.Draw(img)

    if scene_type in ("farmland", "large_farm", "mixed_farm_village"):
        # Regular farm plot grid
        plot_size = random.randint(25, 65)
        plot_colors = [
            (max(0, min(255, bg_color[0] + random.randint(-30, 30))),
             max(0, min(255, bg_color[1] + random.randint(-30, 30))),
             max(0, min(255, bg_color[2] + random.randint(-15, 15))))
            for _ in range(8)
        ]

        for x in range(0, PATCH_SIZE, plot_size):
            for y in range(0, PATCH_SIZE, plot_size):
                color = random.choice(plot_colors)
                # Plots have sharp, regular boundaries
                border = random.randint(1, 3)
                draw.rectangle(
                    [x + border, y + border,
                     x + plot_size - border, y + plot_size - border],
                    fill=color,
                )

                # Add crop row lines within plots
                if random.random() > 0.4:
                    row_spacing = random.randint(4, 8)
                    row_color = (
                        max(0, min(255, color[0] + random.randint(-10, 10))),
                        max(0, min(255, color[1] + random.randint(5, 15))),
                        max(0, min(255, color[2] + random.randint(-5, 5))),
                    )
                    if random.random() > 0.5:
                        # Horizontal rows
                        for ry in range(y + border, y + plot_size - border, row_spacing):
                            draw.line(
                                [(x + border, ry),
                                 (x + plot_size - border, ry)],
                                fill=row_color, width=1,
                            )
                    else:
                        # Vertical rows
                        for rx in range(x + border, x + plot_size - border, row_spacing):
                            draw.line(
                                [(rx, y + border),
                                 (rx, y + plot_size - border)],
                                fill=row_color, width=1,
                            )

    if scene_type in ("village", "mixed_farm_village", "urban_edge"):
        # Organized buildings in clusters
        num_clusters = random.randint(1, 3)
        for _ in range(num_clusters):
            cx = random.randint(30, PATCH_SIZE - 30)
            cy = random.randint(30, PATCH_SIZE - 30)
            num_buildings = random.randint(5, 15)

            # Buildings arranged in grid-like pattern
            building_spacing = random.randint(12, 20)
            cols = random.randint(2, 5)

            for b in range(num_buildings):
                bx = cx + (b % cols) * building_spacing + random.randint(-2, 2)
                by = cy + (b // cols) * building_spacing + random.randint(-2, 2)
                bw = random.randint(6, 14)
                bh = random.randint(6, 14)

                # Building colors (rooftops — metallic/concrete)
                building_color = random.choice([
                    (190, 180, 165), (200, 195, 180), (180, 170, 155),
                    (170, 160, 145), (210, 200, 185), (185, 175, 160),
                ])

                # Regular rectangular buildings (key legal indicator)
                draw.rectangle(
                    [bx, by, bx + bw, by + bh],
                    fill=building_color,
                    outline=(
                        max(0, building_color[0] - 20),
                        max(0, building_color[1] - 20),
                        max(0, building_color[2] - 20),
                    ),
                    width=1,
                )

    # Add roads (straight, organized — key legal indicator)
    num_roads = random.randint(1, 4)
    for _ in range(num_roads):
        road_width = random.randint(2, 5)
        road_color = random.choice([
            (180, 160, 130), (170, 155, 125), (190, 170, 140),
            (175, 160, 135),
        ])
        if random.random() > 0.5:
            # Horizontal road
            y = random.randint(0, PATCH_SIZE)
            draw.line(
                [(0, y), (PATCH_SIZE, y)],
                fill=road_color, width=road_width,
            )
        else:
            # Vertical road
            x = random.randint(0, PATCH_SIZE)
            draw.line(
                [(x, 0), (x, PATCH_SIZE)],
                fill=road_color, width=road_width,
            )

    # Post-processing for realism
    img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.5, 1.2)))

    # Brightness/contrast variation (simulates different times of day)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(random.uniform(0.85, 1.15))
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(random.uniform(0.9, 1.1))

    # Add sensor noise
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, random.uniform(3, 8), arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    img.save(output_dir / f"legal_{index:04d}.png")


# ═══════════════════════════════════════════════════════
# SUSPICIOUS ENCAMPMENT IMAGE GENERATION
# ═══════════════════════════════════════════════════════

def generate_synthetic_suspicious(index: int, output_dir: Path) -> None:
    """
    Generate a synthetic 'suspicious_encampment' image with improved realism.

    Simulates:
    - Irregular clearing in dense vegetation
    - Scattered non-uniform structures (tents, shelters)
    - No organized roads (only dirt tracks)
    - Fire pits and heat sources
    - Camouflage patterns (partially hidden under canopy)
    - Vehicle tracks leading to hidden clearings
    """
    img = Image.new("RGB", (PATCH_SIZE, PATCH_SIZE))
    draw = ImageDraw.Draw(img)

    camp_type = random.choice([
        "forest_clearing", "hidden_camp", "idp_camp",
        "creek_camp", "deep_forest", "edge_camp",
    ])

    # Dense vegetation backgrounds
    bg_palettes = {
        "forest_clearing": [
            (20, 60, 20), (25, 65, 22), (22, 58, 18),
        ],
        "hidden_camp": [
            (18, 55, 18), (20, 50, 15), (15, 48, 15),
        ],
        "idp_camp": [
            (30, 70, 30), (35, 75, 32), (28, 65, 25),
        ],
        "creek_camp": [
            (25, 60, 30), (22, 55, 28), (28, 62, 32),
        ],
        "deep_forest": [
            (12, 45, 12), (15, 50, 15), (10, 40, 10),
        ],
        "edge_camp": [
            (30, 70, 25), (35, 75, 30), (25, 65, 22),
        ],
    }

    bg_color = random.choice(
        bg_palettes.get(camp_type, bg_palettes["forest_clearing"])
    )
    draw.rectangle([0, 0, PATCH_SIZE, PATCH_SIZE], fill=bg_color)

    # Dense canopy texture
    img = _add_vegetation_texture(draw, img, bg_color, density=0.9)
    draw = ImageDraw.Draw(img)

    # Additional canopy detail
    for _ in range(800):
        x = random.randint(0, PATCH_SIZE - 1)
        y = random.randint(0, PATCH_SIZE - 1)
        r = max(0, min(255, bg_color[0] + random.randint(-18, 18)))
        g = max(0, min(255, bg_color[1] + random.randint(-18, 18)))
        b = max(0, min(255, bg_color[2] + random.randint(-12, 12)))
        dot_size = random.randint(3, 8)
        draw.ellipse(
            [x, y, x + dot_size, y + dot_size],
            fill=(r, g, b),
        )

    # Irregular clearing (the camp area)
    cx = random.randint(55, PATCH_SIZE - 55)
    cy = random.randint(55, PATCH_SIZE - 55)
    clearing_radius = random.randint(20, 55)

    # Generate irregular polygon for clearing
    num_points = random.randint(8, 16)
    points: list[tuple[int, int]] = []
    for i in range(num_points):
        angle = (360 / num_points) * i + random.uniform(-15, 15)
        radius = clearing_radius + random.randint(-18, 18)
        px = cx + int(radius * math.cos(math.radians(angle)))
        py = cy + int(radius * math.sin(math.radians(angle)))
        points.append((
            max(0, min(PATCH_SIZE - 1, px)),
            max(0, min(PATCH_SIZE - 1, py)),
        ))

    if len(points) >= 3:
        clearing_color = random.choice([
            (100, 90, 70), (110, 95, 72), (95, 85, 65),
            (120, 100, 75), (105, 92, 68), (115, 98, 73),
        ])
        draw.polygon(points, fill=clearing_color)

        # Add ground texture within clearing
        clear_arr = np.array(img).astype(np.float32)
        noise = _perlin_noise_simple(PATCH_SIZE, scale=15.0)
        # Apply noise only in clearing region (approximate with bounding box)
        min_x = max(0, cx - clearing_radius)
        max_x = min(PATCH_SIZE, cx + clearing_radius)
        min_y = max(0, cy - clearing_radius)
        max_y = min(PATCH_SIZE, cy + clearing_radius)
        clear_arr[min_y:max_y, min_x:max_x, :] += (
            (noise[min_y:max_y, min_x:max_x, np.newaxis] - 0.5) * 20
        )
        clear_arr = np.clip(clear_arr, 0, 255).astype(np.uint8)
        img = Image.fromarray(clear_arr)
        draw = ImageDraw.Draw(img)

    # Scattered irregular structures (tents, shelters)
    num_structures = random.randint(4, 14)
    for _ in range(num_structures):
        # Structures cluster near clearing center
        angle = random.uniform(0, 360)
        dist = random.uniform(0, clearing_radius * 0.85)
        sx = cx + int(dist * math.cos(math.radians(angle)))
        sy = cy + int(dist * math.sin(math.radians(angle)))

        # Clamp to image bounds
        sx = max(5, min(PATCH_SIZE - 5, sx))
        sy = max(5, min(PATCH_SIZE - 5, sy))

        struct_type = random.choice([
            "circle", "irregular", "triangle", "tarp", "lean_to",
        ])
        struct_color = random.choice([
            (80, 75, 65), (60, 55, 50), (140, 130, 110),
            (100, 95, 85), (70, 65, 55), (120, 110, 95),
            (90, 85, 75), (110, 100, 88),
        ])

        if struct_type == "circle":
            sr = random.randint(3, 9)
            draw.ellipse(
                [sx - sr, sy - sr, sx + sr, sy + sr],
                fill=struct_color,
            )
        elif struct_type == "triangle":
            tri_size = random.randint(5, 14)
            rot = random.uniform(0, 360)
            pts = []
            for i in range(3):
                a = rot + i * 120
                px = sx + int(tri_size * math.cos(math.radians(a)))
                py = sy + int(tri_size * math.sin(math.radians(a)))
                pts.append((px, py))
            draw.polygon(pts, fill=struct_color)
        elif struct_type == "tarp":
            # Rectangular but at random angle
            tw = random.randint(6, 16)
            th = random.randint(4, 10)
            rot = random.uniform(0, 360)
            pts = []
            for dx, dy in [(-tw//2, -th//2), (tw//2, -th//2),
                           (tw//2, th//2), (-tw//2, th//2)]:
                a = math.radians(rot)
                px = sx + int(dx * math.cos(a) - dy * math.sin(a))
                py = sy + int(dx * math.sin(a) + dy * math.cos(a))
                pts.append((px, py))
            draw.polygon(pts, fill=struct_color)
        elif struct_type == "lean_to":
            # Irregular shape suggesting makeshift shelter
            pts = [
                (sx + random.randint(-10, 0), sy + random.randint(-5, 0)),
                (sx + random.randint(5, 12), sy + random.randint(-8, -2)),
                (sx + random.randint(3, 10), sy + random.randint(3, 8)),
            ]
            draw.polygon(pts, fill=struct_color)
        else:
            # Irregular quadrilateral
            pts_list: list[tuple[int, int]] = [
                (sx + random.randint(-9, 9), sy + random.randint(-9, 9))
                for _ in range(4)
            ]
            draw.polygon(pts_list, fill=struct_color)

    # Irregular dirt tracks (not roads)
    num_paths = random.randint(1, 4)
    for _ in range(num_paths):
        path_points: list[tuple[int, int]] = [(cx, cy)]
        for _ in range(random.randint(4, 8)):
            last = path_points[-1]
            next_pt = (
                max(0, min(PATCH_SIZE - 1,
                    last[0] + random.randint(-35, 35))),
                max(0, min(PATCH_SIZE - 1,
                    last[1] + random.randint(-35, 35))),
            )
            path_points.append(next_pt)

        path_color = (
            random.randint(95, 120),
            random.randint(80, 100),
            random.randint(60, 80),
        )
        for i in range(len(path_points) - 1):
            draw.line(
                [path_points[i], path_points[i + 1]],
                fill=path_color,
                width=random.randint(1, 2),
            )

    # Fire pits (heat sources)
    num_fires = random.randint(1, 3)
    for _ in range(num_fires):
        if random.random() > 0.25:
            fx = cx + random.randint(-clearing_radius // 2,
                                      clearing_radius // 2)
            fy = cy + random.randint(-clearing_radius // 2,
                                      clearing_radius // 2)
            fx = max(5, min(PATCH_SIZE - 5, fx))
            fy = max(5, min(PATCH_SIZE - 5, fy))

            # Inner glow
            draw.ellipse(
                [fx - 3, fy - 3, fx + 3, fy + 3],
                fill=(random.randint(180, 220),
                      random.randint(80, 120),
                      random.randint(30, 60)),
            )
            # Outer glow
            draw.ellipse(
                [fx - 6, fy - 6, fx + 6, fy + 6],
                outline=(random.randint(140, 170),
                         random.randint(70, 100),
                         random.randint(30, 50)),
                width=1,
            )
            # Ash/char ring
            draw.ellipse(
                [fx - 8, fy - 8, fx + 8, fy + 8],
                outline=(50, 45, 40),
                width=1,
            )

    # Vehicle tracks (two parallel lines, slightly curved)
    if random.random() > 0.5:
        track_start_x = random.choice([0, PATCH_SIZE - 1])
        track_start_y = random.randint(0, PATCH_SIZE - 1)
        track_points = [(track_start_x, track_start_y)]
        for _ in range(6):
            last = track_points[-1]
            dx = 30 if track_start_x == 0 else -30
            next_p = (
                max(0, min(PATCH_SIZE - 1,
                    last[0] + dx + random.randint(-10, 10))),
                max(0, min(PATCH_SIZE - 1,
                    last[1] + random.randint(-15, 15))),
            )
            track_points.append(next_p)

        track_color = (100, 88, 70)
        for i in range(len(track_points) - 1):
            # Two parallel lines
            draw.line(
                [track_points[i], track_points[i + 1]],
                fill=track_color, width=1,
            )
            offset_pts = (
                (track_points[i][0], track_points[i][1] + 3),
                (track_points[i + 1][0], track_points[i + 1][1] + 3),
            )
            draw.line(offset_pts, fill=track_color, width=1)

    # Partial canopy cover (structures partially hidden)
    if camp_type in ("hidden_camp", "deep_forest"):
        for _ in range(random.randint(10, 25)):
            ox = cx + random.randint(-clearing_radius, clearing_radius)
            oy = cy + random.randint(-clearing_radius, clearing_radius)
            cover_size = random.randint(8, 20)
            canopy_color = (
                max(0, min(255, bg_color[0] + random.randint(-10, 10))),
                max(0, min(255, bg_color[1] + random.randint(-10, 10))),
                max(0, min(255, bg_color[2] + random.randint(-8, 8))),
            )
            draw.ellipse(
                [ox, oy, ox + cover_size, oy + cover_size],
                fill=canopy_color,
            )

    # Post-processing
    img = img.filter(
        ImageFilter.GaussianBlur(radius=random.uniform(0.4, 0.9))
    )

    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(random.uniform(0.85, 1.1))
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(random.uniform(0.9, 1.1))

    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, random.uniform(4, 10), arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    img.save(output_dir / f"suspicious_{index:04d}.png")


# ═══════════════════════════════════════════════════════
# DATASET GENERATION
# ═══════════════════════════════════════════════════════

def generate_dataset(num_train: int = 500, num_val: int = 100) -> None:
    """
    Generate the full synthetic training dataset.

    Increased from 200/50 to 500/100 per class for better generalization.
    """
    print(
        f"\n  Generating {num_train} training + {num_val} "
        f"validation images per class..."
    )

    random.seed(42)
    np.random.seed(42)

    for i in range(num_train):
        generate_synthetic_legal(i, TRAIN_DIR / "legal_activity")
        generate_synthetic_suspicious(i, TRAIN_DIR / "suspicious_encampment")
        if (i + 1) % 100 == 0:
            print(f"    Training: {i + 1}/{num_train} per class")

    # Use different seed for validation to ensure no overlap
    random.seed(9999)
    np.random.seed(9999)

    for i in range(num_val):
        generate_synthetic_legal(num_train + i, VAL_DIR / "legal_activity")
        generate_synthetic_suspicious(
            num_train + i, VAL_DIR / "suspicious_encampment"
        )

    print(f"  ✓ Generated {num_train * 2} training images")
    print(f"  ✓ Generated {num_val * 2} validation images")


def print_dataset_stats() -> None:
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
                count = (
                    len(list(cls_dir.glob("*.png")))
                    + len(list(cls_dir.glob("*.jpg")))
                )
                print(f"    {split}/{cls}: {count} images")
            else:
                print(f"    {split}/{cls}: NOT FOUND")


def main() -> None:
    """Entry point for training data setup."""
    print("=" * 60)
    print("  EagleEye-Nigeria — ML Training Data Setup v2")
    print("=" * 60)

    if not PILLOW_AVAILABLE:
        print("\n  ❌ Pillow and NumPy are required.")
        print("  Run: pip install Pillow numpy")
        sys.exit(1)

    print("\n  Step 1: Creating directory structure...")
    create_directory_structure()

    existing_train = sum(
        len(list((TRAIN_DIR / cls).glob("*.*")))
        for cls in CLASSES
        if (TRAIN_DIR / cls).exists()
    )

    if existing_train > 0:
        print(f"\n  Found {existing_train} existing training images.")
        response = input(
            "  Regenerate synthetic data? (y/N): "
        ).strip().lower()
        if response != "y":
            print("  Keeping existing data.")
            print_dataset_stats()
            return

    print("\n  Step 2: Generating improved synthetic satellite imagery...")
    print("  ⚠️  These are SYNTHETIC images for initial model testing.")
    print("  For production, replace with real satellite patches.")
    print("  Generating 500 train + 100 val per class (was 200/50)...")

    generate_dataset(num_train=500, num_val=100)

    metadata: dict[str, Any] = {
        "created": str(Path(os.path.abspath(__file__))),
        "classes": CLASSES,
        "train_per_class": 500,
        "val_per_class": 100,
        "image_size": PATCH_SIZE,
        "type": "synthetic_v2",
        "improvements": [
            "Perlin noise textures",
            "Multiple scene types per class",
            "Realistic color palettes",
            "Crop row patterns",
            "Partial canopy cover",
            "Vehicle tracks",
            "Fire pits with glow",
            "Building outlines",
            "Sensor noise simulation",
            "Brightness/contrast variation",
        ],
        "note": "Replace with real satellite imagery for production use.",
    }

    with open(DATA_DIR / "dataset_info.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print_dataset_stats()

    print(f"\n  ✓ Dataset ready at: {DATA_DIR}")
    print("\n  Next steps:")
    print("    1. python -m ml.train          ← Train the model")
    print("    2. Replace synthetic images with real satellite patches")
    print("    3. Re-train for production accuracy")
    print("=" * 60)


if __name__ == "__main__":
    main()