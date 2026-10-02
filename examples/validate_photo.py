"""Reproduce box/hint selection on a real CC0 photograph, without internet at runtime."""

import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from magnetlabel.imaging import grabcut

ROOT = Path(__file__).resolve().parents[1]
RECT = [160, 10, 265, 310]
STROKES = [
    {"points": [[180, 190], [175, 260], [170, 305]], "radius": 8, "foreground": False},
    {"points": [[300, 305], [365, 305], [405, 245], [413, 195]], "radius": 10, "foreground": False},
    {"points": [[285, 210], [285, 260], [220, 280]], "radius": 10, "foreground": True},
    {"points": [[413, 78]], "radius": 9, "foreground": False},
    {"points": [[361, 270], [365, 285], [372, 300]], "radius": 10, "foreground": False},
]


def validate():
    image = cv2.imread(str(ROOT / "examples" / "coffee.png"))
    start = time.perf_counter()
    initial = grabcut(image, RECT, [])
    initial_seconds = time.perf_counter() - start
    start = time.perf_counter()
    refined = grabcut(image, RECT, STROKES)
    refined_seconds = time.perf_counter() - start
    # Point checks prove useful corrections, not accuracy against a full reference mask.
    assert initial[260, 285] == 0 and refined[260, 285] == 1  # Dark cup body recovered.
    assert initial[280, 365] == 1 and refined[280, 365] == 0  # Spoon bowl excluded.
    assert refined[130, 285] == 1 and refined[360, 500] == 0
    output = ROOT / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    panels = []
    for label, mask in [
        ("Approximate cup box", None),
        ("Initial assisted mask", initial),
        ("Mask after foreground/background hints", refined),
    ]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        if mask is not None:
            rgb = rgb.copy()
            rgb[mask > 0] = np.uint8(rgb[mask > 0] * 0.6 + np.array([180, 230, 100]) * 0.4)
        panel = Image.new("RGB", (600, 452), (20, 24, 22))
        panel.paste(Image.fromarray(rgb), (0, 52))
        draw = ImageDraw.Draw(panel)
        draw.text((20, 18), label, fill=(240, 245, 232), font_size=18)
        if mask is None:
            x, y, w, h = RECT
            draw.rectangle((x, y + 52, x + w, y + h + 52), outline=(200, 239, 128), width=3)
        panels.append(panel)
    comparison = Image.new("RGB", (1800, 452))
    for i, panel in enumerate(panels):
        comparison.paste(panel, (i * 600, 0))
    comparison.save(output / "real-photo-comparison.png")
    cv2.imwrite(str(output / "coffee-mask.png"), refined * 255)
    report = {
        "image": "coffee.png",
        "dimensions": [600, 400],
        "rect": RECT,
        "hint_strokes": len(STROKES),
        "initial_mask_pixels": int(initial.sum()),
        "refined_mask_pixels": int(refined.sum()),
        "initial_seconds": round(initial_seconds, 3),
        "refined_seconds": round(refined_seconds, 3),
        "checks": "cup body recovered; spoon center excluded",
        "ground_truth_available": False,
        "opencv": cv2.__version__,
    }
    (ROOT / "docs" / "real-photo-result.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    validate()
