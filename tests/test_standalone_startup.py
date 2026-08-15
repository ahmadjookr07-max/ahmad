from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows_app"))
import native_app_v2  # noqa: E402


def main() -> None:
    class _Window:
        def __init__(self, marker):
            self.marker = marker

    fake_module = SimpleNamespace(MainWindow=_Window)
    closed = []
    original_close = native_app_v2._close_splash
    try:
        native_app_v2._close_splash = lambda: closed.append(True)
        native_app_v2._gate_startup(fake_module)
        instance = fake_module.MainWindow("started")
        assert instance.marker == "started"
        assert closed == [True]
    finally:
        native_app_v2._close_splash = original_close
    print("OK: standalone startup bypasses licensing")


if __name__ == "__main__":
    main()
