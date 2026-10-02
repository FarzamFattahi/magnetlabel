"""Image normalization, mask codecs, GrabCut, and live-wire edge paths."""

import base64
import io
import threading
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def normalize_image(raw: bytes) -> tuple[bytes, int, int]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Images must be nonempty and at most 25 MB each.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Images must contain at most 16 million pixels.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            image = background.convert("RGB")
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("This file is not a supported, readable image.") from exc


def encode_mask(mask: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", np.uint8(mask > 0) * 255)
    if not ok:
        raise ValueError("Could not encode the mask.")
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")


def decode_mask(value: str, width: int, height: int) -> np.ndarray:
    if not value.startswith("data:image/png;base64,") or len(value) > MAX_BYTES * 2:
        raise ValueError("Mask must be a PNG data URL no larger than 50 MB.")
    try:
        raw = base64.b64decode(value.split(",", 1)[1], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise ValueError("Mask dimensions must match the normalized image.")
            # Browser paint masks use transparency; stored masks use grayscale.
            channel = image.getchannel("A") if image.mode == "RGBA" else image.convert("L")
            return np.uint8(np.array(channel) >= 128)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid mask PNG.") from exc


def bgr_image(raw: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def work_image(image: np.ndarray, max_side: int = 1200) -> tuple[np.ndarray, float]:
    scale = min(1.0, max_side / max(image.shape[:2]))
    if scale == 1:
        return image, scale
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale


def grabcut(image: np.ndarray, rect: list[int], strokes: list[dict]) -> np.ndarray:
    height, width = image.shape[:2]
    x, y, w, h = rect
    if x < 0 or y < 0 or w < 3 or h < 3 or x + w > width or y + h > height:
        raise ValueError("Draw a box at least 3 pixels wide and tall inside the image.")
    if w * h >= width * height:
        raise ValueError("Leave some background outside the selection box.")
    region = np.zeros((height, width), np.uint8)
    region[y : y + h, x : x + w] = 1
    return segment_region(image, region, strokes)


def outline_assist(image: np.ndarray, points: list, strokes: list[dict]) -> np.ndarray:
    """Shrink a coarse polygon/lasso to foreground; never invent pixels outside it."""
    height, width = image.shape[:2]
    coordinates = np.asarray(points, dtype=float)
    if len(coordinates) < 3 or coordinates.ndim != 2 or coordinates.shape[1] != 2:
        raise ValueError("Draw an outline with at least three points.")
    if not np.isfinite(coordinates).all() or np.any(coordinates < 0):
        raise ValueError("Outline points must be finite and inside the image.")
    if np.any(coordinates[:, 0] >= width) or np.any(coordinates[:, 1] >= height):
        raise ValueError("Outline points must be inside the image.")
    region = np.zeros((height, width), np.uint8)
    cv2.fillPoly(region, [np.rint(coordinates).astype(np.int32)], 1)
    if region.sum() < 9 or not np.any(region == 0):
        raise ValueError("Leave background outside an outline of at least nine pixels.")
    return segment_region(image, region, strokes)


def segment_region(image: np.ndarray, region: np.ndarray, strokes: list[dict]) -> np.ndarray:
    height, width = image.shape[:2]
    work, scale = work_image(image)
    wh, ww = work.shape[:2]
    resized = cv2.resize(region, (ww, wh), interpolation=cv2.INTER_NEAREST)
    labels = np.where(resized > 0, cv2.GC_PR_FGD, cv2.GC_BGD).astype(np.uint8)
    for stroke in strokes:
        points = np.array(stroke["points"], dtype=float)
        if not np.isfinite(points).all() or points.ndim != 2 or points.shape[1] != 2:
            raise ValueError("Stroke points must be finite coordinate pairs.")
        if np.any(points < 0) or np.any(points[:, 0] >= width) or np.any(points[:, 1] >= height):
            raise ValueError("Stroke points must be inside the image.")
        points = np.rint(points * scale).astype(np.int32)
        radius = max(1, round(stroke["radius"] * scale))
        value = cv2.GC_FGD if stroke["foreground"] else cv2.GC_BGD
        for point in points:
            cv2.circle(labels, tuple(point), radius, value, -1)
        if len(points) > 1:
            cv2.polylines(labels, [points], False, value, radius * 2)
    if not np.any((labels == 0) | (labels == 2)) or not np.any(labels % 2):
        raise ValueError("Selection needs both foreground and background samples.")
    try:
        cv2.grabCut(
            work, labels, None, np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_MASK
        )
    except cv2.error as exc:
        raise ValueError(
            "Selection could not be computed. Try a tighter box or a polygon."
        ) from exc
    mask = np.uint8((labels == 1) | (labels == 3))
    mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    mask &= region
    if not mask.any():
        raise ValueError("No foreground found. Add foreground hints or use magnetic outline.")
    return mask


class MagneticPaths:
    """Small, locked LRU of shortest-path maps, shared by hover requests."""

    def __init__(self):
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def path(self, image_id: str, image: np.ndarray, start: list[int], end: list[int]):
        height, width = image.shape[:2]
        for x, y in (start, end):
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Magnetic anchors must be inside the image.")
        work, scale = work_image(image)
        wh, ww = work.shape[:2]
        source = tuple(np.minimum([ww - 1, wh - 1], np.rint(np.array(start) * scale)).astype(int))
        target = tuple(np.minimum([ww - 1, wh - 1], np.rint(np.array(end) * scale)).astype(int))
        key = (image_id, source)
        with self.lock:
            if key not in self.cache:
                scissors = cv2.segmentation_IntelligentScissorsMB()
                scissors.setEdgeFeatureCannyParameters(32, 100)
                scissors.applyImage(work)
                scissors.buildMap(source)
                self.cache[key] = scissors
                while len(self.cache) > 4:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            contour = self.cache[key].getContour(target).reshape(-1, 2)
        path = np.rint(contour / scale).astype(int)
        path[:, 0] = np.clip(path[:, 0], 0, width - 1)
        path[:, 1] = np.clip(path[:, 1], 0, height - 1)
        result = path.tolist()
        if not result:
            return [start, end]
        if np.linalg.norm(np.array(result[0]) - start) > np.linalg.norm(
            np.array(result[-1]) - start
        ):
            result.reverse()
        result[0], result[-1] = start, end
        return result
