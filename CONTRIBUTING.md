# Contributing

Install the `dev` extras in a virtual environment and run pytest plus Ruff before submitting a change. Python code lives under `src/magnetlabel`; the frontend lives under `src/magnetlabel/static` and needs no build tool.

Keep dataset guarantees explicit: never silently remap class IDs, drop objects, change topology, or include unreviewed images. Export tests should inspect the archive and recover masks rather than merely checking for a successful response. Browser checks should verify real interaction and downloaded bytes.

Use synthetic images or images with documented redistribution permission in tests. Do not commit project databases, user datasets, downloaded model weights, credentials, or generated export archives. Explain any schema or format changes and update the validation notes.

For a bug report, include OS/Python/browser versions, tool/steps used, image dimensions, the visible error, and a minimal image you have permission to share. Avoid sharing private datasets.
