import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .server import create_app


def main():
    parser = argparse.ArgumentParser(
        description="MagnetLabel local segmentation and detection workspace"
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path.home() / ".magnetlabel",
        help="Workspace directory (default: ~/.magnetlabel)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    app = create_app(args.data)
    url = f"http://127.0.0.1:{args.port}"
    print(f"MagnetLabel • {url}\nProject: {args.data.resolve()}")
    if not args.no_browser:
        timer = threading.Timer(1.2, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
