import io
import json
import zipfile

import cv2
import numpy as np
import pytest
import yaml
from conftest import png

from magnetlabel.exporting import export_dataset, mask_rle, polygons
from magnetlabel.imaging import encode_mask


def add(store, color, mask=None, reviewed=True):
    image_id, _ = store.import_image(f"image-{color[0]}.png", png(color))
    objects = [] if mask is None else [{"id": "one", "class_id": 0, "mask": encode_mask(mask)}]
    store.save(image_id, objects, reviewed, 0)
    return image_id


def rect_mask():
    mask = np.zeros((60, 80), np.uint8)
    mask[10:40, 20:50] = 1
    return mask


def test_yolo_layout_labels_normalization_and_exact_mask_roundtrip(store):
    mask = rect_mask()
    positive = add(store, (40, 50, 60), mask)
    negative = add(store, (41, 50, 60))
    draft = add(store, (42, 50, 60), mask, reviewed=False)
    result = export_dataset(store, "yolo", 0.2, 42, 1, False)
    archive = zipfile.ZipFile(io.BytesIO(result))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["excluded_unreviewed"] == 1
    assert {i["id"] for i in manifest["images"]} == {positive, negative}
    assert not any(draft in path for path in archive.namelist())
    assert {i["split"] for i in manifest["images"]} == {"train", "val"}
    config = yaml.safe_load(archive.read("data.yaml"))
    assert config["names"] == {0: "object"}
    for entry in manifest["images"]:
        data = archive.read(f"labels/{entry['split']}/{entry['id']}.txt").decode()
        if entry["id"] == negative:
            assert data == ""
        else:
            values = data.split()
            assert values[0] == "0"
            coords = np.array(values[1:], float).reshape(-1, 2)
            assert len(coords) >= 3 and np.all((coords >= 0) & (coords <= 1))
            restored = np.zeros_like(mask)
            cv2.fillPoly(restored, [np.rint(coords * [80, 60]).astype(np.int32)], 1)
            np.testing.assert_array_equal(restored, mask)
            raw = archive.read(entry["objects"][0]["mask"])
            np.testing.assert_array_equal(
                cv2.imdecode(np.frombuffer(raw, np.uint8), 0) // 255, mask
            )


def test_split_is_reproducible(store):
    for i in range(8):
        add(store, (40 + i, 50, 60), rect_mask())
    manifests = []
    for _ in range(2):
        z = zipfile.ZipFile(io.BytesIO(export_dataset(store, "yolo", 0.25, 17, 1, False)))
        manifests.append(json.loads(z.read("manifest.json")))
    assert manifests[0] == manifests[1]
    assert sum(i["split"] == "val" for i in manifests[0]["images"]) == 2


@pytest.mark.parametrize("kind", ["hole", "disconnected"])
def test_yolo_topology_loss_requires_explicit_opt_in(store, kind):
    mask = rect_mask()
    if kind == "hole":
        mask[15:25, 25:35] = 0
    else:
        mask[45:55, 60:70] = 1
    add(store, (40, 50, 60), mask)
    add(store, (41, 50, 60))
    with pytest.raises(ValueError, match="topology"):
        export_dataset(store, "yolo", 0.2, 42, 1, False)
    z = zipfile.ZipFile(io.BytesIO(export_dataset(store, "yolo", 0.2, 42, 1, True)))
    assert len(json.loads(z.read("manifest.json"))["warnings"]) == 1


def test_coco_rle_preserves_topology_and_area(store):
    mask = rect_mask()
    mask[15:25, 25:35] = 0
    mask[45:55, 60:70] = 1
    add(store, (40, 50, 60), mask)
    add(store, (41, 50, 60))
    z = zipfile.ZipFile(io.BytesIO(export_dataset(store, "coco", 0.2, 42, 1, False)))
    annotations = [
        a
        for split in ("train", "val")
        for a in json.loads(z.read(f"annotations/instances_{split}.json"))["annotations"]
    ]
    assert len(annotations) == 1 and annotations[0]["area"] == int(mask.sum())
    rle = annotations[0]["segmentation"]
    pixels = np.concatenate(
        [np.full(count, i % 2, np.uint8) for i, count in enumerate(rle["counts"])]
    )
    np.testing.assert_array_equal(pixels.reshape(rle["size"], order="F"), mask)


def test_rle_all_foreground_starts_with_zero_run():
    assert mask_rle(np.ones((3, 4), np.uint8)) == {"size": [3, 4], "counts": [0, 12]}


def test_degenerate_yolo_shapes_are_not_silently_dropped():
    mask = np.zeros((20, 30), np.uint8)
    mask[10, 10] = 1
    with pytest.raises(ValueError, match="isolated pixel"):
        polygons(mask, 1, True)


def test_overaggressive_simplification_falls_back_to_original_contour():
    mask = np.zeros((40, 70), np.uint8)
    mask[10:13, 10:60] = 1
    outlines, _ = polygons(mask, 10, False)
    restored = np.zeros_like(mask)
    cv2.fillPoly(restored, [outlines[0]], 1)
    np.testing.assert_array_equal(restored, mask)


def test_export_requires_two_reviewed_images(store):
    add(store, (40, 50, 60), rect_mask())
    add(store, (41, 50, 60), rect_mask(), reviewed=False)
    with pytest.raises(ValueError, match="at least two"):
        export_dataset(store, "yolo", 0.2, 42, 1, False)
