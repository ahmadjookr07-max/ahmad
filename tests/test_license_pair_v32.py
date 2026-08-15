from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engine_v2 import license_v2 as lv  # noqa: E402


def main() -> None:
    # زوج مفاتيح تجريبي مستقل يحاكي برنامج المالك والتطبيق.
    private_key, public_key = lv.generate_owner_keypair()
    key = lv.make_activation_key(private_key, "A1-B2-C3-D4", "yearly", 30)

    original = (lv.OWNER_PUBLIC_KEY_B64, lv.OWNER_PQC_PUBLIC_KEY_B64,
                lv.machine_fingerprint, lv._license_dir)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            lv.OWNER_PUBLIC_KEY_B64 = public_key
            lv.OWNER_PQC_PUBLIC_KEY_B64 = ""
            lv._license_dir = lambda: Path(tmp)
            lv.machine_fingerprint = lambda: "A1-B2-C3-D4"
            accepted = lv.activate_with_key(key)
            assert "مرفوض" not in accepted.status, accepted.status

            # المفتاح نفسه يجب ألا يقبل على جهاز ثانٍ.
            lv.machine_fingerprint = lambda: "E5-F6-G7-H8"
            rejected = lv.activate_with_key(key)
            assert "جهاز آخر" in rejected.status, rejected.status
        finally:
            (lv.OWNER_PUBLIC_KEY_B64, lv.OWNER_PQC_PUBLIC_KEY_B64,
             lv.machine_fingerprint, lv._license_dir) = original
    print("OK: signature accepted on matching device; rejected on other device")


if __name__ == "__main__":
    main()
