"""Reviewed-only exports. Exact masks accompany every lossy YOLO polygon export."""

import io
import json
import random
import zipfile

import cv2
import numpy as np
import yaml

from .imaging import decode_mask
from .store import Store


def mask_rle(mask):
    """COCO's uncompressed, column-major RLE preserves holes and disjoint regions."""
    pixels = mask.flatten(order="F")
    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    counts = np.diff(np.r_[0, changes, pixels.size]).tolist()
    if pixels[0]:
        counts.insert(0, 0)
    return {"size": list(mask.shape), "counts": counts}


def polygons(mask, epsilon: float, allow_lossy: bool):
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        raise ValueError("Empty mask cannot be exported.")
    outer = [c for c, h in zip(contours, hierarchy[0], strict=True) if h[3] == -1]
    has_holes = any(h[3] != -1 for h in hierarchy[0])
    notes = []
    if has_holes:
        notes.append("holes filled in YOLO polygons")
    if len(outer) > 1:
        notes.append("disconnected regions split into separate YOLO instances")
    if notes and not allow_lossy:
        raise ValueError(
            "YOLO cannot preserve this mask's topology: "
            + "; ".join(notes)
            + ". Use COCO masks, or explicitly allow topology changes in export settings."
        )
    result = []
    for contour in outer:
        if cv2.contourArea(contour) < 1:
            raise ValueError(
                "A mask contains a line or isolated pixel. Edit it before YOLO export."
            )
        candidate = cv2.approxPolyDP(contour, epsilon, True)
        reference = np.zeros_like(mask)
        simplified = np.zeros_like(mask)
        cv2.drawContours(reference, [contour], -1, 1, -1)
        if len(candidate) >= 3:
            cv2.drawContours(simplified, [candidate], -1, 1, -1)
        union = np.logical_or(reference, simplified).sum()
        iou = np.logical_and(reference, simplified).sum() / max(1, union)
        # Prevent simplification from destroying thin or small objects.
        if len(candidate) < 3 or iou < 0.98:
            candidate = contour
        result.append(candidate.reshape(-1, 2))
    return result, notes


def export_dataset(
    store: Store, fmt: str, val_fraction: float, seed: int, epsilon: float, allow_lossy: bool
) -> bytes:
    project = store.project()
    # Snapshot annotations in a single read transaction, so edits during export cannot mix revisions.
    with store.connect() as conn:
        rows = list(conn.execute("SELECT * FROM images WHERE reviewed=1 ORDER BY id"))
    if len(rows) < 2:
        raise ValueError(
            "Review at least two images before export, including verified empty backgrounds."
        )
    images = []
    for row in rows:
        image = dict(row)
        image["objects"] = json.loads(image["objects"])
        images.append(image)
    # In-memory ZIP is intentionally bounded for this single-user edition.
    total = sum(
        store.image_path(i["id"]).stat().st_size + len(json.dumps(i["objects"])) for i in images
    )
    if total > 512 * 1024 * 1024:
        raise ValueError(
            "Export exceeds the local edition's 512 MB memory limit. Use a smaller project."
        )
    random.Random(seed).shuffle(images)
    n_val = max(1, min(len(images) - 1, round(len(images) * val_fraction)))
    val_ids = {i["id"] for i in images[:n_val]}
    manifest = {
        "version": 1,
        "format": fmt,
        "task": project["task"],
        "seed": seed,
        "val_fraction": val_fraction,
        "classes": project["classes"],
        "warnings": [],
        "images": [],
        "polygon_epsilon_pixels": epsilon,
        "minimum_simplification_iou": 0.98,
        "allow_topology_changes": allow_lossy,
        "excluded_unreviewed": len(project["images"]) - len(images),
    }
    output = io.BytesIO()
    coco = {
        split: {
            "images": [],
            "annotations": [],
            "categories": [{"id": c["id"], "name": c["name"]} for c in project["classes"]],
        }
        for split in ("train", "val")
    }
    annotation_id = 1
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for idx, image in enumerate(images, 1):
            image_id, width, height = image["id"], image["width"], image["height"]
            split = "val" if image_id in val_ids else "train"
            archive.write(store.image_path(image_id), f"images/{split}/{image_id}.png")
            coco[split]["images"].append(
                {"id": idx, "file_name": f"{image_id}.png", "width": width, "height": height}
            )
            entry = {
                "id": image_id,
                "original_name": image["name"],
                "split": split,
                "revision": image["revision"],
                "objects": [],
            }
            lines = []
            for j, obj in enumerate(image["objects"]):
                if project["task"] == "detection":
                    x, y, w, h = obj["bbox"]
                    entry["objects"].append(
                        {"id": obj["id"], "class_id": obj["class_id"], "bbox": obj["bbox"]}
                    )
                    if fmt == "yolo":
                        coords = [(x + w / 2) / width, (y + h / 2) / height, w / width, h / height]
                        lines.append(
                            str(obj["class_id"]) + " " + " ".join(f"{v:.8f}" for v in coords)
                        )
                    else:
                        coco[split]["annotations"].append(
                            {
                                "id": annotation_id,
                                "image_id": idx,
                                "category_id": obj["class_id"],
                                "bbox": obj["bbox"],
                                "area": w * h,
                                "iscrowd": 0,
                            }
                        )
                        annotation_id += 1
                    continue
                mask = decode_mask(obj["mask"], width, height)
                mask_path = f"masks/{image_id}/{j:03}.png"
                archive.writestr(mask_path, cv2.imencode(".png", mask * 255)[1].tobytes())
                entry["objects"].append(
                    {"id": obj["id"], "class_id": obj["class_id"], "mask": mask_path}
                )
                if fmt == "yolo":
                    try:
                        outlines, notes = polygons(mask, epsilon, allow_lossy)
                    except ValueError as exc:
                        raise ValueError(f"{image['name']}, object {j + 1}: {exc}") from exc
                    for note in notes:
                        manifest["warnings"].append(
                            {"image": image_id, "object": obj["id"], "message": note}
                        )
                    for points in outlines:
                        coords = points.astype(float) / [width, height]
                        lines.append(
                            str(obj["class_id"]) + " " + " ".join(f"{n:.8f}" for n in coords.flat)
                        )
                else:
                    ys, xs = np.nonzero(mask)
                    coco[split]["annotations"].append(
                        {
                            "id": annotation_id,
                            "image_id": idx,
                            "category_id": obj["class_id"],
                            "segmentation": mask_rle(mask),
                            "area": int(mask.sum()),
                            "iscrowd": 0,
                            "bbox": [
                                int(xs.min()),
                                int(ys.min()),
                                int(xs.max() - xs.min() + 1),
                                int(ys.max() - ys.min() + 1),
                            ],
                        }
                    )
                    annotation_id += 1
            if fmt == "yolo":
                archive.writestr(
                    f"labels/{split}/{image_id}.txt", "\n".join(lines) + ("\n" if lines else "")
                )
            manifest["images"].append(entry)
        if fmt == "yolo":
            archive.writestr(
                "data.yaml",
                yaml.safe_dump(
                    {
                        "path": ".",
                        "train": "images/train",
                        "val": "images/val",
                        "names": {c["id"]: c["name"] for c in project["classes"]},
                    },
                    sort_keys=False,
                ),
            )
        else:
            for split in ("train", "val"):
                archive.writestr(f"annotations/instances_{split}.json", json.dumps(coco[split]))
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr(
            "README.txt",
            f"MagnetLabel reviewed {project['task']} dataset\n"
            "Original names and instance identities: manifest.json\n"
            + (
                "Exact binary masks: masks/ (0 background, 255 foreground)\n"
                if project["task"] == "segmentation"
                else "Bounding boxes: manifest.json; YOLO labels use normalized center x/y, width/height.\n"
            )
            + "Images are EXIF-normalized RGB PNG copies.\n"
            "For YOLO, set data.yaml path to this extracted directory's absolute path.\n"
            "Inspect manifest warnings before training. Split is by image, not source sequence.\n",
        )
    return output.getvalue()
