# -*- coding: utf-8 -*-
"""
CLI entry for the AP prototype observatory.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

from ._app import ObservatoryApp
from ._web import run_observatory_web


def _ensure_utf8_stdio() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> None:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="AP Observatory")
    parser.add_argument("--mode", choices=["web", "cli"], default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    app = ObservatoryApp()
    mode = args.mode or str(app._config.get("default_launch_mode", "web")).strip().lower()
    if mode == "cli":
        app.loop()
        return

    run_observatory_web(
        app,
        host=args.host or str(app._config.get("web_host", "127.0.0.1")),
        port=int(args.port or app._config.get("web_port", 8765)),
        open_browser=not args.no_browser and bool(app._config.get("web_auto_open_browser", True)),
    )


if __name__ == "__main__":
    main()
