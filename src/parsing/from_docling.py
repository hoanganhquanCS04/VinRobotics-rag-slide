"""Đổi file .json của docling (DoclingDocument) sang ParsedDocument.

Năm việc:

  1. Đi theo `body.children` -> ĐÚNG THỨ TỰ ĐỌC. Mảng `texts[]` trong file KHÔNG
     theo thứ tự này, đọc tuần tự mảng là loạn.
  2. Đổi toạ độ: gốc DƯỚI-TRÁI của docling -> gốc TRÊN-TRÁI, chuẩn hoá [0,1].
  3. Tách `body` với `furniture` ra hai rổ riêng (KHÔNG vứt furniture — thanh
     header chạy ở đỉnh trang là nguồn duy nhất dựng được chương).
  4. Gắn `provenance` cho từng mẩu: chữ -> text_layer, mô tả ảnh -> vlm.
  5. Tính `page_hash` để incremental build biết trang nào đổi.

LƯU Ý về provenance của chữ: docling KHÔNG đánh dấu từng item là đọc từ text layer
hay từ OCR. Nên khi `do_ocr=True` ta không phân biệt được, và hàm này hạ toàn bộ
chữ xuống `Provenance.OCR` cho an toàn. Chạy với `do_ocr=False` (mặc định của
`scripts/parse_api.py`) thì mới khai được `text_layer`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

from parsing.models import (
    PAGE_NUMBER,
    AnyBlock,
    BBox,
    Layer,
    ParsedDocument,
    ParsedImage,
    ParsedPage,
    ParsedParagraph,
    ParsedTable,
    ParserInfo,
    Provenance,
    SourceInfo,
)

log = logging.getLogger(__name__)

# docling label -> vai trò trong ParsedParagraph
_ROLE = {
    "section_header": "title",
    "title": "title",
    "caption": "caption",
    "page_header": "header",
    "page_footer": "footer",
}
_FURNITURE_LABELS = {"page_header", "page_footer"}
_DECORATIVE_CLASSES = {"logo", "icon", "signature", "stamp"}
_DECORATIVE_CONF = 0.9


def _refine_role(b: ParsedParagraph) -> None:
    """Hai vai trò docling không gán, suy bằng luật trên chữ.

    links        >= nửa số dòng là URL (p38 của 3_datavisualization: 8/8 dòng)
    page_number  mẩu furniture chỉ gồm "11 / 40" — docling gộp nó vào page_footer
    """
    if b.layer is Layer.FURNITURE:
        if PAGE_NUMBER.fullmatch(b.text):
            b.role = "page_number"
        return
    if b.role in ("body", "list") and b.lines:
        if 2 * len(b.urls) >= len(b.lines):
            b.role = "links"


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _bbox(prov: dict[str, Any], page_w: float, page_h: float, *, is_pptx: bool = False) -> BBox:
    """docling BOTTOMLEFT (t > b, đo từ đáy lên) -> TOPLEFT chuẩn hoá.

    NGOẠI LỆ .pptx: backend pptx của docling gắn nhãn `BOTTOMLEFT` nhưng số thật đo từ
    ĐỈNH xuống (EMU của python-pptx) — tin nhãn là lật trục y. Đo trên tetnguyendan p1:
    "LỄ HỘI LỚN NHẤT NĂM" nằm trên "Tết Nguyên Đán" có t=2557462 < 3548062; lật theo nhãn
    thì ra nằm DƯỚI. Không tin nhãn, chỉ lấy min/max.
    """
    b = prov["bbox"]
    if is_pptx:
        top, bottom = b["b"], b["t"]
    elif b.get("coord_origin", "BOTTOMLEFT").upper() == "BOTTOMLEFT":
        top, bottom = page_h - b["t"], page_h - b["b"]
    else:
        top, bottom = b["t"], b["b"]
    if top > bottom:                      # phòng trường hợp dữ liệu lật ngược
        top, bottom = bottom, top
    return BBox(
        l=_clamp(b["l"] / page_w),
        t=_clamp(top / page_h),
        r=_clamp(b["r"] / page_w),
        b=_clamp(bottom / page_h),
    )


def _resolve(doc: dict[str, Any], ref: str) -> dict[str, Any] | None:
    """'#/texts/12' -> doc['texts'][12]"""
    cur: Any = doc
    for part in ref.lstrip("#/").split("/"):
        if cur is None:
            return None
        cur = cur[int(part)] if part.isdigit() else cur.get(part)
    return cur


def _walk(doc: dict[str, Any], node: dict[str, Any], seen: set[str]) -> Iterator[dict[str, Any]]:
    """Duyệt cây theo thứ tự đọc. Group trả về chính nó rồi mới tới con."""
    for ref in node.get("children", []):
        item = _resolve(doc, ref["$ref"])
        if item is None:
            continue
        sref = item.get("self_ref", "")
        if sref in seen:
            continue
        seen.add(sref)
        yield item
        # Group `list` tự gom con ở bước sau (thành một ParsedParagraph role="list").
        # Group KHÁC thì phải đi vào: docling đọc PPTX nhét MỖI SLIDE vào một group
        # `chapter` — không đi vào là mất sạch chữ (đo được: 62 đoạn -> 0 khối).
        # PDF chỉ có group `list` nên luồng PDF không đổi.
        if not (sref.startswith("#/groups/") and item.get("label") == "list"):
            yield from _walk(doc, item, seen)


def _page_no(item: dict[str, Any]) -> int | None:
    prov = item.get("prov") or []
    return prov[0]["page_no"] if prov else None


def _is_decorative(desc_text: str, classification: list[tuple[str, float]]) -> bool:
    if desc_text.upper().rstrip(".") == "DECORATIVE":
        return True
    if classification:
        name, conf = classification[0]
        return name in _DECORATIVE_CLASSES and conf >= _DECORATIVE_CONF
    return False


def _make_image(
    item: dict[str, Any], bid: str, pg: int, box: BBox, order: int, area_threshold: float
) -> ParsedImage:
    meta = item.get("meta") or {}
    desc = meta.get("description") or {}
    text = _norm(desc.get("text"))
    cls_raw = (meta.get("classification") or {}).get("predictions") or []
    classification = [(c["class_name"], round(float(c["confidence"]), 3)) for c in cls_raw[:3]]

    decorative = bool(text) and _is_decorative(text, classification)
    if decorative:
        skip_reason = "decorative"
    elif text:
        skip_reason = None
    elif box.area_ratio < area_threshold:
        skip_reason = "area_below_threshold"
    else:
        skip_reason = "not_described"

    return ParsedImage(
        id=bid,
        page_no=pg,
        bbox=box,
        layer=Layer.BODY,
        reading_order=order,
        provenance=Provenance.VLM,
        description=text or None,
        described_by=desc.get("created_by") or None,
        skip_reason=skip_reason,
        is_decorative=decorative,
        classification=classification,
    )


def _make_table(
    item: dict[str, Any], bid: str, pg: int, box: BBox, order: int, text_prov: Provenance
) -> ParsedTable:
    data = item.get("data") or {}
    grid = data.get("grid") or []
    cells = [[_norm(c.get("text")) for c in row] for row in grid]
    n_rows = data.get("num_rows", len(cells))
    n_cols = data.get("num_cols", len(cells[0]) if cells else 0)
    return ParsedTable(
        id=bid,
        page_no=pg,
        bbox=box,
        layer=Layer.BODY,
        reading_order=order,
        provenance=text_prov,                 # chữ trong ô: từ text layer
        structure_provenance=Provenance.VLM,  # lưới: do TableFormer dựng
        n_rows=n_rows,
        n_cols=n_cols,
        cells=cells,
    )


def _page_hash(page: ParsedPage) -> str:
    """Hash nội dung + vị trí. Đổi chữ HOẶC đổi bố cục đều ra hash mới."""
    h = hashlib.sha256()
    for b in list(page.blocks) + list(page.furniture):
        bb = b.bbox
        h.update(f"{b.kind}|{bb.l:.4f},{bb.t:.4f},{bb.r:.4f},{bb.b:.4f}|".encode())
        h.update((b.content or "").encode("utf-8"))
    return h.hexdigest()[:16]


def slugify_doc_id(stem: str) -> str:
    """Tên file docling -> doc_id sạch.

        "3_DataVisualization (1)"                         ->  "3_datavisualization"
        "3_DataVisualization (1)__gemini-2.5-flash-lite"  ->  "3_datavisualization"  (tên cũ)

    `doc_id` chui vào MỌI `chunk_id`, mọi tên file vector, và sau này là tên collection
    Qdrant. Để nguyên tên file thô thì nó mang theo dấu cách, "(1)", và tên model VLM —
    ba thứ không liên quan gì tới danh tính tài liệu.

    Bản cũ của scripts/parse_api.py gắn `__<model>` vào tên file; giờ đã bỏ, nhưng vẫn cắt
    để file cũ ra đúng doc_id. Tên model thuộc về CÁCH parse chứ
    không thuộc về TÀI LIỆU. Đổi model VLM mà doc_id đổi theo thì chunk cũ thành mồ côi.
    """
    stem = stem.split("__", 1)[0]                       # bỏ dấu model VLM
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)         # bỏ "(1)" của bản tải trùng
    stem = re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_")
    return stem.lower() or "doc"


def from_docling_json(
    path: str | Path,
    *,
    doc_id: str | None = None,
    source_pdf: str | None = None,
    do_ocr: bool = False,
    vlm_model: str | None = None,
    picture_area_threshold: float = 0.05,
) -> ParsedDocument:
    """Nạp file .json docling sinh ra -> ParsedDocument (chưa có sections/flags)."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Không có OCR thì chữ chắc chắn từ text layer; có OCR thì không phân biệt được.
    text_prov = Provenance.OCR if do_ocr else Provenance.TEXT_LAYER
    is_pptx = "presentationml" in ((raw.get("origin") or {}).get("mimetype") or "")

    sizes = {int(k): (v["size"]["width"], v["size"]["height"]) for k, v in raw["pages"].items()}
    pages = {no: ParsedPage(page_no=no, size_pt=wh) for no, wh in sorted(sizes.items())}
    counters: dict[int, int] = {no: 0 for no in pages}

    def next_id(pg: int) -> tuple[str, int]:
        order = counters[pg]
        counters[pg] += 1
        return f"p{pg:03d}.b{order:02d}", order

    seen: set[str] = set()
    roots = [raw.get("body") or {}, raw.get("furniture") or {}]

    for root in roots:
        for item in _walk(raw, root, seen):
            sref = item.get("self_ref", "")
            is_group = sref.startswith("#/groups/")
            label = item.get("label", "")

            # group: lấy page/bbox từ các con
            if is_group:
                kids = [
                    k
                    for ref in item.get("children", [])
                    if (k := _resolve(raw, ref["$ref"])) is not None
                ]
                kids = [k for k in kids if k.get("label") == "list_item" and (k.get("prov") or [])]
                if not kids:
                    continue
                pg = _page_no(kids[0])
                if pg is None or pg not in pages:
                    continue
                page_w, page_h = sizes[pg]
                boxes = [_bbox(k["prov"][0], page_w, page_h, is_pptx=is_pptx) for k in kids]
                box = BBox(
                    l=min(x.l for x in boxes),
                    t=min(x.t for x in boxes),
                    r=max(x.r for x in boxes),
                    b=max(x.b for x in boxes),
                )
                # Bó bullet -> MỘT ParsedParagraph role="list", các dòng ngăn
                # bằng xuống dòng. Không tách class riêng cho từng dòng: bbox và
                # marker của từng bullet không chỗ nào trong pipeline dùng tới.
                for k in kids:
                    seen.add(k.get("self_ref", ""))
                lid, order = next_id(pg)
                lines = [t for k in kids if (t := _norm(k.get("text")))]
                pages[pg].blocks.append(
                    ParsedParagraph(
                        id=lid,
                        page_no=pg,
                        bbox=box,
                        layer=Layer.BODY,
                        reading_order=order,
                        provenance=text_prov,
                        text="\n".join(lines),
                        text_raw="\n".join(k.get("orig", "") or "" for k in kids),
                        role="list",
                    )
                )
                continue

            prov = item.get("prov") or []
            if not prov:
                continue
            pg = prov[0]["page_no"]
            if pg not in pages:
                continue
            page_w, page_h = sizes[pg]
            box = _bbox(prov[0], page_w, page_h, is_pptx=is_pptx)
            bid, order = next_id(pg)

            layer = (
                Layer.FURNITURE
                if item.get("content_layer") == "furniture" or label in _FURNITURE_LABELS
                else Layer.BODY
            )

            block: AnyBlock
            if sref.startswith("#/pictures/"):
                block = _make_image(item, bid, pg, box, order, picture_area_threshold)
            elif sref.startswith("#/tables/"):
                block = _make_table(item, bid, pg, box, order, text_prov)
            elif label == "list_item":
                # bullet mồ côi (không nằm trong group nào) -> vẫn là role="list"
                block = ParsedParagraph(
                    id=bid, page_no=pg, bbox=box, layer=layer, reading_order=order,
                    provenance=text_prov, text=_norm(item.get("text")),
                    text_raw=item.get("orig", "") or "", role="list",
                )
            else:
                block = ParsedParagraph(
                    id=bid, page_no=pg, bbox=box, layer=layer, reading_order=order,
                    provenance=text_prov, text=_norm(item.get("text")),
                    text_raw=item.get("orig", "") or "",
                    role=_ROLE.get(label, "body"),  # type: ignore[arg-type]
                )

            (pages[pg].furniture if layer is Layer.FURNITURE else pages[pg].blocks).append(block)

    for page in pages.values():
        for b in list(page.blocks) + list(page.furniture):
            if isinstance(b, ParsedParagraph):
                _refine_role(b)
        page.title = next(
            (
                b.text
                for b in page.blocks
                if isinstance(b, ParsedParagraph) and b.role == "title" and b.text
            ),
            None,
        )
        page.page_hash = _page_hash(page)

    doc = ParsedDocument(
        doc_id=doc_id or slugify_doc_id(path.stem),
        source=SourceInfo(
            path=source_pdf or raw.get("name", path.stem),
            sha256=(raw.get("origin") or {}).get("binary_hash", "") and
            str((raw.get("origin") or {}).get("binary_hash", "")),
            n_pages=len(pages),
        ),
        parser=ParserInfo(
            docling_version=_docling_version(raw),
            do_ocr=do_ocr,
            vlm_model=vlm_model,
            picture_area_threshold=picture_area_threshold,
            options_hash=hashlib.sha256(
                f"{do_ocr}|{vlm_model}|{picture_area_threshold}".encode()
            ).hexdigest()[:12],
        ),
        pages=list(pages.values()),
    )
    log.info(
        "%s -> %d trang, %d anh (%d co mo ta)",
        path.name, doc.n_pages, doc.n_images, doc.n_described_images,
    )
    return doc


def _docling_version(raw: dict[str, Any]) -> str:
    try:
        import importlib.metadata as md

        return md.version("docling")
    except Exception:
        return f"schema-{raw.get('version', '?')}"
