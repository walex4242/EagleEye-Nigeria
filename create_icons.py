"""
create_icons.py — Generate PWA icons + favicons for EagleEye dashboard
Run: python create_icons.py
"""

import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    os.system("pip install Pillow")
    from PIL import Image, ImageDraw, ImageFont

ICONS_DIR = os.path.join("dashboard", "static", "icons")
os.makedirs(ICONS_DIR, exist_ok=True)

# PWA icons + favicon sizes
PWA_SIZES = [192, 512]
FAVICON_SIZES = [16, 32, 48]
BG_COLOR = (10, 22, 40)
FG_COLOR = (0, 230, 118)
ACCENT_COLOR = (255, 255, 255)


def create_icon(size):
    img = Image.new("RGBA", (size, size), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Draw circle background
    padding = size // 8
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=(22, 32, 64, 255),
        outline=FG_COLOR + (200,),
        width=max(2, size // 64),
    )

    # Draw eagle emoji text
    text = "EE"
    font_size = size // 3
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
            )
        except OSError:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2
    draw.text((x, y), text, fill=FG_COLOR + (255,), font=font)

    return img


def create_favicon_ico(images_dict):
    """Create multi-size .ico file from dict of {size: Image}"""
    ico_path = os.path.join(ICONS_DIR, "favicon.ico")
    
    # Use 32px as base, include 16 and 48
    sizes_for_ico = [16, 32, 48]
    ico_images = []
    
    for s in sizes_for_ico:
        if s in images_dict:
            ico_images.append(images_dict[s])
    
    if ico_images:
        ico_images[0].save(
            ico_path,
            format="ICO",
            sizes=[(s, s) for s in sizes_for_ico if s in images_dict],
            append_images=ico_images[1:],
        )
        print(f"  ✓ Created {ico_path} (multi-size ICO)")


def create_favicon_svg():
    """Create SVG favicon — eagle eye / radar theme"""
    svg_content = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <!-- Dark background -->
  <circle cx="64" cy="64" r="64" fill="#0a1628"/>
  
  <!-- Inner circle -->
  <circle cx="64" cy="64" r="52" fill="#162040" stroke="#00e676" stroke-width="1.5" opacity="0.8"/>
  
  <!-- Radar rings -->
  <circle cx="64" cy="64" r="40" fill="none" stroke="#00e676" stroke-width="0.5" opacity="0.2"/>
  <circle cx="64" cy="64" r="28" fill="none" stroke="#00e676" stroke-width="0.5" opacity="0.15"/>
  
  <!-- Eagle eye — outer ring -->
  <circle cx="64" cy="64" r="24" fill="none" stroke="#ff2d2d" stroke-width="2.5" opacity="0.85"/>
  
  <!-- Eagle eye — iris -->
  <circle cx="64" cy="64" r="13" fill="#ff2d2d" opacity="0.85"/>
  
  <!-- Eagle eye — pupil -->
  <circle cx="64" cy="64" r="6" fill="#0a1628"/>
  <circle cx="64" cy="64" r="2.5" fill="#ff2d2d"/>
  
  <!-- Crosshair lines -->
  <line x1="64" y1="16" x2="64" y2="36" stroke="#00e676" stroke-width="1.5" opacity="0.5"/>
  <line x1="64" y1="92" x2="64" y2="112" stroke="#00e676" stroke-width="1.5" opacity="0.5"/>
  <line x1="16" y1="64" x2="36" y2="64" stroke="#00e676" stroke-width="1.5" opacity="0.5"/>
  <line x1="92" y1="64" x2="112" y2="64" stroke="#00e676" stroke-width="1.5" opacity="0.5"/>
  
  <!-- Corner brackets -->
  <path d="M22,38 L22,22 L38,22" fill="none" stroke="#3b9eff" stroke-width="2" opacity="0.4"/>
  <path d="M90,22 L106,22 L106,38" fill="none" stroke="#3b9eff" stroke-width="2" opacity="0.4"/>
  <path d="M106,90 L106,106 L90,106" fill="none" stroke="#3b9eff" stroke-width="2" opacity="0.4"/>
  <path d="M38,106 L22,106 L22,90" fill="none" stroke="#3b9eff" stroke-width="2" opacity="0.4"/>
  
  <!-- Subtle "E" watermark -->
  <text x="64" y="72" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" 
        font-size="18" font-weight="bold" fill="#ffffff" opacity="0.08">E</text>
</svg>'''

    svg_path = os.path.join(ICONS_DIR, "favicon.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    print(f"  ✓ Created {svg_path} (SVG favicon)")


if __name__ == "__main__":
    print("[ICONS] Generating EagleEye icons...")
    print()

    # ── PWA Icons (192, 512) ──
    print("  PWA Icons:")
    for s in PWA_SIZES:
        img = create_icon(s)
        path = os.path.join(ICONS_DIR, f"icon-{s}.png")
        img.save(path, "PNG")
        print(f"  ✓ Created {path} ({s}x{s})")

    # ── Favicon PNGs (16, 32, 48) ──
    print()
    print("  Favicon PNGs:")
    favicon_images = {}
    for s in FAVICON_SIZES:
        img = create_icon(s)
        favicon_images[s] = img
        path = os.path.join(ICONS_DIR, f"favicon-{s}.png")
        img.save(path, "PNG")
        print(f"  ✓ Created {path} ({s}x{s})")

    # ── Multi-size ICO ──
    print()
    print("  Favicon ICO:")
    create_favicon_ico(favicon_images)

    # ── SVG Favicon ──
    print()
    print("  SVG Favicon:")
    create_favicon_svg()

    print()
    print("[ICONS] ✓ All icons generated!")
    print()
    print("  Add to your HTML <head>:")
    print('  <link rel="icon" type="image/svg+xml" href="/static/icons/favicon.svg" />')
    print('  <link rel="icon" type="image/png" sizes="32x32" href="/static/icons/favicon-32.png" />')
    print('  <link rel="icon" type="image/png" sizes="16x16" href="/static/icons/favicon-16.png" />')
    print('  <link rel="shortcut icon" href="/static/icons/favicon.ico" />')