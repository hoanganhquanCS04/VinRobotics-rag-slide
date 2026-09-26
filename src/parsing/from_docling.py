"""Đổi file .json của docling (DoclingDocument) sang ParsedDocument.

Năm việc:

  1. Đi theo `body.children` -> ĐÚNG THỨ TỰ ĐỌC. Mảng `texts[]` trong file KHÔNG
     theo thứ tự này, đọc tuần tự mảng là loạn.
  2. Đổi toạ độ: gốc DƯỚI-TRÁI của docling -> gốc TRÊN-TRÁI, chuẩn hoá [0,1], ra `polygon`.
  3. Tách furniture (header/footer/số trang) khỏi nội dung, gom thành `page.furniture`.
     KHÔNG vứt — thanh header chạy là nguồn duy nhất dựng được chương.
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
    Furniture,
    ParsedDocument,
    ParsedImage,
    ParsedPage,
    ParsedParagraph,
    ParsedTable,
    ParserInfo,
    Provenance,
    SourceInfo,
    polygon_from_box,
)

log = logging.getLogger(__name__)

Box = tuple[float, float, float, float]   # (trái, trên, phải, dưới), [0,1], gốc trên-trái

# docling label -> role của ParsedParagraph
_ROLE = {
    "section_header": "title",
    "title": "title",
    "caption": "caption",
}
_FURNITURE_LABELS = {"page_header", "page_footer"}
_DECORATIVE_CLASSES = {"logo", "icon", "signature", "stamp"}
_DECORATIVE_CONF = 0.9


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _box(prov: dict[str, Any], page_w: float, page_h: float, *, is_pptx: bool = False) -> Box:
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
    return (_clamp(b["l"] / page_w), _clamp(top / page_h),
            _clamp(b["r"] / page_w), _clamp(bottom / page_h))


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


def _is_decorative(desc_text: str, item: dict[str, Any]) -> bool:
    if desc_text.upper().rstrip(".") == "DECORATIVE":
        return True
    preds = ((item.get("meta") or {}).get("classification") or {}).get("predictions") or []
    if preds:
        top = preds[0]
        return top["class_name"] in _DECORATIVE_CLASSES and float(top["confidence"]) >= _DECORATIVE_CONF
    return False


def _make_image(item: dict[str, Any], bid: str, box: Box, area_threshold: float) -> ParsedImage:
    text = _norm(((item.get("meta") or {}).get("description") or {}).get("text"))
    decorative = bool(text) and _is_decorative(text, item)
    im = ParsedImage(id=bid, content=None if decorative else (text or None),
                     polygon=polygon_from_box(*box), provenance=Provenance.VLM)
    if decorative:
        im.why_empty = "decorative"
    elif not text:
        im.why_empty = "area_below_threshold" if im.area < area_threshold else "not_described"
    return im


def _make_table(item: dict[str, Any], bid: str, box: Box, text_prov: Provenance) -> ParsedTable:
    grid = (item.get("data") or {}).get("grid") or []
    return ParsedTable(
        id=bid, polygon=polygon_from_box(*box), provenance=text_prov,   # chữ trong ô: text layer
        cells=[[_norm(c.get("text")) for c in row] for row in grid],
    )


def _vlm_model(raw: dict[str, Any]) -> str | None:
    """Model ĐÃ mô tả ảnh, đọc từ chính output docling (`created_by` trên từng ảnh)."""
    for p in raw.get("pictures") or []:
        by = (((p.get("meta") or {}).get("description")) or {}).get("created_by")
        if by:
            return by
    return None


def _furniture(items: list[tuple[str, str, float]], page_no: int) -> Furniture:
    """(nhãn docling, chữ, tâm y) -> Furniture.

    header       mẩu `page_header` ĐẦU TIÊN; không có nhãn thì mẩu đầu tiên sát đỉnh (y < 0.15).
                 Chỉ lấy MỘT — gộp thêm mẩu khác vào là tên chương lệch giữa các trang, luật
                 dựng chương thấy "cắt rời" và trả 0 chương.
    page_number  "11 / 40" — docling gộp nó vào page_footer. CHỈ giữ khi LỆCH page_no.
    footer       mọi chữ lặp còn lại (tác giả, tên môn…).
    """
    items = [x for x in items if x[1]]
    labeled = [x for x in items if x[0] == "page_header"]
    top = [x for x in items if x[0] != "page_footer" and x[2] < 0.15]
    head = (labeled or top or [None])[0]

    furn = Furniture(header=head[1] if head else None)
    for x in items:
        if x is head:
            continue
        if m := PAGE_NUMBER.fullmatch(x[1]):
            if int(m.group(1)) != page_no:
                furn.page_number = x[1].strip()
        else:
            furn.footer.append(x[1])
    return furn


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
    pages = {no: ParsedPage(page_no=no) for no in sorted(sizes)}
    furniture: dict[int, list[tuple[str, str, float]]] = {no: [] for no in pages}
    counters: dict[int, int] = {no: 0 for no in pages}

    def next_id(pg: int) -> str:
        n = counters[pg]
        counters[pg] += 1
        return f"p{pg:03d}.b{n:02d}"

    seen: set[str] = set()
    roots = [raw.get("body") or {}, raw.get("furniture") or {}]

    for root in roots:
        for item in _walk(raw, root, seen):
            sref = item.get("self_ref", "")
            label = item.get("label", "")

            # Bó bullet -> MỘT ParsedParagraph role="list", các dòng ngăn bằng xuống dòng.
            # Không tách block riêng cho từng dòng: dòng lẻ chỉ vài chữ, không trả lời được gì.
            if sref.startswith("#/groups/"):
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
                boxes = [_box(k["prov"][0], *sizes[pg], is_pptx=is_pptx) for k in kids]
                box = (min(x[0] for x in boxes), min(x[1] for x in boxes),
                       max(x[2] for x in boxes), max(x[3] for x in boxes))
                for k in kids:
                    seen.add(k.get("self_ref", ""))
                lines = [t for k in kids if (t := _norm(k.get("text")))]
                if not lines:
                    continue
                pages[pg].blocks.append(ParsedParagraph(
                    id=next_id(pg), role="list", content="\n".join(lines),
                    polygon=polygon_from_box(*box), provenance=text_prov,
                ))
                continue

            prov = item.get("prov") or []
            if not prov:
                continue
            pg = prov[0]["page_no"]
            if pg not in pages:
                continue
            box = _box(prov[0], *sizes[pg], is_pptx=is_pptx)

            if item.get("content_layer") == "furniture" or label in _FURNITURE_LABELS:
                furniture[pg].append((label, _norm(item.get("text")), (box[1] + box[3]) / 2))
                continue

            block: AnyBlock
            if sref.startswith("#/pictures/"):
                block = _make_image(item, next_id(pg), box, picture_area_threshold)
            elif sref.startswith("#/tables/"):
                block = _make_table(item, next_id(pg), box, text_prov)
            else:
                text = _norm(item.get("text"))
                if not text:
                    continue                 # bỏ TRƯỚC khi cấp id — không để lại lỗ trong dãy id
                block = ParsedParagraph(
                    id=next_id(pg), content=text, polygon=polygon_from_box(*box),
                    provenance=text_prov,
                    # bullet mồ côi (không nằm trong group nào) vẫn là role="list"
                    role="list" if label == "list_item" else _ROLE.get(label, "body"),  # type: ignore[arg-type]
                )
            pages[pg].blocks.append(block)

    for page in pages.values():
        page.furniture = _furniture(furniture[page.page_no], page.page_no)
        page.title = next(
            (b.content for b in page.paragraphs if b.role == "title" and b.content), None
        )
        page.page_hash = page.compute_hash()

    # Model ĐÃ mô tả ảnh (ghi trong output docling) thắng model khai trong .env —
    # và hash phải tính từ đúng model được ghi, không thì hai thứ lệch nhau.
    vlm_model = _vlm_model(raw) or vlm_model
    doc = ParsedDocument(
        doc_id=doc_id or slugify_doc_id(path.stem),
        source=SourceInfo(
            path=source_pdf or raw.get("name", path.stem),
            sha256=str((raw.get("origin") or {}).get("binary_hash", "")),
        ),
        parser=ParserInfo(
            docling_version=_docling_version(raw),
            vlm_model=vlm_model,
            do_ocr=do_ocr,
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
