from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from native_app import MainWindow
from engine_v2.state_sync_v2 import sync_removed_outputs


class GuardHarness:
    _remember_deleted_result_items = MainWindow._remember_deleted_result_items
    _drop_deleted_result_items = MainWindow._drop_deleted_result_items

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._deleted_result_path_keys = set()
        self._deleted_result_source_names = set()

    def _result_path(self, raw: str):
        p = Path(raw)
        return p if p.is_absolute() else self.workspace / p

    @staticmethod
    def _norm_path_key(path):
        return MainWindow._norm_path_key(path)


def run() -> None:
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        base = ws / "100_حبه.webp"
        nutrition = ws / "100_حبه-1.webp"
        base.write_bytes(b"base")
        nutrition.write_bytes(b"nutrition")
        payload = {"result": {"items": [
            {"source_name": "source.jpg", "output_path": base.name,
             "review_path": base.name},
            {"source_name": "source.jpg", "output_path": nutrition.name,
             "review_path": nutrition.name, "match_source": "nutrition_crop"},
        ]}}
        (ws / "job_state.json").write_text(json.dumps(payload), encoding="utf-8")

        # حذف اقتصاص التغذية لا يحذف صورة الصنف التي تشترك في source_name.
        report = sync_removed_outputs(ws, source_names={"source.jpg"},
                                      output_paths={str(nutrition)})
        assert report["written"] and report["removed"] == 1, report
        saved = json.loads((ws / "job_state.json").read_text(encoding="utf-8"))
        assert [x["output_path"] for x in saved["result"]["items"]] == [base.name]

        # لقطة عامل قديمة تحوي الاثنين: حارس الواجهة يخفي المحذوف وحده.
        h = GuardHarness(ws)
        primary = SimpleNamespace(source_name="source.jpg", output_path=base.name,
                                  review_path=base.name)
        removed = SimpleNamespace(source_name="source.jpg", output_path=nutrition.name,
                                  review_path=nutrition.name)
        _, paths = h._remember_deleted_result_items([removed])
        assert str(nutrition) in paths
        kept = h._drop_deleted_result_items([primary, removed])
        assert kept == [primary], kept
    print("OK: deleted nutrition row cannot return and shared product remains")


if __name__ == "__main__":
    run()
