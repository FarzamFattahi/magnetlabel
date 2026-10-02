"""Collect installed distribution notices for the portable binary's dependencies."""

import shutil
import sys
from importlib import metadata
from pathlib import Path

target = Path("dist/MagnetLabel/THIRD-PARTY-LICENSES")
target.mkdir(parents=True, exist_ok=True)
names = [
    "fastapi",
    "starlette",
    "uvicorn",
    "opencv-python-headless",
    "numpy",
    "Pillow",
    "python-multipart",
    "PyYAML",
    "pydantic",
    "pydantic-core",
    "annotated-types",
    "typing-extensions",
    "typing-inspection",
    "anyio",
    "idna",
    "sniffio",
    "h11",
    "click",
    "setuptools",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "packaging",
    "httpx",
    "httpcore",
    "certifi",
    "annotated-doc",
    "opentelemetry-api",
    "importlib-metadata",
    "zipp",
]
versions = []
for name in names:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        continue
    versions.append(f"{name}=={dist.version}")
    for file in dist.files or []:
        if file.name.lower().startswith(("license", "licence", "copying", "copyright", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                destination = target / name / str(file).replace("..", "_")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
runtime_license = Path(sys.base_prefix) / "LICENSE.txt"
if runtime_license.is_file():
    shutil.copy2(runtime_license, target / "Python-LICENSE.txt")
(target / "DISTRIBUTIONS.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")
