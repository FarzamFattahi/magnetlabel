"""A project is a portable directory: SQLite metadata plus normalized PNG images."""

import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path

from .imaging import decode_mask, encode_mask, normalize_image

PALETTE = ["#c8ef80", "#82c9ff", "#ffb38a", "#c7a6ff", "#ff91ba", "#80e2d0"]


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.images_dir = self.directory / "images"
        self.images_dir.mkdir(exist_ok=True)
        self.db = self.directory / "project.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, width INTEGER, height INTEGER,
                    digest TEXT UNIQUE, objects TEXT NOT NULL DEFAULT '[]',
                    reviewed INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0
                );
            """)
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('configured', 'false')")
            conn.execute("INSERT OR IGNORE INTO settings VALUES ('task', '\"segmentation\"')")
            conn.execute(
                "INSERT OR IGNORE INTO settings VALUES ('name', ?)",
                (json.dumps("My segmentation project"),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings VALUES ('classes', ?)",
                (json.dumps([{"id": 0, "name": "object", "color": PALETTE[0]}]),),
            )

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def project(self):
        with self.connect() as conn:
            settings = {
                r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")
            }
            settings["images"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,name,width,height,reviewed,revision FROM images ORDER BY rowid"
                )
            ]
            counts = {
                r["id"]: len(json.loads(r["objects"]))
                for r in conn.execute("SELECT id,objects FROM images")
            }
        for image in settings["images"]:
            image["objects_count"] = counts[image["id"]]
        return settings

    def configure(self, name: str, classes: list[str], task: str | None = None):
        if task is not None and task not in ("segmentation", "detection"):
            raise ValueError("Choose segmentation or detection.")
        names = [s.strip() for s in classes]
        if (
            not name.strip()
            or not 1 <= len(names) <= 100
            or any(not s or len(s) > 80 for s in names)
        ):
            raise ValueError("Use a project name and 1–100 class names of 1–80 characters.")
        if len(set(names)) != len(names):
            raise ValueError("Class names must be unique.")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = json.loads(
                conn.execute("SELECT value FROM settings WHERE key='classes'").fetchone()[0]
            )
            # Stable IDs protect existing annotation meaning. Rename/reorder only on empty projects.
            has_objects = conn.execute(
                "SELECT 1 FROM images WHERE objects != '[]' LIMIT 1"
            ).fetchone()
            if has_objects and names[: len(old)] != [c["name"] for c in old]:
                raise ValueError(
                    "Existing classes cannot be renamed, removed, or reordered once annotations exist. Append new classes."
                )
            old_task = json.loads(
                conn.execute("SELECT value FROM settings WHERE key='task'").fetchone()[0]
            )
            if has_objects and task is not None and task != old_task:
                raise ValueError("Start a new dataset to change task after annotations exist.")
            if task is not None:
                conn.execute("UPDATE settings SET value=? WHERE key='task'", (json.dumps(task),))
            values = [
                {"id": i, "name": s, "color": PALETTE[i % len(PALETTE)]}
                for i, s in enumerate(names)
            ]
            conn.execute(
                "UPDATE settings SET value=? WHERE key='name'", (json.dumps(name.strip()),)
            )
            conn.execute("UPDATE settings SET value=? WHERE key='classes'", (json.dumps(values),))
            conn.execute("UPDATE settings SET value='true' WHERE key='configured'")

    def import_image(self, name: str, raw: bytes):
        png, width, height = normalize_image(raw)
        digest = hashlib.sha256(png).hexdigest()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT id FROM images WHERE digest=?", (digest,)).fetchone()
            if existing:
                return existing[0], False
            image_id = uuid.uuid4().hex
            destination = self.images_dir / f"{image_id}.png"
            destination.write_bytes(png)
            try:
                conn.execute(
                    "INSERT INTO images (id,name,width,height,digest) VALUES (?,?,?,?,?)",
                    (image_id, Path(name.replace("\\", "/")).name[:200], width, height, digest),
                )
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return image_id, True

    def image(self, image_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if row is None:
            raise KeyError("Image not found.")
        image = dict(row)
        image["objects"] = json.loads(image["objects"])
        image.pop("digest")
        return image

    def image_path(self, image_id: str):
        self.image(image_id)  # Existence check before constructing a filesystem path.
        return self.images_dir / f"{image_id}.png"

    def save(self, image_id: str, objects: list[dict], reviewed: bool, revision: int):
        image = self.image(image_id)
        if len(objects) > 100:
            raise ValueError("At most 100 objects per image.")
        validated = []
        ids = set()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            classes = json.loads(
                conn.execute("SELECT value FROM settings WHERE key='classes'").fetchone()[0]
            )
            for obj in objects:
                if obj["id"] in ids or not obj["id"] or len(obj["id"]) > 80:
                    raise ValueError("Each object needs a unique ID of at most 80 characters.")
                ids.add(obj["id"])
                if not 0 <= obj["class_id"] < len(classes):
                    raise ValueError("Object has an unknown class.")
                task = json.loads(
                    conn.execute("SELECT value FROM settings WHERE key='task'").fetchone()[0]
                )
                if task == "detection":
                    box = obj.get("bbox")
                    if (
                        obj.get("mask") is not None
                        or not isinstance(box, (list, tuple))
                        or len(box) != 4
                    ):
                        raise ValueError(
                            "Detection objects require a bounding box, without a mask."
                        )
                    if any(
                        isinstance(v, bool)
                        or not isinstance(v, (int, float))
                        or not math.isfinite(v)
                        for v in box
                    ):
                        raise ValueError("Bounding box coordinates must be finite numbers.")
                    x, y, w, h = box
                    if (
                        x < 0
                        or y < 0
                        or w < 1
                        or h < 1
                        or x + w > image["width"]
                        or y + h > image["height"]
                    ):
                        raise ValueError(
                            "Bounding boxes must be at least one pixel and inside the image."
                        )
                    validated.append(
                        {"id": obj["id"], "class_id": obj["class_id"], "bbox": list(box)}
                    )
                else:
                    if obj.get("bbox") is not None or not obj.get("mask"):
                        raise ValueError(
                            "Segmentation objects require a mask, without a bounding box."
                        )
                    mask = decode_mask(obj["mask"], image["width"], image["height"])
                    if not mask.any():
                        raise ValueError("Empty objects cannot be saved. Remove the empty object.")
                    validated.append(
                        {"id": obj["id"], "class_id": obj["class_id"], "mask": encode_mask(mask)}
                    )
            result = conn.execute(
                "UPDATE images SET objects=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (json.dumps(validated), int(reviewed), image_id, revision),
            )
            if result.rowcount != 1:
                raise ConflictError("This image changed in another tab. Reload before saving.")
        return self.image(image_id)
