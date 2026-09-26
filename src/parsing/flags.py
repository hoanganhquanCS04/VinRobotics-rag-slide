"""Sinh danh sách chỗ cần người xem.

§10 cấm bắt người duyệt mở cả deck — chỉ duyệt phần bị flag. §11 lại có gate
`Flag precision (S7) >= 60%`, nên luật flag phải CHỌN KỸ, không flag bừa.

Ví dụ cụ thể về chọn kỹ: trên `3_DataVisualization` có 43 ảnh không được mô tả.
Flag hết 43 cái thì precision sụp, vì đã đo được cả 43 đều dưới 1% diện tích và
phần lớn là thanh điều khiển PowerPoint lọt vào lúc export — bỏ chúng là ĐÚNG.
Luật đúng phải là "ảnh TRÊN ngưỡng mà vẫn không mô tả được", và luật đó trên file
này bắn ra 0 flag.
"""

from __future__ import annotations

import logging

from parsing.models import Flag, ParsedDocument, header_differs

log = logging.getLogger(__name__)


def _header_title_mismatch(doc: ParsedDocument) -> list[Flag]:
    """Thanh header nói một đằng, tiêu đề trang nói một nẻo.

    Thường là lỗi thật của bộ slide (tác giả quên đổi thanh header khi sang mục
    mới). §5 S2: lỗi của bộ slide thì BÁO, KHÔNG tự sửa.

    Trang `exercise` KHÔNG bắn: lệch header ở đó là tín hiệu đã dùng để phân loại, bắn nữa
    là cờ oan (kéo tụt Flag precision §11).
    """
    out: list[Flag] = []
    for page in doc.pages:
        hdr, title = page.running_header, page.title
        if not hdr or not title or page.slide_type == "exercise":
            continue
        if header_differs(hdr, title):
            out.append(
                Flag(
                    kind="header_title_mismatch",
                    page_no=page.page_no,
                    detail=f"header={hdr!r} vs title={title!r}",
                    severity="warn",
                )
            )
    return out


def _empty_page(doc: ParsedDocument) -> list[Flag]:
    """Không chữ (ngoài tiêu đề) mà cũng không mô tả ảnh nào -> vào KB gần như rỗng.

    Trang phân mục rỗng là ĐÚNG thiết kế — không bắn (trước đây bắn oan 7 cờ error,
    CLI thoát mã 1, CI đỏ giả).
    """
    out: list[Flag] = []
    for page in doc.pages:
        if not page.is_text_starved or page.slide_type == "section_divider":
            continue
        if any(im.content for im in page.images):
            continue
        out.append(
            Flag(
                kind="empty_page",
                page_no=page.page_no,
                detail=(
                    f"{len(page.paragraphs)} block chu, "
                    f"{len(page.images)} anh nhung 0 co mo ta"
                ),
                severity="error",
            )
        )
    return out


def _image_not_described(doc: ParsedDocument) -> list[Flag]:
    """Ảnh TRÊN ngưỡng diện tích mà vẫn không có mô tả -> mất nội dung thật."""
    out: list[Flag] = []
    for page in doc.pages:
        for im in page.images:
            if im.needs_review:
                out.append(
                    Flag(
                        kind="image_not_described",
                        page_no=page.page_no,
                        block_id=im.id,
                        detail=f"chiem {im.area:.1%} trang, ly do={im.why_empty}",
                        severity="error",
                    )
                )
    return out


def _page_label_mismatch(doc: ParsedDocument) -> list[Flag]:
    """Số trang IN TRÊN GIẤY lệch số trang docling gán -> parse sót/lệch trang.

    `furniture.page_number` chỉ được ghi khi đã lệch (from_docling), nên có là bắn.
    """
    out: list[Flag] = []
    for page in doc.pages:
        label = page.furniture.page_number
        if label:
            out.append(
                Flag(
                    kind="page_label_mismatch",
                    page_no=page.page_no,
                    detail=f"tren giay ghi {label!r} nhung docling gan p{page.page_no}",
                    severity="warn",
                )
            )
    return out


def _no_sections(doc: ParsedDocument) -> list[Flag]:
    if doc.sections:
        return []
    return [
        Flag(
            kind="no_sections",
            detail="khong dung duoc page_header -> moi trang la mot don vi doc lap",
            severity="info",
        )
    ]


def build_flags(doc: ParsedDocument) -> list[Flag]:
    flags = (
        _header_title_mismatch(doc)
        + _empty_page(doc)
        + _image_not_described(doc)
        + _page_label_mismatch(doc)
        + _no_sections(doc)
    )
    order = {"error": 0, "warn": 1, "info": 2}
    flags.sort(key=lambda f: (order[f.severity], f.page_no or 0))
    return flags


def apply_flags(doc: ParsedDocument) -> ParsedDocument:
    doc.flags = build_flags(doc)
    by_kind: dict[str, int] = {}
    for f in doc.flags:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    log.info("  co: %s", by_kind or "(khong co)")
    return doc
