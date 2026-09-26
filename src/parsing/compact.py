"""Bản GỌN của ParsedDocument — để NGƯỜI đọc, bỏ các field lặp nhau.

`cli.py -o out/parsed/<ten>.json` tự ghi kèm `out/parsed/<ten>.compact.json`.

Chỉ để XEM. Pipeline vẫn đọc file đầy đủ — bản gọn thiếu `bbox`, `text`, `page_hash`...
nên không nạp ngược lại thành ParsedDocument được.

Mỗi block còn đúng: id · kind · role (chữ) · content · polygon · provenance
(+ urls / caption / why_empty). Furniture gom thành {header, footer} — `page_number` chỉ
hiện khi lệch `page_no`.

    bỏ                                     vì
    bbox, area_ratio                       đã có polygon
    text, text_raw, description            đã có content
    page_no, reading_order, layer          vị trí trong mảng đã nói lên
    described_by, prompt_hash, page_hash   metadata cho máy
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from parsing.models import Block, ParsedDocument, ParsedImage, ParsedParagraph, ParsedTable


def _block(b: Block) -> dict:
    out: dict = {"id": b.id, "kind": b.kind}
    if isinstance(b, ParsedParagraph):
        out["role"] = b.role      # in cả "body" — đọc khỏi phải nhớ quy ước ngầm
    out["content"] = b.content
    if isinstance(b, ParsedParagraph) and b.role == "links":
        out["urls"] = b.urls
    out["polygon"] = [[round(x, 3), round(y, 3)] for x, y in b.polygon]
    out["provenance"] = b.provenance.value
    if isinstance(b, ParsedTable) and b.caption:
        out["caption"] = b.caption
    if isinstance(b, ParsedImage) and b.content is None:
        # content rỗng thì phải biết VÌ SAO — trang trí hay chưa được mô tả
        out["why_empty"] = "decorative" if b.is_decorative else (b.skip_reason or "not_described")
    return out


def _furniture(blocks: list[Block], page_no: int) -> dict:
    """Gom theo vai trò: {"header": "...", "footer": [...]}.

    header mỗi trang thường có một -> chuỗi; footer thường nhiều -> mảng.
    Mẩu không rõ vai trò (vd deck .pptx docling không gắn nhãn) -> "other".

    `page_number` ("11 / 40") CHỈ hiện khi số in trên slide LỆCH `page_no` — trùng thì
    thừa. File đầy đủ vẫn giữ nó cho cờ `page_label_mismatch`.
    """
    groups: dict[str, list[str]] = {}
    for b in blocks:
        if not b.content:
            continue
        role = b.role if isinstance(b, ParsedParagraph) else b.kind
        if role == "page_number" and b.content.split("/")[0].split("of")[0].strip() == str(page_no):
            continue
        key = role if role in ("header", "footer", "page_number") else "other"
        groups.setdefault(key, []).append(b.content)
    out: dict = {}
    for key in ("header", "footer", "page_number", "other"):
        if key in groups:
            vals = groups[key]
            out[key] = vals[0] if key in ("header", "page_number") and len(vals) == 1 else vals
    return out


def compact(doc: ParsedDocument) -> dict:
    pages = []
    for p in doc.pages:
        page: dict = {"page_no": p.page_no, "title": p.title}
        if p.section_id:
            page["section_id"] = p.section_id
        page["blocks"] = [_block(b) for b in p.blocks]
        if p.furniture:
            page["furniture"] = _furniture(p.furniture, p.page_no)
        pages.append(page)
    return {
        "doc_id": doc.doc_id,
        "n_pages": doc.n_pages,
        "sections": [
            {"id": s.id, "title": s.title, "pages": [s.start_page, s.end_page]}
            for s in doc.sections
        ],
        "flags": [f"[{f.severity}] {f.kind}{f' p{f.page_no}' if f.page_no else ''}: {f.detail}"
                  for f in doc.flags],
        "pages": pages,
    }


def dumps(data: dict) -> str:
    """indent=2, nhưng mảng số (polygon) gập về một dòng."""
    s = json.dumps(data, ensure_ascii=False, indent=2)
    # [\n  0.1,\n  0.2\n] -> [0.1, 0.2]
    s = re.sub(r"\[\s+(-?[\d.]+),\s+(-?[\d.]+)\s+\]", r"[\1, \2]", s)
    # [\n [..],\n [..] ... ] -> [[..], [..], ...]
    return re.sub(r"\[\s+((?:\[[^\[\]]+\],?\s*)+)\]",
                  lambda m: "[" + re.sub(r",\s+", ", ", m.group(1).strip()) + "]", s)


def compact_path(full: Path) -> Path:
    """out/parsed/x.json -> out/parsed/x.compact.json"""
    return full.with_name(f"{full.stem}.compact.json")


def write_compact(doc: ParsedDocument, full: Path) -> Path:
    dst = compact_path(full)
    dst.write_text(dumps(compact(doc)) + "\n", encoding="utf-8")
    return dst
