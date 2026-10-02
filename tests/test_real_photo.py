from pathlib import Path

import cv2

from magnetlabel.imaging import grabcut


def test_real_photo_guidance_recovers_cup_body_and_excludes_spoon():
    """Representative pixel checks, not ground-truth segmentation accuracy."""
    image = cv2.imread(str(Path(__file__).parents[1] / "examples" / "coffee.png"))
    rect = [160, 10, 265, 310]
    initial = grabcut(image, rect, [])
    refined = grabcut(
        image,
        rect,
        [
            {"points": [[180, 190], [175, 260], [170, 305]], "radius": 8, "foreground": False},
            {
                "points": [[300, 305], [365, 305], [405, 245], [413, 195]],
                "radius": 10,
                "foreground": False,
            },
            {"points": [[285, 210], [285, 260], [220, 280]], "radius": 10, "foreground": True},
            {"points": [[413, 78]], "radius": 9, "foreground": False},
            {"points": [[361, 270], [365, 285], [372, 300]], "radius": 10, "foreground": False},
        ],
    )
    assert initial[260, 285] == 0 and refined[260, 285] == 1
    assert initial[280, 365] == 1 and refined[280, 365] == 0
    assert 35000 < refined.sum() < 60000
