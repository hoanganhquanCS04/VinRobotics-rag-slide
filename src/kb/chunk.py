"""Cắt ParsedDocument thành KBChunk.

Luật (chi tiết ở docs/spec/kb-chunk.md):

    đơn vị    1 trang = 1 chunk chính           <- vì R2 nhảy tới TRANG
    + phụ     mỗi mô tả ảnh = 1 vector phụ      <- chống loãng khi trang nhiều ảnh
    tiền tố   [<tên chương> · trang N/M]        <- contextual enrichment, KHÔNG gọi LLM
    bỏ qua    furniture (header/footer)
    đánh dấu  trang phân mục -> section_divider, lọc khỏi tìm kiếm (KHÔNG xoá)
    cắt thêm  chỉ khi > 500 token, cắt theo ranh giới block

KHÔNG có overlap. Luật `overlap 50` của §5 S5 sinh ra cho văn xuôi liên tục — cắt ở
điểm tuỳ tiện thì câu vắt qua ranh giới mất cả hai bên. Ở đây ranh giới là ranh giới
TRANG, do chính tác giả slide chia. Không câu nào bị cắt đôi. Thứ overlap định phục vụ
(ngữ cảnh vắt qua ranh giới) thì tiền tố `[chương · trang N/M]` làm tốt hơn, mà không
nhân đôi dữ liệu.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from kb.models import ChunkSet, KBChunk
from parsing.models import ParsedDocument, ParsedImage, ParsedPage, ParsedParagraph

log = logging.getLogger(__name__)

TOKENIZER_ID = "cl100k_base"   # tokenizer THẬT của text-embedding-3-*
MAX_TOKENS = 500
CHARS_PER_TOKEN = 3.2          # đường lui khi máy không có tiktoken (tiếng Việt, đo thô)

# Trang phân mục: tiêu đề nằm GIỮA trang thay vì góc trên trái.
# Đo trên 3_DataVisualization — tách bạch, không có vùng xám:
#     phân mục  cx=0.50  cy=0.47     (7 trang: p9,16,22,25,29,32,35)
#     nội dung  cx=0.20  cy=0.11
DIVIDER_MIN_CY = 0.30
DIVIDER_CX_RANGE = (0.35, 0.65)


@lru_cache(maxsize=1)
def _tokenizer():
    """Tokenizer của CHÍNH model nhúng đang dùng (text-embedding-3-* -> cl100k_base).

    Trước đếm bằng bge-m3 và code cũ đã tự ghi đó chỉ là PROXY. Bỏ bge-m3 rồi thì đếm
    bằng đúng bộ của model luôn — tiktoken chỉ ~2 MB chứ không phải 4.3 GB.

    Máy không có tiktoken thì lui về ước theo số ký tự. Con số này chỉ dùng để quyết
    có cắt nhỏ chunk hay không (ngưỡng 500) và để báo cáo, nên sai ±15% vẫn an toàn:
    chunk to nhất đo được mới 353 token.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding(TOKENIZER_ID)
    except Exception:
        log.warning("khong co tiktoken -> uoc token theo so ky tu (sai ~15%%)")
        return None


def tokenizer_name() -> str:
    """Ghi vào ChunkSet để sau khỏi lẫn số đếm đúng với số ước."""
    return TOKENIZER_ID if _tokenizer() is not None else f"uoc_{CHARS_PER_TOKEN}_ky_tu"


def count_tokens(text: str) -> int:
    enc = _tokenizer()
    if enc is None:
        return round(len(text) / CHARS_PER_TOKEN)
    return len(enc.encode(text))


def is_section_divider(page: ParsedPage) -> bool:
    """Trang chỉ có một dải tiêu đề giữa trang, không nội dung."""
    if len(page.paragraphs) != 1:
        return False
    title = page.paragraphs[0]
    if title.role != "title":
        return False
    cx, cy = title.bbox.center
    return cy >= DIVIDER_MIN_CY and DIVIDER_CX_RANGE[0] <= cx <= DIVIDER_CX_RANGE[1]


def prefix_for(doc: ParsedDocument, page: ParsedPage) -> str:
    """'[Đồ thị dạng đường · trang 11/40] ' — ngữ cảnh, khỏi phải gọi LLM sinh."""
    sec = doc.section_of(page.page_no)
    head = f"{sec.title} · " if sec else ""
    return f"[{head}trang {page.page_no}/{doc.n_pages}] "


def _provenance(blocks) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in blocks:
        k = b.provenance.value
        out[k] = out.get(k, 0) + 1
    return out


def _page_chunks(doc: ParsedDocument, page: ParsedPage, max_tokens: int) -> list[KBChunk]:
    """Chunk chính của trang. Quá dài thì cắt theo ranh giới block."""
    blocks = [b for b in page.blocks if b.content]
    if not blocks:
        return []

    prefix = prefix_for(doc, page)
    divider = is_section_divider(page)
    ctype = "section_divider" if divider else "content"

    def make(idx: int | None, bs) -> KBChunk:
        raw = "\n".join(b.content or "" for b in bs)
        enriched = prefix + raw
        suffix = "" if idx is None else f".{idx}"
        return KBChunk(
            chunk_id=f"{doc.doc_id}#p{page.page_no:03d}{suffix}",
            doc_id=doc.doc_id,
            page_no=page.page_no,
            section_id=page.section_id,
            section_title=(s.title if (s := doc.section_of(page.page_no)) else None),
            vector_role="page",
            content_type=ctype,
            text_raw=raw,
            text_enriched=enriched,
            token_count=count_tokens(enriched),
            block_ids=[b.id for b in bs],
            provenance=_provenance(bs),
        )

    whole = make(None, blocks)
    if whole.token_count <= max_tokens or len(blocks) == 1:
        return [whole]

    # Quá dài -> gom block cho tới khi chạm ngưỡng, CẮT Ở RANH GIỚI BLOCK.
    # Mỗi mảnh giữ nguyên tiền tố, nên mảnh nào cũng tự biết mình ở trang nào.
    out: list[KBChunk] = []
    cur: list = []
    cur_tok = count_tokens(prefix)
    for b in blocks:
        t = count_tokens(b.content or "")
        if cur and cur_tok + t > max_tokens:
            out.append(make(len(out) + 1, cur))
            cur, cur_tok = [], count_tokens(prefix)
        cur.append(b)
        cur_tok += t
    if cur:
        out.append(make(len(out) + 1, cur))
    log.info("    p%d dai %d token -> cat thanh %d manh", page.page_no, whole.token_count, len(out))
    return out


def _image_chunks(doc: ParsedDocument, page: ParsedPage) -> list[KBChunk]:
    """Mỗi mô tả ảnh một vector phụ — chống loãng khi trang có nhiều ảnh.

    Đo được 5/40 trang có >=2 ảnh được mô tả, và chúng thường là cặp
    'code + biểu đồ kết quả'. Gộp một vector thì bình quân hai chủ đề, loãng.
    Tách vector nhưng CÙNG trỏ về page_no nên điều hướng không đổi.
    """
    imgs = [b for b in page.images if b.content]
    if len(imgs) < 2:          # 1 ảnh thì chunk trang đã đủ, không nhân bản
        return []

    prefix = prefix_for(doc, page)
    title = page.title or ""
    sec = doc.section_of(page.page_no)
    out: list[KBChunk] = []
    for im in imgs:
        raw = f"{title}\n{im.content}" if title else (im.content or "")
        enriched = prefix + raw
        out.append(
            KBChunk(
                chunk_id=f"{doc.doc_id}#{im.id}",
                doc_id=doc.doc_id,
                page_no=page.page_no,
                section_id=page.section_id,
                section_title=sec.title if sec else None,
                vector_role="image",
                content_type="content",
                text_raw=raw,
                text_enriched=enriched,
                token_count=count_tokens(enriched),
                block_ids=[im.id],
                provenance={im.provenance.value: 1},   # ảnh người sửa -> "manual"
            )
        )
    return out


def chunk_document(doc: ParsedDocument, *, max_tokens: int = MAX_TOKENS) -> ChunkSet:
    chunks: list[KBChunk] = []
    for page in doc.pages:
        chunks.extend(_page_chunks(doc, page, max_tokens))
        chunks.extend(_image_chunks(doc, page))

    cs = ChunkSet(
        doc_id=doc.doc_id,
        source_path=doc.source.path,
        max_tokens=max_tokens,
        tokenizer=tokenizer_name(),
        chunks=chunks,
    )
    n_div = sum(1 for c in chunks if c.content_type == "section_divider")
    n_img = sum(1 for c in chunks if c.vector_role == "image")
    log.info(
        "%s -> %d chunk (%d trang + %d anh) | %d phan muc | tim duoc %d",
        doc.doc_id, len(chunks), len(chunks) - n_img, n_img, n_div, len(cs.searchable),
    )
    return cs
