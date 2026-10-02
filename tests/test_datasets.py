from conftest import png
from fastapi.testclient import TestClient
from test_project import object_mask

from magnetlabel.server import create_app


def test_new_dataset_is_empty_and_old_tab_remains_isolated(client, store):
    image_id, _ = store.import_image("old.png", png())
    store.save(image_id, [object_mask()], True, 0)
    original = client.get("/api/project").json()["dataset_id"]
    fresh = client.post("/api/datasets", json={"name": "Fresh", "classes": ["cup", "spoon"]})
    assert fresh.status_code == 200
    fresh = fresh.json()
    assert fresh["images"] == []
    assert [c["name"] for c in fresh["classes"]] == ["cup", "spoon"]
    assert fresh["dataset_id"] != original
    assert client.get(f"/api/images/{image_id}").status_code == 404
    headers = {"X-Dataset-ID": original}
    assert client.get(f"/api/images/{image_id}", headers=headers).json()["reviewed"]
    assert client.get(f"/api/images/{image_id}/file?dataset={original}").status_code == 200
    client.post(
        "/api/import/upload",
        headers=headers,
        files=[("files", ("second.png", png((90, 20, 10)), "image/png"))],
    )
    assert client.get("/api/project").json()["images"] == []
    old = client.post(f"/api/datasets/{original}/activate").json()
    assert len(old["images"]) == 2
    assert old["images"][0]["objects_count"] == 1
    assert len(client.get("/api/datasets").json()) == 2


def test_active_dataset_survives_restart(client, store):
    fresh = client.post("/api/datasets", json={"name": "Restart", "classes": ["spoon"]}).json()
    with TestClient(create_app(store.directory)) as reopened:
        assert reopened.get("/api/project").json()["dataset_id"] == fresh["dataset_id"]


def test_unknown_dataset_never_falls_back_to_active(client):
    assert client.get("/api/project", headers={"X-Dataset-ID": "missing"}).status_code == 404
    assert client.get("/api/project?dataset=../private").status_code == 404
    assert client.post("/api/datasets/missing/activate").status_code == 404


def test_outline_endpoint_validates_and_returns_native_mask(client, store):
    import io

    import cv2
    import numpy as np
    from PIL import Image

    from magnetlabel.imaging import decode_mask

    image = np.full((100, 140, 3), 25, np.uint8)
    cv2.circle(image, (70, 50), 25, (70, 180, 240), -1)
    raw = io.BytesIO()
    Image.fromarray(image).save(raw, "PNG")
    image_id, _ = store.import_image("circle.png", raw.getvalue())
    url = f"/api/images/{image_id}/outline-assist"
    response = client.post(url, json={"points": [[35, 15], [105, 15], [105, 85], [35, 85]]})
    assert response.status_code == 200
    mask = decode_mask(response.json()["mask"], 140, 100)
    assert mask[50, 70] == 1 and mask[15, 35] == 0
    assert client.post(url, json={"points": [[-5, 15], [105, 15], [105, 85]]}).status_code == 400
    assert client.post(url, json={"points": [[35, 15], [105, 15]]}).status_code == 422
