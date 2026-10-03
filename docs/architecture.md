# Architecture

The application has no frontend build step. FastAPI serves static HTML/CSS/JavaScript plus a JSON API, while OpenCV performs assisted selection on CPU. This keeps the Python package installable and the behavior easy to inspect.

```text
Browser canvas
  image coordinates → temporary mask / outline / rectangle → added class-labeled objects
      |
      | same-origin loopback HTTP
      v
FastAPI
  imaging.py    EXIF normalization, PNG mask codec, GrabCut, cached magnetic paths
  store.py      SQLite project/classes/images/objects/review state/revisions
  datasets.py   workspace registry, isolated stores, active dataset and tab scoping
  exporting.py reviewed snapshot, split, polygon/RLE conversion, masks and manifest
      |
      v
Project directory
  datasets.json + original project.sqlite3/images + projects/<uuid>/project.sqlite3/images
```

## Coordinates and masks

1. Import normalizes orientation and converts the image to RGB PNG.
2. The canvas uses a zoom/pan transform for display; all points and brushes are recorded in normalized **source-image pixel coordinates**, not browser coordinates.
3. Browser masks use opaque white foreground and transparent background. Saving thresholds alpha at 128; stored masks use grayscale binary PNGs.
4. OpenCV assistance is computed at up to 1,200 pixels per side and mapped back. Nearest-neighbor resizing prevents soft label values, but it cannot recover detail lost during downsampling.
5. Each added instance has its own mask and a stable class ID. Overlapping objects are permitted; the reviewer decides the appropriate occlusion convention.

## Persistence

SQLite serializes writes. Saves validate mask dimensions, nonempty objects, unique instance IDs and known classes. A revision predicate detects stale-tab writes. Existing classes are immutable after annotations exist, except for appending new ones. Added objects autosave; outline anchors and unfinished drafts do not.

Editing clears reviewed state in the UI save payload. Direct API clients are responsible for that workflow convention; the API is a local app interface, not a hardened public annotation service.

Dataset creation allocates a separate directory and switches the workspace's active dataset. Browser requests carry an explicit dataset ID, including image-file query strings, so a tab opened on an earlier dataset cannot accidentally mutate the newly active one. The registry is atomically replaced under a lock. Legacy single-dataset directories remain the original dataset.

Smart polygons and freehand lassos are rasterized into probable-foreground regions; everything outside is definite background. GrabCut estimates appearance inside the region and the final mask is clipped to the original outline. Manual/magnetic outlines can invoke the same refinement explicitly. Foreground/background hints guide recomputation; pixel brushes remain direct edits.

## Performance

Magnetic shortest-path maps use a four-entry LRU protected by a lock. A new anchor builds a new map, while hover targets from the same anchor reuse it. The UI debounces preview requests and rejects obsolete results. CPU-heavy imports run outside the event loop. Colored mask overlays are cached and invalidated by brush changes. Undo history is capped at 12 snapshots; complex large images can still consume substantial browser memory.

## Export contracts

- Only reviewed images enter a single read snapshot. At least two images are required for nonempty train/validation partitions.
- A seeded shuffle assigns images; class IDs do not change.
- YOLO conversion checks holes, disconnected components and degenerate contours. Lossy topology changes require explicit opt-in and generate manifest warnings.
- COCO uses uncompressed column-major RLE; masks accompany both formats.
- Estimated package input size is bounded to 512 MB. ZIP output is constructed in memory, so actual process memory can be higher than that estimate.

## Local boundary

The launcher binds to `127.0.0.1`. Trusted-host and same-origin checks reject browser requests from other origins; no CORS permission is granted. The UI escapes filenames/class names through DOM text nodes. Data directories, environments and exports are excluded from Git. This edition has no authentication and must not be exposed as a network service.

## Detection task

The dataset settings persist `task: detection` or `segmentation`; legacy workspaces migrate to segmentation automatically. Once any annotations exist, task changes require a new dataset. Task and class changes use SQLite write transactions.

Detection objects store native source-pixel `bbox: [x, y, width, height]`, independently of masks. Coordinates are finite; boxes must be at least one pixel and within image bounds. Right and bottom edges may equal the image dimensions. Segmentation and box schemas cannot be mixed. Autosave revision conflicts, class validation, dataset scoping, review, and undo apply to both tasks.

YOLO detection export normalizes box centers and sizes and writes one five-column row per object. COCO detection includes boxes and their area, without a segmentation field. No mask images are generated for detection.
