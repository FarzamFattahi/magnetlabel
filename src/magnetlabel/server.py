"""Loopback-only FastAPI application. No cloud calls or model downloads."""

import io
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import cv2
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .datasets import Datasets
from .exporting import export_dataset
from .imaging import MAX_BYTES, MagneticPaths, bgr_image, encode_mask, grabcut, outline_assist
from .store import ConflictError, Store


class Config(BaseModel):
    name: str = Field(max_length=120)
    classes: list[str] = Field(min_length=1, max_length=100)
    task: Literal["segmentation", "detection"] | None = None


class Folder(BaseModel):
    path: str
    recursive: bool = False


class ObjectMask(BaseModel):
    id: str
    class_id: int = Field(ge=0)
    mask: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class Save(BaseModel):
    objects: list[ObjectMask] = Field(max_length=100)
    reviewed: bool = False
    revision: int = Field(ge=0)


class Stroke(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=1, max_length=5000)
    radius: int = Field(ge=1, le=200)
    foreground: bool


class Cut(BaseModel):
    rect: tuple[int, int, int, int]
    strokes: list[Stroke] = Field(default_factory=list, max_length=100)


class PathQuery(BaseModel):
    start: tuple[int, int]
    end: tuple[int, int]


class Outline(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=3, max_length=3000)
    strokes: list[Stroke] = Field(default_factory=list, max_length=100)


class Export(BaseModel):
    format: str = Field(pattern="^(yolo|coco)$")
    val_fraction: float = Field(default=0.2, gt=0, lt=1)
    seed: int = 42
    epsilon: float = Field(default=1, ge=0, le=10)
    allow_lossy: bool = False


def create_app(data_dir: Path) -> FastAPI:
    app = FastAPI(title="MagnetLabel", version="0.3.0")
    datasets, magnetic = Datasets(data_dir), MagneticPaths()
    app.state.store = datasets.get()
    app.state.datasets = datasets

    def resolve_store(request: Request):
        return datasets.get(
            request.headers.get("X-Dataset-ID") or request.query_params.get("dataset")
        )

    ProjectStore = Annotated[Store, Depends(resolve_store)]

    def project_view(store):
        return {**store.project(), "dataset_id": datasets.identifier(store)}

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {"detail": "Only same-origin local requests are allowed."}, status_code=403
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(
            {"detail": str(exc)}, status_code=409 if isinstance(exc, ConflictError) else 400
        )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Image or dataset not found."}, status_code=404)

    @app.get("/api/health")
    def health():
        return {"app": "magnetlabel", "version": "0.3.0"}

    @app.get("/api/datasets")
    def list_datasets():
        return datasets.listing()

    @app.post("/api/datasets")
    def create_dataset(body: Config):
        _, store = datasets.create(body.name, body.classes, body.task or "segmentation")
        return project_view(store)

    @app.post("/api/datasets/{dataset_id}/activate")
    def activate_dataset(dataset_id: str):
        return project_view(datasets.activate(dataset_id))

    @app.get("/api/project")
    def project(store: ProjectStore):
        return project_view(store)

    @app.put("/api/project")
    def configure(body: Config, store: ProjectStore):
        store.configure(body.name, body.classes, body.task)
        return project_view(store)

    @app.post("/api/import/upload")
    async def upload(files: Annotated[list[UploadFile], File()], store: ProjectStore):
        if len(files) > 500:
            raise ValueError("Upload at most 500 images in one batch.")
        added, duplicates, errors = 0, 0, []
        for file in files:
            try:
                raw = await file.read(MAX_BYTES + 1)
                _, new = await run_in_threadpool(store.import_image, file.filename or "image", raw)
                added += int(new)
                duplicates += int(not new)
            except ValueError as exc:
                errors.append({"name": file.filename, "error": str(exc)})
            finally:
                await file.close()
        return {"added": added, "duplicates": duplicates, "errors": errors}

    @app.post("/api/import/folder")
    def folder(body: Folder, store: ProjectStore):
        path = Path(body.path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Folder does not exist on the computer running MagnetLabel.")
        candidates = path.rglob("*") if body.recursive else path.iterdir()
        added, duplicates, errors, count = 0, 0, [], 0
        for file in sorted(candidates):
            if file.suffix.lower() not in {
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
                ".tif",
                ".tiff",
            }:
                continue
            if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(path):
                continue
            count += 1
            if count > 1000:
                errors.append(
                    {"name": "batch", "error": "Stopped after 1,000 files. Import smaller folders."}
                )
                break
            try:
                if file.stat().st_size > MAX_BYTES:
                    raise ValueError("Image exceeds 25 MB.")
                _, new = store.import_image(file.name, file.read_bytes())
                added += int(new)
                duplicates += int(not new)
            except (ValueError, OSError) as exc:
                errors.append({"name": file.name, "error": str(exc)})
        return {"added": added, "duplicates": duplicates, "errors": errors}

    @app.get("/api/images/{image_id}")
    def image(image_id: str, store: ProjectStore):
        return store.image(image_id)

    @app.get("/api/images/{image_id}/file")
    def image_file(image_id: str, store: ProjectStore):
        return FileResponse(store.image_path(image_id), media_type="image/png")

    @app.put("/api/images/{image_id}")
    def save(image_id: str, body: Save, store: ProjectStore):
        return store.save(
            image_id,
            [obj.model_dump(exclude_none=True) for obj in body.objects],
            body.reviewed,
            body.revision,
        )

    @app.post("/api/images/{image_id}/grabcut")
    def cut(image_id: str, body: Cut, store: ProjectStore):
        if store.project()["task"] != "segmentation":
            raise ValueError("Selection assistance is available in segmentation datasets.")
        image = bgr_image(store.image_path(image_id).read_bytes())
        return {
            "mask": encode_mask(
                grabcut(image, list(body.rect), [s.model_dump() for s in body.strokes])
            )
        }

    @app.post("/api/images/{image_id}/magnetic")
    def edge_path(image_id: str, body: PathQuery, store: ProjectStore):
        if store.project()["task"] != "segmentation":
            raise ValueError("Selection assistance is available in segmentation datasets.")
        image = bgr_image(store.image_path(image_id).read_bytes())
        try:
            points = magnetic.path(
                datasets.identifier(store) + image_id, image, list(body.start), list(body.end)
            )
        except cv2.error as exc:
            raise HTTPException(
                400, "Magnetic path failed. Try closer anchors or use a polygon."
            ) from exc
        return {"points": points}

    @app.post("/api/export")
    def export(body: Export, store: ProjectStore):
        result = export_dataset(
            store, body.format, body.val_fraction, body.seed, body.epsilon, body.allow_lossy
        )
        # The UI supplies the filename on its Blob download. An attachment header can
        # cause browser hosts to intercept a fetch before its body reaches JavaScript.
        return Response(result, media_type="application/zip")

    @app.post("/api/demo")
    def demo(store: ProjectStore):
        # Original procedural imagery: no third-party datasets or licensing ambiguity.
        import numpy as np
        from PIL import Image, ImageDraw

        rng = np.random.default_rng(42)
        for idx in range(3):
            noise = rng.integers(0, 9, (640, 960, 1), dtype=np.uint8)
            image = Image.fromarray(np.uint8(np.clip(np.array([37, 48, 47]) + noise, 0, 255)))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (80, 80, 880, 570), radius=18, fill=(58, 72, 67), outline=(78, 94, 85), width=2
            )
            cx, cy = 470 + idx * 35, 305 - idx * 10
            draw.ellipse((cx - 190, cy - 105, cx + 195, cy + 150), fill=(27, 37, 31))
            draw.polygon(
                [
                    (cx - 160, cy + 100),
                    (cx - 125, cy - 10),
                    (cx - 75, cy - 120),
                    (cx + 45, cy - 150),
                    (cx + 140, cy - 70),
                    (cx + 155, cy + 60),
                    (cx + 65, cy + 130),
                    (cx - 60, cy + 140),
                ],
                fill=(idx * 15 + 151, 183, 106),
            )
            draw.line([(cx - 155, cy + 95), (cx + 100, cy - 80)], fill=(210, 228, 162), width=5)
            for offset in (-70, -20, 30, 80):
                draw.line(
                    [(cx + offset, cy - offset // 2), (cx + offset - 30, cy - 80 - offset // 2)],
                    fill=(178, 202, 130),
                    width=3,
                )
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            store.import_image(f"demo_leaf_{idx + 1}.png", buffer.getvalue())
        return project_view(store)

    @app.post("/api/images/{image_id}/outline-assist")
    def assist_outline(image_id: str, body: Outline, store: ProjectStore):
        if store.project()["task"] != "segmentation":
            raise ValueError("Selection assistance is available in segmentation datasets.")
        image = bgr_image(store.image_path(image_id).read_bytes())
        return {
            "mask": encode_mask(
                outline_assist(image, body.points, [stroke.model_dump() for stroke in body.strokes])
            )
        }

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="workspace")
    return app
