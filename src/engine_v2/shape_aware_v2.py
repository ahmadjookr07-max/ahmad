# -*- coding: utf-8 -*-
"""shape_aware_v2 — تمييز شكل المنتج والإكمال الذكي للنواقص.

## سبب وجود الوحدة (قياس على صور المالك الحقيقية)
سبع صور منجزة (800×700، خلفية بيضاء) قِيست فوجد فيها:

| الصنف | ثقوب | أكبر ثقب | حافة داكنة% |
| --- | --- | --- | --- |
| 10000002_حبه | 9 | 192 | 18.6 |
| 10000017_حبه | 0 | 21 | **22.3** |
| 10000064_حبه | 3 | 528 | 21.2 |
| 10000111_حبه-3 | 6 | 614 | 20.2 |
| 10000111_حبه-4 | 7 | **1046** | 13.2 |

**والكشف الأهم**: كيس الموزاريلا 10000017 خرج من العزل **كتلتين
منفصلتين تمامًا** — يسرى فيها الباركود ويمنى فيها النص — لأن
البلاستيك الشفاف وسط الكيس مرّر الخلفية البيضاء فرآه ISNet خلفية.
ولذلك «0 ثقوب» رغم العطب الفاحش: الفراغ ليس ثقبًا مغلقًا بل فصلٌ
كامل. وأي معالجة تستدعي «أكبر مكوّن» **تُسقط نصف الكيس** بلا أن
تشعر.

## المبدأ: الإكمال يفهم الشكل قبل أن يُكمل
1. **توحيد كتل المنتج** قبل أي شيء (`unify_product_blocks`)
2. **تمييز الشكل** من الهندسة: bag/box/bottle/pouch/unknown
3. **قواعد إكمال حسب الشكل** (العلبة حدّها مستقيم فنتساهل، الكيس
   محدّب فنتحفّظ، القنينة متناظرة فنستعمل المرآة)
4. **ردم بالنسيج** (`inpaint`) لا بلون مسطّح
5. **تقليم الشوائب الحافية المتصلة** — لا البقع الصغيرة وحدها،
   فالقياس أثبت أن العطب شريط ممتدّ من الطاولة ومكان التصوير
6. **حرس صارم**: سقف نمو، وسقف حجم فراغ، وتقرير شفاف لكل خطوة
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

__all__ = [
    "ShapeInfo",
    "CompletionReport",
    "mask_from_white",
    "unify_product_blocks",
    "classify_shape",
    "complete_product",
]


# ═══════════════════════════ أنواع البيانات ═══════════════════════════

@dataclass
class ShapeInfo:
    """وصف هندسي لشكل المنتج — أساس قرارات الإكمال."""

    kind: str = "unknown"          # bag|box|bottle|pouch|unknown
    confidence: float = 0.0
    solidity: float = 0.0          # المساحة ÷ مساحة المحدّب
    extent: float = 0.0            # المساحة ÷ مساحة الحاضن
    aspect: float = 0.0            # العرض ÷ الطول
    corners: int = 0
    v_symmetry: float = 0.0        # تناظر رأسي
    neck_ratio: float = 1.0
    reason: str = ""


@dataclass
class CompletionReport:
    """تقرير شفاف لما جرى — لا صندوق أسود."""

    shape: ShapeInfo = field(default_factory=ShapeInfo)
    blocks_merged: int = 0
    bridged_px: int = 0
    holes_filled: int = 0
    holes_area: int = 0
    slits_filled: int = 0
    slits_area: int = 0
    edge_trimmed: int = 0
    symmetry_used: bool = False
    grew_pct: float = 0.0
    applied: bool = False
    notes: list[str] = field(default_factory=list)


# ═══════════════════════ استخراج القناع من الأبيض ═══════════════════════

def mask_from_white(image_bgr: np.ndarray, tol: int = 12,
                    close_px: int = 3) -> np.ndarray:
    """قناع المنتج من صورة منجزة بخلفية بيضاء.

    الصور المنجزة لا تحتفظ بألفا، فالقناع يُستخرج من الانحراف عن
    الأبيض. ونستعمل **أقصى انحراف في القنوات الثلاث** لا المتوسط:
    فالمنتج الأبيض الفاتح (علبة لبن) ينحرف قليلًا في قناة واحدة على
    الأقل، بخلاف الخلفية المصنّعة (255,255,255) بالضبط.

    قياس على صور المالك: نسبة المنتج خرجت 33–49% في السبع كلها —
    قيم منطقية تُثبت صلاحية الطريقة.
    """
    d = 255 - image_bgr.astype(np.int16)
    dev = d.max(axis=2)
    m = (dev > tol).astype(np.uint8)
    if close_px > 0:
        k = np.ones((close_px, close_px), np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    return m


def _largest_component(mask: np.ndarray) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return mask
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (lab == i).astype(np.uint8)


# ═══════════════════ توحيد كتل المنتج الواحد المقسوم ═══════════════════

def unify_product_blocks(mask: np.ndarray,
                         min_share: float = 0.12,
                         max_gap_ratio: float = 0.22,
                         overlap_min: float = 0.45,
                         max_inflate: float = 1.25,
                         ) -> tuple[np.ndarray, int, int, np.ndarray]:
    """يوحّد كتل المنتج الواحد المقسوم ويجسر الفراغ بينها.

    ## سبب وجود الدالة (قياس 10000017_حبه)
    الكيس خرج كتلتين منفصلتين، والفراغ بينهما يمتدّ من أعلى القناع
    إلى أسفله فلا يُحصى «ثقبًا»، و«أكبر مكوّن» يُسقط نصف الكيس.

    ## المعيار: التراصف لا القرب وحده
    كتلتان من منتج واحد **تتقاسمان مدى الصفوف أو الأعمدة** بنسبة
    عالية، والفجوة بينهما ضيّقة نسبةً لبعد المنتج. وكتلتان من
    منتجين مختلفين (صورة فيها منتجان) لا تتراصفان بهذه الدرجة أو
    تفصلهما فجوة واسعة.

    يعيد `(mask_out, blocks_merged, bridged_px, bridge_mask)`.
    و`bridge_mask` هو البكسلات المُستحدَثة بالجسر — تُردم بالنسيج
    لاحقًا، وإلا بقيت بيضاء داخل قناع المنتج (كشفه القياس).
    """
    m = (mask > 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 2:
        return m, 0, 0, np.zeros_like(m)

    areas = stats[1:, cv2.CC_STAT_AREA]
    main = 1 + int(np.argmax(areas))
    main_area = int(stats[main, cv2.CC_STAT_AREA])
    mx = int(stats[main, cv2.CC_STAT_LEFT])
    my = int(stats[main, cv2.CC_STAT_TOP])
    mw = int(stats[main, cv2.CC_STAT_WIDTH])
    mh = int(stats[main, cv2.CC_STAT_HEIGHT])

    keep = (lab == main)
    merged = 0
    for i in range(1, n):
        if i == main:
            continue
        if int(stats[i, cv2.CC_STAT_AREA]) < main_area * min_share:
            continue                      # بقعة تائهة لا كتلة منتج
        cx = int(stats[i, cv2.CC_STAT_LEFT])
        cy = int(stats[i, cv2.CC_STAT_TOP])
        cw = int(stats[i, cv2.CC_STAT_WIDTH])
        ch = int(stats[i, cv2.CC_STAT_HEIGHT])

        row_ov = min(my + mh, cy + ch) - max(my, cy)
        row_share = row_ov / float(max(1, min(mh, ch)))
        col_ov = min(mx + mw, cx + cw) - max(mx, cx)
        col_share = col_ov / float(max(1, min(mw, cw)))

        gap_x = max(0, max(mx, cx) - min(mx + mw, cx + cw))
        gap_y = max(0, max(my, cy) - min(my + mh, cy + ch))

        side_by_side = (row_share >= overlap_min
                        and gap_x <= mw * max_gap_ratio)
        stacked = (col_share >= overlap_min
                   and gap_y <= mh * max_gap_ratio)
        if side_by_side or stacked:
            keep |= (lab == i)
            merged += 1

    out = keep.astype(np.uint8)
    if merged == 0:
        return out, 0, 0, np.zeros_like(m)

    # جسر الفراغ بنواتين رقيقتين موجّهتين لا بنواة مربعة كبيرة:
    # المربعة تنفخ الحدّ الخارجي وتشوّه شكل الكيس.
    before = int(out.sum())
    ys, xs = np.where(out > 0)
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    kx = max(3, int(bw * 0.08) | 1)
    ky = max(3, int(bh * 0.08) | 1)
    bridged = cv2.morphologyEx(out, cv2.MORPH_CLOSE,
                               np.ones((3, kx), np.uint8))
    bridged = cv2.morphologyEx(bridged, cv2.MORPH_CLOSE,
                               np.ones((ky, 3), np.uint8))
    bridge_mask = np.zeros_like(m)
    if int(bridged.sum()) <= before * max_inflate:
        bridge_mask = ((bridged > 0) & (out == 0)).astype(np.uint8)
        out = bridged
    return out, merged, int(out.sum()) - before, bridge_mask


# ═══════════════════════════ تمييز الشكل ═══════════════════════════

def classify_shape(mask: np.ndarray) -> ShapeInfo:
    """يميّز شكل المنتج من هندسة قناعه.

    الإشارات كلها **نسبية لا مطلقة** فتصلح لأي مقاس صورة. وعند
    الشك يُرجَع `unknown` لتكون المعالجة أضعف تدخّلًا — فإفساد
    منتج سليم أسوأ من ترك نقصٍ فيه.

    عتبة `bag` أُنزلت إلى 0.72 بعد أن خرجت صورة مجعّدة للمالك
    بتحدّب 0.76 فصُنّفت `unknown` خطأً.
    """
    info = ShapeInfo()
    m = (mask > 0).astype(np.uint8)
    if not m.any():
        info.reason = "قناع فارغ"
        return info

    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        info.reason = "لا محيط"
        return info
    c = max(cnts, key=cv2.contourArea)
    area = float(cv2.contourArea(c))
    if area < 100:
        info.reason = "محيط ضئيل"
        return info

    x, y, w, h = cv2.boundingRect(c)
    hull_area = float(cv2.contourArea(cv2.convexHull(c))) or 1.0
    info.solidity = area / hull_area
    info.extent = area / float(max(1, w * h))
    info.aspect = w / float(max(1, h))

    peri = cv2.arcLength(c, True)
    info.corners = len(cv2.approxPolyDP(c, 0.02 * peri, True))

    sub = m[y:y + h, x:x + w]
    if sub.shape[1] >= 4:
        half = sub.shape[1] // 2
        left = sub[:, :half]
        right = np.fliplr(sub[:, sub.shape[1] - half:])
        inter = np.logical_and(left, right).sum()
        union = np.logical_or(left, right).sum()
        info.v_symmetry = inter / max(1, union)

    widths = sub.sum(axis=1)
    nz = np.flatnonzero(widths)
    if nz.size >= 6:
        top = widths[nz[0]:nz[0] + max(3, len(nz) // 3)]
        top = top[top > 0]
        if top.size:
            info.neck_ratio = float(top.min()) / float(max(1, widths.max()))

    # قنينة: عنق أضيق بوضوح + طولية + تناظر معتبر.
    # عتبة التناظر 0.80 لا 0.86: القياس أثبت **دائرية منطقية** —
    # القطع الذي نريد إكماله بالتناظر هو نفسه ما يخفض التناظر
    # (قنينة مقطوعة الجانب أعطت 0.8558 فسقطت دون 0.86 بفارق
    # 0.0042 رغم أن العنق 0.30 والنسبة 0.42 قاطعتان).
    if (info.v_symmetry >= 0.80 and info.neck_ratio <= 0.62
            and info.aspect <= 0.85):
        info.kind = "bottle"
        info.confidence = min(1.0, info.v_symmetry)
        info.reason = (f"تناظر {info.v_symmetry:.2f} · عنق "
                       f"{info.neck_ratio:.2f} · نسبة {info.aspect:.2f}")
        return info

    # علبة/كرتون: تحدّب عالٍ + امتلاء حاضن عالٍ + زوايا قليلة
    if info.solidity >= 0.94 and info.extent >= 0.80 and info.corners <= 8:
        info.kind = "box"
        info.confidence = min(1.0, info.solidity)
        info.reason = (f"تحدّب {info.solidity:.2f} · امتلاء "
                       f"{info.extent:.2f} · زوايا {info.corners}")
        return info

    if info.aspect >= 1.15 and info.solidity >= 0.84:
        info.kind = "pouch"
        info.confidence = 0.72
        info.reason = (f"نسبة {info.aspect:.2f} · تحدّب "
                       f"{info.solidity:.2f}")
        return info

    if 0.72 <= info.solidity < 0.98 and info.extent >= 0.50:
        info.kind = "bag"
        info.confidence = 0.68
        info.reason = (f"تحدّب {info.solidity:.2f} · امتلاء "
                       f"{info.extent:.2f} · زوايا {info.corners}")
        return info

    info.kind = "unknown"
    info.confidence = 0.30
    info.reason = (f"لا قاعدة تنطبق (تحدّب {info.solidity:.2f} · "
                   f"امتلاء {info.extent:.2f} · نسبة {info.aspect:.2f})")
    return info


# ═════════════════════ كشف الفراغات والشقوق ═════════════════════

def _closed_holes(mask: np.ndarray) -> np.ndarray:
    """الثقوب المغلقة تمامًا داخل المنتج."""
    h, w = mask.shape[:2]
    ff = mask.copy()
    pad = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, pad, (0, 0), 1)
    return (ff == 0).astype(np.uint8)


def _edge_slits(mask: np.ndarray, min_len_ratio: float = 0.18,
                max_width_ratio: float = 0.16) -> np.ndarray:
    """الشقوق المتصلة بحافة المنتج — لا يراها كشف الثقوب المغلقة.

    التعريف: فراغ **داخل** المستطيل المحصور للمنتج، طوله معتبر
    نسبةً لبعد المنتج، وعرضه صغير، ومحاط بالمنتج من جانبين
    متقابلين.
    """
    m = (mask > 0).astype(np.uint8)
    ys, xs = np.where(m > 0)
    if xs.size == 0:
        return np.zeros_like(m)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1

    inside = np.zeros_like(m)
    inside[y0:y1 + 1, x0:x1 + 1] = 1
    gap = ((inside > 0) & (m == 0)).astype(np.uint8)
    if not gap.any():
        return np.zeros_like(m)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(gap, 8)
    out = np.zeros_like(m)
    for i in range(1, n):
        gx = int(stats[i, cv2.CC_STAT_LEFT])
        gy = int(stats[i, cv2.CC_STAT_TOP])
        gw = int(stats[i, cv2.CC_STAT_WIDTH])
        gh = int(stats[i, cv2.CC_STAT_HEIGHT])

        vert = (gh >= bh * min_len_ratio and gw <= bw * max_width_ratio)
        horz = (gw >= bw * min_len_ratio and gh <= bh * max_width_ratio)
        if not (vert or horz):
            continue

        if vert:
            lo = max(x0, gx - 6)
            hi = min(x1 + 1, gx + gw + 6)
            b1 = m[gy:gy + gh, lo:gx]
            b2 = m[gy:gy + gh, gx + gw:hi]
        else:
            b1 = m[max(y0, gy - 6):gy, gx:gx + gw]
            b2 = m[gy + gh:min(y1 + 1, gy + gh + 6), gx:gx + gw]
        if b1.size == 0 or b2.size == 0:
            continue
        if b1.mean() < 0.55 or b2.mean() < 0.55:
            continue
        out[lab == i] = 1
    return out


def _mirror_complete(mask: np.ndarray) -> np.ndarray:
    """إكمال بالتناظر الرأسي — أقوى إشارة للقنينة.

    قياس على 10000111: أضاف 7143 بكسل فاكتمل الجانب الأيمن
    المقطوع، ونزلت الحافة الداكنة من 17.6% إلى 10.6%.
    """
    m = (mask > 0).astype(np.uint8)
    ys, xs = np.where(m > 0)
    if xs.size == 0:
        return m
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    sub = m[y0:y1 + 1, x0:x1 + 1]
    out = m.copy()
    out[y0:y1 + 1, x0:x1 + 1] = np.maximum(sub, np.fliplr(sub))
    return out


# ═══════════════ تقليم الشوائب الحافية المتصلة (م-24) ═══════════════

def trim_edge_debris(image_bgr: np.ndarray, mask: np.ndarray,
                     band_px: int = 14,
                     color_gap: int = 46,
                     max_trim_pct: float = 4.0,
                     ) -> tuple[np.ndarray, int]:
    """يقلّم شوائب الخلفية ومكان التصوير الملتصقة بحافة المنتج.

    ## لماذا لا يكفي حذف البقع الصغيرة
    القياس الأول حذف البقع الداكنة الصغيرة المنفصلة، فارتفع مقياس
    «الحافة الداكنة%» من 24.1 إلى 32.7 على 10000017 — لأن حذف
    الصغائر يصغّر المقام أسرع من البسط، **والعطب الحقيقي شريط
    داكن ممتدّ متصل** (ظلّ الطاولة وخطوط البلاط) لا بقعًا.

    ## المعيار: انتماء اللون لا حجم البقعة
    نبني لوحة ألوان المنتج من **قلبه** (بعد تعرية عميقة)، ثم نقيس
    لكل بكسل في شريط الحافة أقرب مسافة لونية إلى تلك اللوحة. ما
    بَعُد أكثر من `color_gap` فهو شائبة دخيلة لا جزء من المنتج،
    ويُقلَّم من الحافة إلى الداخل (لا من الوسط) حفاظًا على البنية.

    يعيد `(mask_out, trimmed_px)`.
    """
    m = (mask > 0).astype(np.uint8)
    if not m.any():
        return m, 0
    base = int(m.sum())

    # ── اللوحة تُبنى من الربع المركزي لا من كل القلب ──
    # القياس كشف أن شائبة حافية سميكة (12×300) نجت من التعرية
    # فدخلت اللوحة بـ819 بكسل وتجاوزت حدّ 0.2%، فصارت «لونًا
    # شرعيًا للمنتج» ولم تُقلَّم أبدًا. والشوائب تسكن الأطراف
    # دائمًا، فالمركز أنقى مرجعٍ ممكن.
    ys_a, xs_a = np.where(m > 0)
    cy0, cy1 = int(ys_a.min()), int(ys_a.max())
    cx0, cx1 = int(xs_a.min()), int(xs_a.max())
    qh = (cy1 - cy0 + 1) // 4
    qw = (cx1 - cx0 + 1) // 4
    core = np.zeros_like(m)
    core[cy0 + qh:cy1 - qh + 1, cx0 + qw:cx1 - qw + 1] = 1
    core = ((core > 0) & (m > 0)).astype(np.uint8)
    if core.sum() < base * 0.03:
        core = cv2.erode(m, np.ones((7, 7), np.uint8))
    if not core.any():
        return m, 0

    lab_img = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    core_px = lab_img[core > 0]
    # لوحة مُختزلة بالتكميم (أسرع وأمتن من k-means على كل بكسل)
    q = (core_px / 16).astype(np.int16)
    uniq, counts = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    # حدّ 2% لا 0.2%: فلا تدخل اللوحة أقليةٌ دخيلة
    keep = counts >= max(3, int(counts.sum() * 0.02))
    palette = (uniq[keep] * 16 + 8).astype(np.float32)
    if palette.shape[0] == 0:
        palette = core_px.reshape(-1, 3)[:256]

    er = cv2.erode(m, np.ones((band_px * 2 + 1,) * 2, np.uint8))
    band = ((m > 0) & (er == 0))
    if not band.any():
        return m, 0
    ys, xs = np.where(band)
    px = lab_img[ys, xs]                       # (N,3)
    # أقرب مسافة لونية إلى اللوحة
    d = np.linalg.norm(px[:, None, :] - palette[None, :, :], axis=2)
    dmin = d.min(axis=1)

    debris = np.zeros_like(m)
    debris[ys[dmin > color_gap], xs[dmin > color_gap]] = 1
    if not debris.any():
        return m, 0

    # البذرة من شريط الحافة كله لا من المحيط الرقيق: القياس أثبت
    # أن شائبة سميكة (16px) لا تلمس المحيط المُعرّى بنواة 3×3
    # فتنجو من التقليم كلّه.
    seed = (debris > 0) & band
    if not seed.any():
        return m, 0
    n, lab, _, _ = cv2.connectedComponentsWithStats(debris, 8)
    seed_ids = set(np.unique(lab[seed]).tolist()) - {0}
    trim = np.isin(lab, list(seed_ids)).astype(np.uint8)

    cap = base * (max_trim_pct / 100.0)
    if trim.sum() > cap:
        # نُقلّم الأشدّ انحرافًا فقط حتى السقف
        order = np.argsort(-dmin)
        sel = np.zeros_like(m)
        used = 0
        for k in order:
            yy, xx = ys[k], xs[k]
            if trim[yy, xx] and not sel[yy, xx]:
                sel[yy, xx] = 1
                used += 1
                if used >= cap:
                    break
        trim = sel

    out = m.copy()
    out[trim > 0] = 0
    out = _largest_component(cv2.morphologyEx(
        out, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)))
    return out, int(trim.sum())


# ═══════════════════════════ الإكمال الرئيسي ═══════════════════════════

def complete_product(image_bgr: np.ndarray,
                     mask: np.ndarray | None = None,
                     *,
                     unify_blocks: bool = True,
                     fill_holes: bool = True,
                     fill_slits: bool = True,
                     trim_debris: bool = True,
                     use_symmetry: bool = True,
                     max_hole_ratio: float = 0.06,
                     max_grow_pct: float = 30.0,
                     inpaint_radius: int = 4,
                     white_bg: bool = True,
                     ) -> tuple[np.ndarray, np.ndarray, CompletionReport]:
    """يُكمل المنتج الناقص وَفق شكله المميَّز.

    يعيد `(image_out, mask_out, report)`.
    """
    rep = CompletionReport()
    img = image_bgr

    if mask is None:
        m = mask_from_white(img)
    elif mask.dtype != np.uint8 or mask.max() <= 1:
        m = (np.clip(mask.astype(np.float32), 0, 1) > 0.5).astype(np.uint8)
    else:
        m = (mask > 127).astype(np.uint8)

    if not m.any():
        rep.notes.append("لا منتج — لا إكمال")
        return img, m, rep

    # ── 0. توحيد الكتل قبل أي شيء (وإلا أسقطنا نصف المنتج) ──
    bridge_mask = np.zeros_like(m)
    if unify_blocks:
        m, merged, bridged, bridge_mask = unify_product_blocks(m)
        rep.blocks_merged = merged
        rep.bridged_px = bridged
        if merged:
            rep.notes.append(
                f"وُحّدت {merged} كتلة من المنتج نفسه "
                f"(جُسر {bridged} بكسل)")
    m = _largest_component(m)
    bridge_mask = ((bridge_mask > 0) & (m > 0)).astype(np.uint8)
    base_area = int(m.sum())

    shape = classify_shape(m)
    rep.shape = shape
    rep.notes.append(f"الشكل: {shape.kind} ({shape.reason})")

    new_m = m.copy()
    # بكسلات الجسر تُردم بالنسيج وإلا بقيت بيضاء داخل القناع
    to_fill = bridge_mask.copy()

    # ── 1. الثقوب المغلقة ──
    if fill_holes:
        holes = _closed_holes(m)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 8)
        cap = base_area * max_hole_ratio
        cnt = tot = 0
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            if a <= cap:
                to_fill[lab == i] = 1
                cnt += 1
                tot += a
        rep.holes_filled, rep.holes_area = cnt, tot
        if cnt:
            rep.notes.append(f"رُدم {cnt} ثقبًا مغلقًا ({tot} بكسل)")

    # ── 2. الشقوق المتصلة بالحافة (حسب الشكل) ──
    if fill_slits:
        if shape.kind == "box":
            mlr, mwr = 0.12, 0.22
        elif shape.kind in ("bag", "pouch"):
            mlr, mwr = 0.18, 0.16
        elif shape.kind == "bottle":
            mlr, mwr = 0.15, 0.20
        else:
            mlr, mwr = 0.25, 0.10          # unknown ⇒ أضعف تدخّل
        slits = _edge_slits(m, mlr, mwr)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(slits, 8)
        cap = base_area * max_hole_ratio * 2.5
        cnt = tot = 0
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            if a <= cap:
                to_fill[lab == i] = 1
                cnt += 1
                tot += a
        rep.slits_filled, rep.slits_area = cnt, tot
        if cnt:
            rep.notes.append(
                f"رُدم {cnt} شقًّا متصلًا بالحافة ({tot} بكسل)")

    new_m = np.maximum(new_m, to_fill)

    # ── 3. الإكمال بالتناظر (للقنينة وحدها) ──
    # العتبة 0.80 موحّدة مع `classify_shape` — وكانت 0.86 هنا فقط
    # فصنّفت القنينة bottle ومع ذلك لم يُستعمل التناطر (كشفه القياس).
    if use_symmetry and shape.kind == "bottle" and shape.v_symmetry >= 0.80:
        mir = _mirror_complete(new_m)
        add = int(mir.sum()) - int(new_m.sum())
        if 0 < add <= base_area * 0.12:
            to_fill = np.maximum(
                to_fill, ((mir > 0) & (new_m == 0)).astype(np.uint8))
            new_m = mir
            rep.symmetry_used = True
            rep.notes.append(f"أُكمل بالتناظر الرأسي (+{add} بكسل)")

    # ── 4. حرس النمو ──
    rep.grew_pct = (int(new_m.sum()) - base_area) / max(1, base_area) * 100
    if rep.grew_pct > max_grow_pct:
        rep.notes.append(
            f"رُفض الإكمال: نما {rep.grew_pct:.1f}% > السقف "
            f"{max_grow_pct:.0f}%")
        return img, m, rep

    # ── 5. ردم النسيج (inpaint) لا اللون المسطّح ──
    out = img.copy()
    if to_fill.any():
        fill_d = cv2.dilate(to_fill, np.ones((3, 3), np.uint8))
        out = cv2.inpaint(out, fill_d, inpaint_radius, cv2.INPAINT_TELEA)

    # ── 6. تقليم الشوائب الحافية المتصلة ──
    if trim_debris:
        trimmed_mask, trimmed = trim_edge_debris(out, new_m)
        if trimmed:
            new_m = trimmed_mask
            rep.edge_trimmed = trimmed
            rep.notes.append(f"قُلّمت شوائب حافية ({trimmed} بكسل)")

    # الخلفية بيضاء نقية خارج القناع
    if white_bg:
        out[new_m == 0] = (255, 255, 255)

    rep.applied = bool(rep.holes_filled or rep.slits_filled
                       or rep.symmetry_used or rep.edge_trimmed
                       or rep.blocks_merged)
    return out, new_m, rep
