"""Vá nội dung bằng tay cho những trang parser bỏ sót.

Vì sao cần: docling có lúc bỏ sót cả một vùng nội dung. Ví dụ đo được — trang 15 của
`3_DataVisualization` có đoạn code `mpl.colors.cnames.items()` và cả bảng tên màu, mà
parse ra KHÔNG thấy chữ lẫn ảnh. Nội dung đó là ảnh chụp màn hình dán vào slide, và
layout model không nhận ra đó là ảnh nên đường VLM cũng không chạm tới.

Bật OCR thì đọc được nhưng hỏng dấu tiếng Việt ("Liệt kê" -> "Lit kê") và chậm 8.4×.
Nên với vài trang lẻ, người gõ tay là rẻ nhất và đúng nhất.

KHÔNG sửa thẳng vào `out/parsed/*.json` — chạy lại parse là mất. Patch nằm ở file
riêng, áp lại mỗi lần parse, nên bền qua mọi lần chạy lại.

Block vá vào mang `provenance: "manual"` — tin được như `text_layer`, và truy được là
người gõ chứ không phải model sinh (NT2).

File patch:

    data/patches/<doc_id_bat_ky_phan_nao_cua_ten>.json
    {
      "note": "vi sao phai va",
      "pages": {
        "15": {
          "note": "docling bo sot code + bang mau",
          "add_blocks": [
            {"role": "body", "text": "...", "bbox": [l, t, r, b]}
          ],
          "fix_images": {
            "p015.b00": "mô tả đúng, người viết lại"
          }
        }
      }
    }

`fix_images` thay mô tả VLM tả SAI (vd ảnh Tết bị tả thành "mâm cỗ Trung Thu"). Key là
`block_id` — lấy bằng `python src/parsing/cli.py out/parsed/<ten>.json --page N --full`.
Chuỗi rỗng "" = ảnh trang trí, bỏ khỏi index. Ảnh sửa xong mang `provenance: "manual"`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from parsing.models import (
    BBox,
    Flag,
    Layer,
    ParsedDocument,
    ParsedImage,
    ParsedParagraph,
    Provenance,
)

log = logging.getLogger(__name__)


def load_patch(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"khong thay file patch: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def find_patch(doc_id: str, patch_dir: str | Path = "data/patches") -> Path | None:
    """Tìm file patch hợp với doc_id. Khớp lỏng vì doc_id hay dài và bẩn."""
    d = Path(patch_dir)
    if not d.exists():
        return None
    key = doc_id.lower()
    for f in sorted(d.glob("*.json")):
        if f.stem.lower() in key:
            return f
    return None


def apply_patch(doc: ParsedDocument, patch: dict[str, Any]) -> ParsedDocument:
    """Thêm block / sửa mô tả ảnh. Sửa tại chỗ, trả về chính doc."""
    pages = patch.get("pages") or {}
    n_block = n_fix = 0

    for raw_no, spec in pages.items():
        page = doc.page(int(raw_no))
        if page is None:
            log.warning("  patch: khong co trang %s, bo qua", raw_no)
            continue

        blocks = spec.get("add_blocks") or []
        for i, b in enumerate(blocks):
            l, t, r, bo = b.get("bbox") or [0.05, 0.20, 0.95, 0.90]
            order = max((x.reading_order for x in page.blocks), default=0) + 1 + i
            page.blocks.append(
                ParsedParagraph(
                    id=f"p{page.page_no:03d}.m{i:02d}",     # m = manual
                    page_no=page.page_no,
                    bbox=BBox(l=l, t=t, r=r, b=bo),
                    layer=Layer.BODY,
                    reading_order=order,
                    provenance=Provenance.MANUAL,
                    text=b.get("text", "").strip(),
                    text_raw=b.get("text", "").strip(),
                    role=b.get("role", "body"),
                )
            )
            n_block += 1

        images = {b.id: b for b in page.blocks if isinstance(b, ParsedImage)}
        for bid, desc in (spec.get("fix_images") or {}).items():
            im = images.get(bid)
            if im is None:
                # block_id sai thì BÁO, không lờ đi — lờ đi là mô tả bịa vẫn nằm trong index
                log.warning("  patch: trang %s khong co anh %s, bo qua", raw_no, bid)
                continue
            im.description = desc.strip() or None
            im.is_decorative = not desc.strip()
            im.provenance = Provenance.MANUAL
            im.described_by = "nguoi"
            im.skip_reason = None
            n_fix += 1

        page.blocks.sort(key=lambda x: x.reading_order)
        # Vá xong thì hash đổi -> incremental build biết trang này khác rồi
        from parsing.from_docling import _page_hash

        page.page_hash = _page_hash(page)

        if note := spec.get("note"):
            doc.flags.append(
                Flag(kind="empty_page", page_no=page.page_no,
                     detail=f"da va tay: {note}", severity="info")
            )

    log.info("  patch: them %d block, sua %d mo ta anh, tren %d trang",
             n_block, n_fix, len(pages))
    return doc
