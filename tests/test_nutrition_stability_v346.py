from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from native_app import MainWindow
from engine_v2.state_sync_v2 import sync_result_items


@dataclass(frozen=True)
class FrozenResult:
    items: tuple


class NutritionHarness:
    _remember_nutrition_result_item = MainWindow._remember_nutrition_result_item
    _restore_nutrition_result_items = MainWindow._restore_nutrition_result_items
    _insert_item_beside_group = MainWindow._insert_item_beside_group

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._nutrition_result_items = {}

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
        (ws / "job_state.json").write_text(json.dumps({"result": {"items": []}}), encoding="utf-8")
        primary = SimpleNamespace(source_name="source.jpg", source_path="source.jpg",
                                  status="matched", item_code="100", product_name="منتج",
                                  barcode="628", confidence=1.0, explanation="",
                                  output_path=base.name, review_path=base.name,
                                  match_source="catalog")
        nutrition_item = SimpleNamespace(source_name=nutrition.name, source_path="source.jpg",
                                         status="manual", item_code="100", product_name="منتج",
                                         barcode="628", confidence=1.0, explanation="حقائق التغذية",
                                         output_path=nutrition.name, review_path=nutrition.name,
                                         match_source="nutrition_crop")

        # تكتب القائمة الكاملة إلى الحالة الذرية، لا تبقى التغذية في الذاكرة فقط.
        report = sync_result_items(ws, [primary, nutrition_item])
        assert report["written"] and report["count"] == 2, report
        saved = json.loads((ws / "job_state.json").read_text(encoding="utf-8"))
        assert len(saved["result"]["items"]) == 2

        # عامل قديم يعيد primary فقط؛ الحجز يعيد nutrition بعد نفس الصنف.
        h = NutritionHarness(ws)
        h._remember_nutrition_result_item(nutrition_item)
        restored = h._restore_nutrition_result_items([primary])
        assert restored == [primary, nutrition_item], restored

        # الإدراج لا يعتمد على list mutable داخل BatchRunResult.
        h.current_result = FrozenResult(items=(primary,))
        h._insert_item_beside_group(nutrition_item)
        assert list(h.current_result.items) == [primary, nutrition_item], h.current_result.items

        nutrition.unlink()
        vanished = h._restore_nutrition_result_items([primary])
        assert vanished == [primary], vanished
    print("OK: nutrition result persists across stale worker refreshes and sessions")


if __name__ == "__main__":
    run()
