"""تحقق يدوي سريع من ترحيل أسماء 2.9.12 (بلا رقم ثم 1، 2، 3).

يُشغَّل: ``python3 tools/تحقق_الترحيل.py``
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import engine_v2.naming_v2 as nv  # noqa: E402


def _mk(names: list[str]) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp()) / "مخرجات"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"x")
    return d


def _names(d: pathlib.Path) -> list[str]:
    return sorted(p.name for p in d.glob("*.webp"))


def case(title: str, names: list[str], expect: list[str],
         should_migrate: bool = True) -> bool:
    d = _mk(names)
    needs = nv.folder_needs_dash_migration(d)
    res = nv.migrate_legacy_dash_names(d)
    got = _names(d)
    ok = got == sorted(expect) and needs == should_migrate
    print(f"[{'نجح' if ok else 'فشل'}] {title}")
    if not ok:
        print(f"    يحتاج ترحيل: {needs} (المتوقع {should_migrate})")
        print(f"    الناتج : {got}")
        print(f"    المتوقع: {sorted(expect)}")
        print(f"    التفصيل: {res}")
    return ok


def main() -> int:
    results = [
        case("سلسلة كاملة 2،3،4 تنزل إلى 1،2،3",
             ["10001099_حبه.webp", "10001099_حبه-2.webp",
              "10001099_حبه-3.webp", "10001099_حبه-4.webp"],
             ["10001099_حبه.webp", "10001099_حبه-1.webp",
              "10001099_حبه-2.webp", "10001099_حبه-3.webp"]),
        case("صنفان مستقلان",
             ["10001099_حبه.webp", "10001099_حبه-2.webp",
              "10002200_كرتون.webp", "10002200_كرتون-2.webp"],
             ["10001099_حبه.webp", "10001099_حبه-1.webp",
              "10002200_كرتون.webp", "10002200_كرتون-1.webp"]),
        case("مجلد بالاصطلاح الجديد أصلًا لا يُمسّ",
             ["10001099_حبه.webp", "10001099_حبه-1.webp",
              "10001099_حبه-2.webp"],
             ["10001099_حبه.webp", "10001099_حبه-1.webp",
              "10001099_حبه-2.webp"],
             should_migrate=False),
        case("مجلد بلا أرقام إطلاقًا",
             ["10001099_حبه.webp", "10002200_كرتون.webp"],
             ["10001099_حبه.webp", "10002200_كرتون.webp"],
             should_migrate=False),
        case("وحدة مركّبة (join_all)",
             ["10011205_حبه_شدة_كرتون.webp",
              "10011205_حبه_شدة_كرتون-2.webp",
              "10011205_حبه_شدة_كرتون-3.webp"],
             ["10011205_حبه_شدة_كرتون.webp",
              "10011205_حبه_شدة_كرتون-1.webp",
              "10011205_حبه_شدة_كرتون-2.webp"]),
    ]

    # تحقق round-trip بين البناء والقراءة
    rt_ok = True
    for seq in range(1, 8):
        stem = nv.build_name_dash("10001099", seq, "حبه")
        parsed = nv.parse_name(stem)
        if not parsed or parsed.seq != seq:
            rt_ok = False
            print(f"[فشل] round-trip seq={seq} -> {stem} -> {parsed}")
    print(f"[{'نجح' if rt_ok else 'فشل'}] round-trip البناء/القراءة")
    results.append(rt_ok)

    print()
    if all(results):
        print("كل اختبارات الترحيل نجحت.")
        return 0
    print("توجد اختبارات فاشلة.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
