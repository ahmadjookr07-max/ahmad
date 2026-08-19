from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
from per_image_unit_patch import _apply_unit


@dataclasses.dataclass(frozen=True)
class _Item:
    item_code: str
    output_path: str
    review_path: str = ""
    source_path: str = ""
    source_name: str = ""
    match_source: str = "batch"


class _Window:
    def __init__(self, root: Path, items):
        self.current_workspace = root
        self.current_result = SimpleNamespace(items=items)
        self.rebuilt = 0
        self.saved = 0

    def _result_path(self, path):
        return self.current_workspace / str(path)

    def _capture_results_position(self):
        return None

    def _populate_results(self, **kwargs):
        self.rebuilt += 1

    def v2_save_session(self):
        self.saved += 1


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "10000001_حبه.webp"
        second = root / "10000001_حبه-1.webp"
        first.write_bytes(b"front")
        second.write_bytes(b"back")
        items = [_Item("10000001", first.name), _Item("10000001", second.name)]
        window = _Window(root, items)
        assert _apply_unit(window, items[1], "كرتون")
        assert first.is_file()
        carton = root / "10000001_كرتون.webp"
        assert carton.is_file() and carton.read_bytes() == b"back"
        assert not second.exists()
        names = [item.output_path for item in window.current_result.items]
        assert first.name in names and carton.name in names, names
        assert window.rebuilt == 1 and window.saved == 1
    print("OK: per-image unit change preserves other units and saves session")


if __name__ == "__main__":
    run()
