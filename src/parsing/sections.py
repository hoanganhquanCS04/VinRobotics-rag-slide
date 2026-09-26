"""Dò chương (section) từ thanh tiêu đề chạy ở đỉnh trang.

Vì sao cần: docling dựng cây heading PHẲNG — mọi `section_header` đều `level=1`,
`parent=#/body`. Đo trên `3_DataVisualization`: cả 43 tiêu đề đều như vậy, kể cả
tên môn học ở trang bìa lẫn trang mục lục. Tức là KHÔNG có phân cấp nào.

Thứ duy nhất gom được trang thành chương là thanh tiêu đề chạy, mà docling xếp vào
`content_layer: furniture`. Nhưng nó là tín hiệu CƠ HỘI, không phải cơ chế — đã đo
ba file:

    3_DataVisualization   thanh chứa tên chương          -> dùng được
    Chương1               chỉ 1/12 trang, là nhãn biểu đồ -> vứt
    7_XLA7                '11 of 39 11 of 39 11 of 50'    -> vứt

Nên phải kiểm trước khi tin, qua 3 luật. Trượt luật nào cũng trả [] — KHÔNG đoán.
"""

from __future__ import annotations

import logging
import re

from parsing.models import ParsedDocument, ParsedParagraph, SectionSpan

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.60
MIN_OUTLINE_MATCH = 0.80

# 'trang 7', '11 of 39', '5/40', '— 12 —' ... bỏ hết số và liên từ mà rỗng -> là số trang
_NOISE_RE = re.compile(r"^(?:trang|page|slide)?[\s\d/of\-–.]*$", re.IGNORECASE)


def _is_noise(s: str) -> bool:
    return bool(_NOISE_RE.match(s.strip()))


def _running_headers(doc: ParsedDocument) -> dict[int, str]:
    out: dict[int, str] = {}
    for page in doc.pages:
        h = page.running_header
        if h and not _is_noise(h):
            out[page.page_no] = h
    return out


def _outline_titles(doc: ParsedDocument) -> list[str]:
    """Bullet của trang mục lục — trang SỚM NHẤT có một role="list" >= 4 dòng."""
    for page in doc.pages:
        for b in page.blocks:
            if isinstance(b, ParsedParagraph) and b.role == "list" and len(b.lines) >= 4:
                return b.lines
    return []


def _similar(a: str, b: str) -> bool:
    """Khớp lỏng: một chuỗi chứa 12 ký tự đầu của chuỗi kia."""
    a, b = a.lower().strip(), b.lower().strip()
    return bool(a and b and (a[:12] in b or b[:12] in a))


def detect_sections(doc: ParsedDocument) -> tuple[list[SectionSpan], list[str]]:
    """-> (sections, các dòng giải thích để log / báo cáo cho người duyệt)."""
    notes: list[str] = []
    total = doc.n_pages or 1
    hdr = _running_headers(doc)

    coverage = len(hdr) / total
    ok1 = coverage >= MIN_COVERAGE
    notes.append(
        f"luat 1 PHU RONG   : {len(hdr)}/{total} trang = {coverage:.0%} "
        f"(nguong {MIN_COVERAGE:.0%}) -> {'DAT' if ok1 else 'TRUOT'}"
    )
    if not ok1:
        return [], notes

    # gom trang liên tiếp cùng tiêu đề thành khối
    blocks: list[dict] = []
    for pg in sorted(hdr):
        if blocks and blocks[-1]["title"] == hdr[pg] and blocks[-1]["end"] == pg - 1:
            blocks[-1]["end"] = pg
        else:
            blocks.append({"title": hdr[pg], "start": pg, "end": pg})

    counts: dict[str, int] = {}
    for b in blocks:
        counts[b["title"]] = counts.get(b["title"], 0) + 1
    split = [t for t, n in counts.items() if n > 1]
    notes.append(
        f"luat 2 LIEN TUC   : {len(blocks)} khoi, {len(split)} ten bi cat roi -> "
        f"{'DAT' if not split else 'TRUOT: ' + ', '.join(split[:3])}"
    )
    if split:
        return [], notes

    notes.append(f"luat 3 KHONG PHAI SO: da loc nhieu, con {len(blocks)} khoi -> DAT")

    # đối chứng với trang mục lục -> nâng confidence
    confidence = round(coverage, 2)
    outline = _outline_titles(doc)
    if outline:
        titles = [b["title"] for b in blocks]
        hit = sum(1 for o in outline if any(_similar(o, t) for t in titles))
        ratio = hit / len(outline)
        notes.append(f"doi chung muc luc : {hit}/{len(outline)} bullet khop ({ratio:.0%})")
        if ratio >= MIN_OUTLINE_MATCH:
            confidence = round(min(1.0, coverage + 0.15), 2)
    else:
        notes.append("doi chung muc luc : khong tim thay trang muc luc")

    sections = [
        SectionSpan(
            id=f"sec_{i:02d}",
            title=b["title"],
            pages=(b["start"], b["end"]),
            source="page_header",
            confidence=confidence,
        )
        for i, b in enumerate(blocks)
    ]
    return sections, notes


def apply_sections(doc: ParsedDocument) -> ParsedDocument:
    """Dò section, gán vào doc.sections và page.section_id. Sửa tại chỗ."""
    sections, notes = detect_sections(doc)
    for n in notes:
        log.info("  %s", n)
    doc.sections = sections
    for page in doc.pages:
        sec = doc.section_of(page.page_no)
        page.section_id = sec.id if sec else None
    return doc
