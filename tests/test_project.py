import numpy as np
import pytest
from conftest import png

from magnetlabel.imaging import encode_mask
from magnetlabel.store import ConflictError, Store


def object_mask(width=80, height=60):
    mask = np.zeros((height, width), np.uint8)
    mask[10:40, 20:50] = 1
    return {"id": "instance-1", "class_id": 0, "mask": encode_mask(mask)}


def test_import_deduplicates_normalized_image(store):
    image_id, added = store.import_image("first.png", png())
    other, new = store.import_image("other-name.png", png())
    assert added and not new and image_id == other
    assert len(store.project()["images"]) == 1


def test_save_reopen_and_stale_write_protection(store):
    image_id, _ = store.import_image("image.png", png())
    image = store.save(image_id, [object_mask()], True, 0)
    assert image["revision"] == 1 and image["reviewed"]
    with pytest.raises(ConflictError):
        store.save(image_id, [], False, 0)
    reopened = Store(store.directory)
    assert reopened.image(image_id)["objects"][0]["id"] == "instance-1"
    assert reopened.image(image_id)["reviewed"]


def test_class_ids_cannot_change_under_existing_masks(store):
    image_id, _ = store.import_image("image.png", png())
    store.save(image_id, [object_mask()], False, 0)
    with pytest.raises(ValueError, match="cannot be renamed"):
        store.configure("New title", ["leaf"])
    store.configure("Leaves", ["object", "leaf"])
    assert store.project()["classes"][1]["id"] == 1


def test_empty_object_and_unknown_class_rejected(store):
    image_id, _ = store.import_image("image.png", png())
    obj = object_mask()
    obj["mask"] = encode_mask(np.zeros((60, 80), np.uint8))
    with pytest.raises(ValueError, match="Empty"):
        store.save(image_id, [obj], True, 0)
    obj = object_mask()
    obj["class_id"] = 3
    with pytest.raises(ValueError, match="unknown class"):
        store.save(image_id, [obj], False, 0)


def test_upload_errors_are_visible_and_valid_files_still_import(client):
    response = client.post(
        "/api/import/upload",
        files=[
            ("files", ("valid.png", png(), "image/png")),
            ("files", ("bad.jpg", b"not an image", "image/jpeg")),
        ],
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert len(response.json()["errors"]) == 1


def test_folder_import_is_nonrecursive_unless_requested(client, tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "one.png").write_bytes(png())
    (folder / "sub").mkdir()
    (folder / "sub" / "two.png").write_bytes(png((100, 110, 120)))
    assert client.post("/api/import/folder", json={"path": str(folder)}).json()["added"] == 1
    assert (
        client.post("/api/import/folder", json={"path": str(folder), "recursive": True}).json()[
            "added"
        ]
        == 1
    )


def test_cross_origin_mutation_and_unknown_hosts_rejected(client):
    response = client.post("/api/demo", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.get("/api/project", headers={"Host": "evil.example"}).status_code == 400


def test_unknown_image_and_path_traversal_are_not_filesystem_reads(client):
    assert client.get("/api/images/not-found/file").status_code == 404
    assert client.get("/api/images/..%2Fproject.sqlite3/file").status_code == 404


def test_demo_import_is_repeatable_and_ui_assets_served(client):
    assert len(client.post("/api/demo").json()["images"]) == 3
    assert len(client.post("/api/demo").json()["images"]) == 3
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]


def test_api_conflict_and_validation(client, store):
    image_id, _ = store.import_image("one.png", png())
    body = {"objects": [object_mask()], "reviewed": False, "revision": 0}
    assert client.put(f"/api/images/{image_id}", json=body).status_code == 200
    assert client.put(f"/api/images/{image_id}", json=body).status_code == 409
    assert client.post("/api/export", json={"format": "bogus"}).status_code == 422
