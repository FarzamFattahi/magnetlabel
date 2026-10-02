# Existing tools and the project decision

Research checked against primary project documentation on 2 October 2026. The underlying idea is practical but already established. Magnetic edge tracing is commonly called **Intelligent Scissors** or **live-wire**; model-assisted selection is a separate family of tools.

| Tool | Documented capabilities relevant here | What MagnetLabel focuses on |
| --- | --- | --- |
| [CVAT](https://docs.cvat.ai/docs/annotation/auto-annotation/ai-tools/) | OpenCV intelligent scissors, AI interactors, positive/negative points, detectors and tracking; [multiple dataset formats](https://docs.cvat.ai/docs/manual/advanced/formats/) | A small, single-user Python installation and one focused segmentation workflow |
| [Labelme](https://github.com/wkentaro/labelme) | Python image annotation, polygon and other shape types, AI-assisted annotation | Browser canvas, direct mask correction, review state and paired YOLO/COCO export with exact masks |
| [Label Studio](https://labelstud.io/guide/ml_tutorials/segment_anything_model) | Interactive SAM integration through an ML backend, including point/rectangle prompts and mask output | CPU-only assistance out of the box, without deploying an ML backend or obtaining model weights |
| [Ultralytics annotation editor](https://docs.ultralytics.com/platform/data/annotation) | Polygon labeling and SAM-powered smart annotation, integrated with dataset/training workflows | Local files, no platform account, explicit topology checks on export |

These are mature projects and may be better choices for teams, model-assisted annotation, or large-scale work. MagnetLabel does not claim superior segmentation accuracy or measured labeling speed. Its portfolio value is a clear, inspectable implementation of a complete local annotation-to-dataset workflow, with careful conversion and persistence tests.

## What was adopted

1. Prompt the user for the class vocabulary before their first import, preserving class IDs once masks exist.
2. Separate a temporary selection from an added object, making review explicit.
3. Let users choose box assistance, coarse polygon/freehand region refinement, edge-following outlines, or manual polygons, then correct pixels directly.
4. Preserve exact masks and treat polygon conversion as potentially lossy. Warn or refuse rather than silently changing holes or instance identity.
5. Exclude unfinished/unreviewed images from training exports and support explicit negative examples.

## Algorithms and formats

- [OpenCV GrabCut](https://docs.opencv.org/4.13.0/dd/dfc/tutorial_js_grabcut.html) models foreground/background appearance and applies graph cuts. It can be guided by definite foreground/background samples. It does not understand class names or recognize objects semantically.
- [OpenCV Intelligent Scissors](https://docs.opencv.org/4.12.0/df/d6b/classcv_1_1segmentation_1_1IntelligentScissorsMB.html) extracts image features, builds a shortest-path map from an anchor, and retrieves an edge-following contour to a target. The user still places anchors around the intended object.
- [Ultralytics segmentation format](https://docs.ultralytics.com/datasets/segment/) uses one normalized polygon row per object and a YAML class/split configuration.
- [COCO API](https://github.com/cocodataset/cocoapi) supports masks with run-length encoding. Uncompressed RLE in this implementation is deliberately inspectable and retains holes/disconnected regions.

The distinction matters: an approximate box invokes GrabCut to estimate a region; a magnetic outline snaps the path *between anchors* to edges. Neither classical method guarantees the exact semantic object boundary from an arbitrary loose selection. The real-photo test documents that limitation, and optional SAM integration remains future work.
