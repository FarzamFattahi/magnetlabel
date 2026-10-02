import base64
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from magnetlabel.imaging import (
    MagneticPaths,
    decode_mask,
    encode_mask,
    grabcut,
    normalize_image,
    outline_assist,
)


def test_exif_orientation_is_applied_before_annotation():
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    raw = io.BytesIO()
    image.save(raw, "JPEG", exif=exif)
    normalized, w, h = normalize_image(raw.getvalue())
    assert (w, h) == (20, 40)
    assert Image.open(io.BytesIO(normalized)).getexif().get(274) is None


def test_transparent_source_is_composited_on_white():
    image = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    raw = io.BytesIO()
    image.save(raw, "PNG")
    normalized, _, _ = normalize_image(raw.getvalue())
    assert Image.open(io.BytesIO(normalized)).getpixel((0, 0)) == (255, 255, 255)


def test_mask_roundtrip_preserves_holes_and_disjoint_pixels():
    mask = np.zeros((50, 80), np.uint8)
    mask[5:30, 5:30] = 1
    mask[12:20, 12:20] = 0
    mask[45, 70] = 1
    np.testing.assert_array_equal(decode_mask(encode_mask(mask), 80, 50), mask)


def test_browser_rgba_masks_use_alpha_not_white_rgb():
    rgba = np.full((12, 20, 4), 255, np.uint8)
    rgba[:, :, 3] = 0
    rgba[2:7, 3:8, 3] = 255
    buffer = io.BytesIO()
    Image.fromarray(rgba).save(buffer, "PNG")
    data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    mask = decode_mask(data, 20, 12)
    assert mask.sum() == 25


@pytest.mark.parametrize("data", ["invalid", "data:image/png;base64,@@@@"])
def test_invalid_mask_rejected(data):
    with pytest.raises(ValueError):
        decode_mask(data, 20, 12)


def test_wrong_mask_dimensions_rejected():
    with pytest.raises(ValueError, match="dimensions"):
        decode_mask(encode_mask(np.ones((12, 20), np.uint8)), 21, 12)


def test_grabcut_recovers_contrasting_object():
    image = np.full((100, 140, 3), 25, np.uint8)
    cv2.circle(image, (70, 50), 25, (70, 180, 240), -1)
    expected = np.zeros((100, 140), np.uint8)
    cv2.circle(expected, (70, 50), 25, 1, -1)
    result = grabcut(image, [35, 15, 70, 70], [])
    iou = np.logical_and(result, expected).sum() / np.logical_or(result, expected).sum()
    assert iou > 0.98


@pytest.mark.parametrize(
    "points",
    [
        [[35, 15], [105, 15], [105, 85], [35, 85]],
        [[30, 50], [40, 20], [70, 12], [100, 20], [110, 50], [100, 80], [70, 88], [40, 80]],
    ],
)
def test_rough_polygon_and_lasso_shrink_to_object(points):
    image = np.full((100, 140, 3), 25, np.uint8)
    cv2.circle(image, (70, 50), 25, (70, 180, 240), -1)
    expected = np.zeros((100, 140), np.uint8)
    cv2.circle(expected, (70, 50), 25, 1, -1)
    region = np.zeros_like(expected)
    cv2.fillPoly(region, [np.array(points, np.int32)], 1)
    result = outline_assist(image, points, [])
    assert not (result & (1 - region)).any()
    assert result.sum() < region.sum()
    assert np.logical_and(result, expected).sum() / np.logical_or(result, expected).sum() > 0.98


@pytest.mark.parametrize(
    "points",
    [
        [[0, 0], [139, 0], [139, 99], [0, 99]],
        [[5, 5], [5, 5], [5, 5]],
        [[-1, 0], [30, 10], [30, 30]],
        [[5, 5], [20, 20]],
        [[5, 5], [float("nan"), 20], [30, 30]],
    ],
)
def test_invalid_outline_is_rejected(points):
    with pytest.raises(ValueError):
        outline_assist(np.zeros((100, 140, 3), np.uint8), points, [])


def test_grabcut_negative_hint_removes_distractor():
    image = np.full((100, 140, 3), 25, np.uint8)
    cv2.circle(image, (50, 50), 20, (70, 180, 240), -1)
    cv2.circle(image, (95, 50), 10, (70, 180, 240), -1)
    result = grabcut(
        image,
        [20, 20, 100, 60],
        [
            {"points": [[95, 50]], "radius": 12, "foreground": False},
            {"points": [[50, 50]], "radius": 5, "foreground": True},
        ],
    )
    assert result[50, 50] == 1
    assert result[50, 95] == 0


def test_full_image_box_has_no_background_and_is_rejected():
    with pytest.raises(ValueError, match="background"):
        grabcut(np.zeros((100, 140, 3), np.uint8), [0, 0, 140, 100], [])


def test_magnetic_path_follows_edge_instead_of_diagonal():
    image = np.zeros((100, 120, 3), np.uint8)
    cv2.rectangle(image, (20, 20), (95, 75), (230, 230, 230), -1)
    paths = MagneticPaths()
    points = np.array(paths.path("one", image, [20, 20], [95, 75]))
    assert points[0].tolist() == [20, 20]
    assert points[-1].tolist() == [95, 75]
    distance_to_edge = np.minimum.reduce(
        [
            abs(points[:, 0] - 20),
            abs(points[:, 0] - 95),
            abs(points[:, 1] - 20),
            abs(points[:, 1] - 75),
        ]
    )
    assert np.mean(distance_to_edge <= 2) > 0.95
    assert paths.path("one", image, [20, 20], [95, 20])[-1] == [95, 20]
    assert len(paths.cache) == 1
