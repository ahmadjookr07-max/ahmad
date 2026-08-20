from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from framing_zoom_patch import ProductFrame, frame_product, save_framed_image  # noqa: E402


def _bounds(image: np.ndarray) -> tuple[int, int, int, int]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(gray < 245)
    assert len(xs) > 0
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def run() -> None:
    image = np.full((700, 800, 3), 255, np.uint8)
    # منتج منحاز عمدًا إلى اليسار وبمساحة بيضاء واسعة.
    cv2.rectangle(image, (90, 185), (350, 585), (70, 115, 175), -1)

    centered = frame_product(image, ProductFrame(zoom_percent=106))
    x0, y0, x1, y1 = _bounds(centered)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert abs(cx - 399.5) <= 3 and abs(cy - 349.5) <= 3, (cx, cy)
    assert x0 > 1 and y0 > 1 and x1 < 798 and y1 < 698, (x0, y0, x1, y1)
    assert (x1 - x0) > 260 and (y1 - y0) > 400, (x0, y0, x1, y1)

    shifted = frame_product(image, ProductFrame(zoom_percent=106, offset_x_percent=12))
    sx0, sy0, sx1, sy1 = _bounds(shifted)
    assert (sx0 + sx1) / 2 > cx + 20, ((sx0 + sx1) / 2, cx)
    assert sy0 > 1 and sy1 < 698, (sy0, sy1)

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "1001_حبه.webp"
        assert cv2.imwrite(str(target), image, [cv2.IMWRITE_WEBP_QUALITY, 101])
        before = target.read_bytes()
        assert save_framed_image(target, ProductFrame(zoom_percent=112, offset_x_percent=8))
        assert target.is_file() and not list(Path(folder).glob("*.tmp*"))
        assert target.read_bytes() != before
        assert len(list(Path(folder).glob("*.webp"))) == 1

    print("OK: product auto-centered, safely zoomed, and user offset is applied/saved in-place")


if __name__ == "__main__":
    run()
