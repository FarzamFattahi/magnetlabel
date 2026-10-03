import io
import json
import zipfile

import pytest
from conftest import png
from test_project import object_mask

from magnetlabel.exporting import export_dataset
from magnetlabel.store import Store


def test_legacy_task_and_annotation_task_lock(store):
    assert store.project()["task"] == "segmentation"
    image, _ = store.import_image("old.png", png())
    store.save(image, [object_mask()], True, 0)
    with pytest.raises(ValueError, match="new dataset"):
        store.configure("Old", ["object"], "detection")
    store.configure("Renamed", ["object"])
    assert store.image(image)["objects"][0]["mask"]
    assert Store(store.directory).project()["task"] == "segmentation"


@pytest.mark.parametrize(
    "box",
    [
        [-1, 0, 10, 10],
        [0, 0, 0, 10],
        [0, 0, 1, 0.5],
        [70, 0, 11, 10],
        [0, 55, 10, 6],
        [0, 0, float("nan"), 10],
        [True, 0, 10, 10],
    ],
)
def test_invalid_boxes_rejected(store, box):
    store.configure("Boxes", ["cup"], "detection")
    image, _ = store.import_image("box.png", png())
    with pytest.raises(ValueError):
        store.save(image, [{"id": "b", "class_id": 0, "bbox": box}], False, 0)
    assert store.image(image)["revision"] == 0


def test_detection_api_save_and_task_isolation(client, store):
    old = client.get("/api/project").json()["dataset_id"]
    fresh = client.post(
        "/api/datasets", json={"name": "Boxes", "classes": ["cup"], "task": "detection"}
    ).json()
    assert fresh["task"] == "detection" and fresh["images"] == []
    response = client.post("/api/import/upload", files=[("files", ("box.png", png(), "image/png"))])
    assert response.status_code == 200
    image = client.get("/api/project").json()["images"][0]
    obj = {"id": "b", "class_id": 0, "bbox": [0, 0, 80, 60]}
    url = f"/api/images/{image['id']}"
    body = {"objects": [obj], "reviewed": True, "revision": 0}
    saved = client.put(url, json=body)
    assert saved.status_code == 200 and saved.json()["objects"] == [obj]
    assert client.put(url, json=body).status_code == 409
    body["revision"] = 1
    body["objects"] = [object_mask()]
    assert client.put(url, json=body).status_code == 400
    assert (
        client.put(
            "/api/project", json={"name": "Wrong", "classes": ["cup"], "task": "segmentation"}
        ).status_code
        == 400
    )
    assert (
        client.get("/api/project", headers={"X-Dataset-ID": old}).json()["task"] == "segmentation"
    )


@pytest.mark.parametrize("fmt", ["yolo", "coco"])
def test_detection_export_native_boxes_and_negative(store, fmt):
    store.configure("Boxes", ["cup", "spoon"], "detection")
    first, _ = store.import_image("objects.png", png())
    second, _ = store.import_image("negative.png", png((5, 6, 7)))
    third, _ = store.import_image("draft.png", png((8, 9, 10)))
    objects = [
        {"id": "cup", "class_id": 0, "bbox": [0, 0, 80, 60]},
        {"id": "spoon", "class_id": 1, "bbox": [10.5, 20, 30, 10]},
    ]
    store.save(first, objects, True, 0)
    store.save(second, [], True, 0)
    data = export_dataset(store, fmt, 0.2, 42, 1, False)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["task"] == "detection" and manifest["excluded_unreviewed"] == 1
        assert not any(n.startswith("masks/") for n in archive.namelist())
        assert len(manifest["images"]) == 2
        if fmt == "yolo":
            lines = [
                archive.read(n).decode() for n in archive.namelist() if n.startswith("labels/")
            ]
            assert "" in lines
            rows = [r.split() for text in lines for r in text.splitlines()]
            assert all(len(r) == 5 for r in rows)
            assert rows[0] == ["0", "0.50000000", "0.50000000", "1.00000000", "1.00000000"]
            assert list(map(float, rows[1][1:])) == pytest.approx(
                [25.5 / 80, 25 / 60, 30 / 80, 10 / 60]
            )
        else:
            annotations = [
                a
                for n in archive.namelist()
                if n.startswith("annotations/")
                for a in json.loads(archive.read(n))["annotations"]
            ]
            assert len(annotations) == 2
            assert annotations[1]["bbox"] == [10.5, 20, 30, 10] and annotations[1]["area"] == 300
            assert all("segmentation" not in a for a in annotations)


def test_geometry_type_cannot_mix(store):
    image, _ = store.import_image("image.png", png())
    with pytest.raises(ValueError, match="Segmentation"):
        store.save(image, [{"id": "b", "class_id": 0, "bbox": [0, 0, 5, 5]}], False, 0)
    store.configure("Boxes", ["object"], "detection")
    with pytest.raises(ValueError, match="Detection"):
        store.save(image, [dict(object_mask(), bbox=[0, 0, 5, 5])], False, 0)
