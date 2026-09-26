"""Schema của ParsedDocument.

Ba tầng chứa nhau:

    ParsedDocument  --*-->  ParsedPage  --*-->  Block
                                                  |-- ParsedParagraph   (chữ)
                                                  |-- ParsedTable       (bảng)
                                                  `-- ParsedImage       (ảnh)

Mọi Block khai ba thứ: NỘI DUNG gì · nằm CHỖ NÀO · AI sinh ra (`provenance`).
Field cuối là NT2 đóng thành kiểu dữ liệu: `text_layer` đúng 100%, `vlm` có thể bịa.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Iterator, Literal

from pydantic import BaseModel, Field, computed_field


# Một dòng chỉ gồm một URL — "https://moso.vn/" · "www.abc.com/x"
URL_LINE = re.compile(r"(?:https?://|www\.)\S+")
# Số trang in trên slide — "11 / 40" · "11 of 40"
PAGE_NUMBER = re.compile(r"\s*\d+\s*(?:/|of)\s*\d+\s*")


class Provenance(str, Enum):
    """Nội dung này ở đâu ra — quyết định tin được bao nhiêu (NT2)."""

    TEXT_LAYER = "text_layer"   # đọc thẳng từ text layer của PDF, đúng 100%
    VLM = "vlm"                 # model nhìn ảnh rồi sinh, CÓ THỂ BỊA
    OCR = "ocr"                 # đọc từ pixel, sai chính tả được
    DERIVED = "derived"         # code suy ra (section, reading order)
    MANUAL = "manual"           # người gõ tay ở S7 — tin được như text_layer


class Layer(str, Enum):
    BODY = "body"               # nội dung thật
    FURNITURE = "furniture"     # header/footer/số trang, lặp mọi trang


class BBox(BaseModel):
    """Toạ độ đã CHUẨN HOÁ: [0,1], gốc TRÊN-TRÁI.

    docling dùng gốc DƯỚI-TRÁI (`coord_origin: BOTTOMLEFT`) nên `t > b`. Quy đổi
    một lần ở biên (`from_docling`), để mọi chỗ dùng sau khỏi tự xoay trục.
    """

    l: float = Field(ge=0.0, le=1.0)
    t: float = Field(ge=0.0, le=1.0)
    r: float = Field(ge=0.0, le=1.0)
    b: float = Field(ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area_ratio(self) -> float:
        """Chiếm bao nhiêu phần diện tích trang. Ngưỡng gọi API VLM dựa vào đây."""
        return round(max(0.0, self.r - self.l) * max(0.0, self.b - self.t), 6)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.l + self.r) / 2, (self.t + self.b) / 2)

    def to_pixel(self, img_w: float, img_h: float) -> tuple[float, float, float, float]:
        """-> (x0, y0, x1, y1) trên ảnh đã render, để vẽ khung."""
        return (self.l * img_w, self.t * img_h, self.r * img_w, self.b * img_h)

    def overlaps(self, other: BBox) -> bool:
        return not (
            self.r < other.l or other.r < self.l or self.b < other.t or other.b < self.t
        )


# --------------------------------------------------------------------------- Block


class Block(BaseModel):
    """Lớp cha của mọi mẩu nội dung nằm trên trang."""

    id: str                     # "p010.b03" — ổn định, Flag và chunk trỏ vào
    page_no: int
    bbox: BBox
    layer: Layer
    reading_order: int
    provenance: Provenance

    @property
    def content(self) -> str | None:
        """Nội dung dạng chữ — thứ đem đi chunk làm KB. Mỗi lớp con tự định nghĩa."""
        raise NotImplementedError

    @computed_field  # type: ignore[prop-decorator]
    @property
    def polygon(self) -> list[tuple[float, float]]:
        """4 góc theo chiều kim đồng hồ từ trên-trái, toạ độ [0,1]. Tính từ bbox."""
        b = self.bbox
        return [(b.l, b.t), (b.r, b.t), (b.r, b.b), (b.l, b.b)]


class ParsedParagraph(Block):
    """Mọi thứ là CHỮ: tiêu đề, đoạn văn, và cả bó gạch đầu dòng.

    Bó gạch đầu dòng KHÔNG có class riêng — nó là `role="list"`, các dòng ngăn
    nhau bằng xuống dòng, lấy ra bằng `.lines`. Lý do giữ `role` thay vì gộp hẳn
    vào `body`: §5 S4 cấm robot đọc bullet nguyên văn, S4 cần biết mẩu này là
    danh sách để diễn đạt lại thành lời nói.

    `role` nói robot đối xử với mẩu chữ thế nào — `kind` vẫn là "paragraph" vì nó vẫn là chữ:

        body · title · list · caption      nội dung (layer=body)
        links                              phần lớn dòng là URL -> KHÔNG đọc URL thành tiếng
        header · footer · page_number      khung trang (layer=furniture)
    """

    kind: Literal["paragraph"] = "paragraph"
    text: str
    text_raw: str = ""          # bản chưa gỡ marker/khoảng trắng thừa
    role: Literal[
        "title", "body", "list", "caption", "links", "header", "footer", "page_number"
    ] = "body"

    @property
    def lines(self) -> list[str]:
        """Tách thành từng dòng. Có nghĩa khi `role="list"` / `"links"`."""
        return [ln.strip() for ln in self.text.split("\n") if ln.strip()]

    @property
    def urls(self) -> list[str]:
        """Các dòng là URL. Có nghĩa khi `role="links"`."""
        return [ln for ln in self.lines if URL_LINE.fullmatch(ln)]

    @property
    def n_chars(self) -> int:
        return len(self.text)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content(self) -> str | None:
        return self.text or None


class ParsedTable(Block):
    """Lưới do TableFormer dựng (có thể sai), chữ trong ô từ text layer (đúng).

    Hai nguồn khác nhau nên phải khai hai `provenance` riêng — gộp một là mất
    thông tin.
    """

    kind: Literal["table"] = "table"
    n_rows: int = 0
    n_cols: int = 0
    header_rows: int = 1
    cells: list[list[str]] = Field(default_factory=list)
    caption: str | None = None
    structure_provenance: Provenance = Provenance.VLM

    @property
    def header(self) -> list[str]:
        return self.cells[0] if self.cells and self.header_rows else []

    def rows_as_chunks(self) -> list[str]:
        """Mỗi hàng một chunk, LẶP HEADER ở mỗi hàng (luật S5 cho bảng lớn)."""
        head = self.header
        out: list[str] = []
        for row in self.cells[self.header_rows:]:
            pairs = [f"{h}: {c}" for h, c in zip(head, row) if c]
            out.append(" | ".join(pairs) if pairs else " | ".join(row))
        return out

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content(self) -> str | None:
        """Bảng dạng markdown, sinh từ `cells` — `cells` mới là bản gốc."""
        if not self.cells:
            return None

        def row(r: list[str]) -> str:
            cs = [c.replace("|", "\\|").replace("\n", " ") for c in r]
            return "| " + " | ".join(cs) + " |"

        n_head = max(1, self.header_rows)
        lines = [row(r) for r in self.cells[:n_head]]
        lines.append("|" + "---|" * len(self.cells[0]))
        lines += [row(r) for r in self.cells[n_head:]]
        return "\n".join(lines)


class ParsedImage(Block):
    """Mẩu ảnh. `description` do VLM sinh nên `provenance` luôn là `vlm`.

    `skip_reason` là thứ docling không lưu mà ta cần: nhìn `description=None`
    phải biết được là CHƯA GỌI hay GỌI MÀ FAIL — hai ca xử lý khác hẳn nhau.
    """

    kind: Literal["image"] = "image"
    description: str | None = None
    described_by: str | None = None       # "gemini-2.5-flash-lite@api"
    prompt_hash: str | None = None        # đổi prompt -> mô tả cũ lạc hậu
    skip_reason: str | None = None        # "area_below_threshold" | "api_error" | ...
    is_decorative: bool = False
    classification: list[tuple[str, float]] = Field(default_factory=list)

    @property
    def was_described(self) -> bool:
        return bool(self.description) and not self.is_decorative

    @property
    def needs_review(self) -> bool:
        """Ảnh đủ to mà không có mô tả -> mất nội dung thật.

        Ảnh trang trí KHÔNG tính: VLM đã xem và kết luận không có nội dung, đó là
        câu trả lời hợp lệ chứ không phải thiếu sót. Không loại nó ra thì logo cỡ
        lớn bắn cờ oan và kéo tụt `Flag precision` của §11.
        """
        if self.is_decorative or self.was_described:
            return False
        return self.bbox.area_ratio >= 0.05

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content(self) -> str | None:
        return self.description if self.was_described else None


AnyBlock = Annotated[
    ParsedParagraph | ParsedTable | ParsedImage,
    Field(discriminator="kind"),
]


# ------------------------------------------------------------------ tầng tài liệu


class ParsedPage(BaseModel):
    page_no: int
    size_pt: tuple[float, float]
    page_hash: str = ""                   # incremental build (§8)
    title: str | None = None              # tiêu đề của trang
    section_id: str | None = None         # trỏ lên ParsedDocument.sections
    blocks: list[AnyBlock] = Field(default_factory=list)      # layer=body
    furniture: list[AnyBlock] = Field(default_factory=list)   # layer=furniture

    @property
    def images(self) -> list[ParsedImage]:
        return [b for b in self.blocks if isinstance(b, ParsedImage)]

    @property
    def tables(self) -> list[ParsedTable]:
        return [b for b in self.blocks if isinstance(b, ParsedTable)]

    @property
    def paragraphs(self) -> list[ParsedParagraph]:
        return [b for b in self.blocks if isinstance(b, ParsedParagraph)]

    @property
    def running_header(self) -> str | None:
        """Thanh tiêu đề chạy ở đỉnh trang — nguồn duy nhất dựng được chương.

        Tin nhãn `role="header"` của docling trước; không có nhãn thì mới đoán theo vị trí.
        """
        paras = [b for b in self.furniture if isinstance(b, ParsedParagraph) and b.text]
        for b in paras:
            if b.role == "header":
                return b.text
        for b in paras:
            if b.bbox.center[1] < 0.15:
                return b.text
        return None

    @property
    def page_label(self) -> str | None:
        """Số trang IN TRÊN GIẤY ('11 / 40'), để đối chiếu với page_no."""
        for b in self.furniture:
            if isinstance(b, ParsedParagraph) and PAGE_NUMBER.fullmatch(b.text):
                return b.text.strip()
        return None

    @property
    def is_text_starved(self) -> bool:
        """<=1 mẩu chữ -> trang sống chết nhờ mô tả ảnh."""
        return len(self.paragraphs) <= 1


class SectionSpan(BaseModel):
    """Một chương: trang start..end. SUY RA chứ không parse ra — phải khai nguồn."""

    id: str
    title: str
    start_page: int
    end_page: int
    source: Literal["page_header", "title_bbox", "outline_page", "manual"]
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def n_pages(self) -> int:
        return self.end_page - self.start_page + 1

    def contains(self, page_no: int) -> bool:
        return self.start_page <= page_no <= self.end_page


class Flag(BaseModel):
    """Chỗ cần người xem. §10 cấm bắt duyệt cả deck — chỉ duyệt phần bị flag."""

    kind: Literal[
        "header_title_mismatch",
        "empty_page",
        "image_not_described",
        "page_label_mismatch",
        "no_sections",
    ]
    page_no: int | None = None
    block_id: str | None = None
    detail: str = ""
    severity: Literal["info", "warn", "error"] = "warn"


class SourceInfo(BaseModel):
    path: str
    sha256: str = ""
    n_pages: int = 0


class ParserInfo(BaseModel):
    """Đổi model hay đổi option mà không parse lại -> dữ liệu cũ mới lẫn nhau
    trong im lặng. Cùng loại bẫy với luật nhúng `model_id` vào tên collection."""

    docling_version: str = ""
    do_ocr: bool = False
    vlm_model: str | None = None
    picture_area_threshold: float = 0.05
    options_hash: str = ""


class ParsedDocument(BaseModel):
    doc_id: str
    source: SourceInfo
    parser: ParserInfo
    pages: list[ParsedPage] = Field(default_factory=list)
    sections: list[SectionSpan] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    # -------- truy vấn

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def n_images(self) -> int:
        return sum(len(p.images) for p in self.pages)

    @property
    def n_described_images(self) -> int:
        return sum(1 for p in self.pages for im in p.images if im.was_described)

    def page(self, page_no: int) -> ParsedPage | None:
        return next((p for p in self.pages if p.page_no == page_no), None)

    def section_of(self, page_no: int) -> SectionSpan | None:
        return next((s for s in self.sections if s.contains(page_no)), None)

    def pages_in(self, section_id: str) -> list[ParsedPage]:
        sec = next((s for s in self.sections if s.id == section_id), None)
        if sec is None:
            return []
        return [p for p in self.pages if sec.contains(p.page_no)]

    def iter_blocks(self, layer: Layer | None = Layer.BODY) -> Iterator[Block]:
        """Duyệt phẳng toàn tài liệu. layer=None -> cả body lẫn furniture."""
        for page in self.pages:
            if layer in (None, Layer.BODY):
                yield from page.blocks
            if layer in (None, Layer.FURNITURE):
                yield from page.furniture
