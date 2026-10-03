# Validation — 0.3.0

Validated locally on Windows 11, Python 3.12, OpenCV, FastAPI, and Microsoft Edge. CI is configured for Linux and Python 3.11–3.13; consult the Actions badge for the current remote result.

## Backend

54 pytest checks passed. They cover EXIF normalization, transparency, mask codecs, holes/disconnected regions, native mask dimensions, positive/negative GrabCut hints, edge-following magnetic paths, dataset isolation and restart, stale-tab saves, stable class IDs, upload/folder validation, same-origin protections, reviewed-only exports, deterministic splits, and YOLO/COCO round-trips.

Both coarse polygon and freehand-outline fixtures recover a known high-contrast circle with over 98% IoU, remain inside the input outline, and remove background. These controlled checks establish geometry and API behavior, not accuracy on arbitrary photographs. Full-image, tiny, nonfinite, and out-of-bounds outlines are rejected.

Ruff and JavaScript syntax checks pass. Starlette's current TestClient warns about its httpx integration; this warning does not affect the served application or test results.

## Actual browser interactions

Install Playwright (`npm install --no-save playwright`) and use an installed Edge browser, or set `BROWSER_CHANNEL=chrome`. Node is needed only for development tests.

Start a fresh workspace in one terminal:

```bash
magnetlabel --no-browser --port 8769 --data data/browser-check
```

In another terminal:

```bash
# PowerShell: $env:MAGNETLABEL_URL='http://127.0.0.1:8769'
# POSIX: export MAGNETLABEL_URL=http://127.0.0.1:8769
node tests/browser-smoke.cjs
python -c "import cv2,numpy as np; a=np.full((100,140,3),25,np.uint8); cv2.circle(a,(70,50),25,(70,180,240),-1); cv2.imwrite('data/browser-circle.png',a)"
node tests/usability-browser.cjs
node tests/real-photo-browser.cjs
```

All three scripts passed locally with no page JavaScript errors. The general smoke test checks label setup, genuine box/magnetic/polygon drawing, hint/brush editing, undo, relabeling, review invalidation, persistence, and nonempty YOLO/COCO ZIP downloads. The downloaded archives also passed ZIP integrity checks.

The usability test compares rendered canvas pixels before and after right-button drag, verifies smart-polygon and lasso mask overlap against a known circle, tightens a manual polygon, measures focus-mode canvas growth, creates an empty dataset, and restores earlier annotations. The 390 px viewport was checked for horizontal document overflow. Canvas annotation still requires pointer input; this is not a full accessibility audit.

## Real photograph: cup and spoon only

The included [CC0 coffee image](../examples/ATTRIBUTION.md) comes from the internet/scikit-image. The showcase contains two classes, **cup** and **spoon**, and two separately labeled instances. Farzam corrected the mask boundaries in the application and reviewed the image. The screenshot below was captured from that saved workspace; the cup class assignment was corrected before capture. No person image or person annotation is shipped.

![Farzam's corrected and reviewed cup and spoon masks](screenshots/cup-spoon-reviewed.jpg)

A loose cup box initially misses dark cup-body pixels and includes spoon pixels. Foreground/background hints improve it. [The point-based check](../examples/validate_photo.py) verifies cup-body recovery and exclusion of a spoon-center pixel. The automated browser demonstration uses a manual polygon and brush corrections for the spoon; those initial generated masks are separate from the updated human-reviewed showcase. Occluded pixels are not invented; disconnected visible parts can remain one stored instance, which COCO RLE preserves and strict YOLO conversion flags.

There is no expert reference mask for this photograph. The current showcase is human-reviewed, while automated demonstration masks remain drafts for inspection. Neither is described as exact ground truth or a measured annotation-speed benchmark.

## Distribution

The wheel/source distribution include the static GUI. A self-contained Windows x64 package is built with PyInstaller and exercised through the full general browser workflow, including magnetic selection and both exports. No Python installation or network calls are needed to run that package. Its executable is unsigned.

Rebuild from a Windows development environment with `powershell -File packaging/build-windows.ps1`. Packaging excludes environments, SQLite workspaces, private/user images, and generated exports. The portable package includes third-party license notices.

Not exercised: macOS, YOLO training, GPU/SAM inference, large-scale datasets, or multi-user operation. Dataset quality remains dependent on human review and an appropriate split.

## Object detection — 0.3.0

Backend checks cover task migration and locking, native box validation (including nonfinite/out-of-bounds/zero-size values), schema separation, stale saves, dataset isolation, reviewed negatives, draft exclusion, normalized five-column YOLO rows, and native COCO box/area records without segmentation.

Run `node tests/detection-browser.cjs` against a fresh workspace on port 8769 (`BASE_URL` overrides it). It creates its own detection dataset and uses real mouse input to draw reversed rectangles, move and resize boxes, undo edits, pan with the right button, relabel, clear review through editing, switch task without changing existing annotations, reload saved objects, and download YOLO and COCO ZIPs. It captures the actual coffee and cat workspace screenshots and records results in `docs/detection-ui-result.json`.

The 0.3.0 Windows portable executable passed the same detection browser workflow on port 8768, including both ZIP downloads and zero page errors. The archive passed CRC validation and contains no SQLite annotation databases. Existing segmentation smoke checks also passed after the task selector was added.
