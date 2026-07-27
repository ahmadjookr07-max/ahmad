"""Tests: session save/resume + WebP max-quality verification."""
import sys, os, json, shutil
sys.path.insert(0, "/home/ubuntu/v2_project/v2")

from engine_v2.session_v2 import SessionStore, SessionState

D = "/home/ubuntu/v2_project/tmp_sessions"
if os.path.isdir(D):
    shutil.rmtree(D)

store = SessionStore(D)
s = store.new_session("/photos", "/items.xlsx", "/out")
sid = s.session_id
store.upsert_image("a.jpg", source_path="a.jpg", status="matched",
                   barcode="628", item_code="10001043", sequence=1)
store.upsert_image("b.jpg", source_path="b.jpg", status="done",
                   item_code="10001043", sequence=2,
                   nutrition_mode="rebuild",
                   nutrition_values={"calories": "135"})
store.set_position(7)
store.save(force=True)

# simulate app restart
store2 = SessionStore(D)
lst = store2.list_sessions()
assert len(lst) == 1 and lst[0]["total"] == 2 and lst[0]["done"] == 1
s2 = store2.load(sid)
assert s2.current_position == 7
assert s2.images["b.jpg"].nutrition_values == {"calories": "135"}
assert s2.images["a.jpg"].item_code == "10001043"
print("session save/resume OK:", lst[0])

# ---- WebP quality verification on an existing V2 output
import cv2
import numpy as np
out = "/home/ubuntu/v2_project/v2_out/rebuild/10009999_حبه.webp"
img = cv2.imdecode(np.fromfile(out, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
print("webp size:", img.shape, "file KB:", os.path.getsize(out) // 1024)
# lossless check: re-encode lossless and compare pixels
ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 101])
img2 = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
assert np.array_equal(img, img2), "lossless roundtrip mismatch"
print("WebP lossless roundtrip OK")
shutil.rmtree(D)
print("ALL OK")
