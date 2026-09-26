"""Kiểm kịch bản bằng CODE — không tin LLM. Xem docs/spec/scenario.md §11.

Ba mức:
    red    cờ đỏ, KHÔNG đóng gói được       -> thử pass 2, còn thì bắt người duyệt
    fix    vi phạm luật                     -> pass 2 sửa, còn thì thành cờ vàng
    warn   đáng soi nhưng không bắt sửa     -> cờ vàng thẳng
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Literal

from scenario.models import SlideScript
from scenario.syllables import Pronunciation

MAX_SYLLABLES = 30                      # R7 chỉ ngắt được ở ranh giới câu
MAX_SENTENCES = {"section_divider": 2, "content": 6}   # thay cho time_budget đã bỏ
DELIVERY_RANGE = (0.10, 0.25)           # NT4 — 10% là sàn cứng
STDEV_MIN = 6.0

# Văn viết. Lookbehind để khỏi bắt oan "công việc", "thực sự".
BANNED = [
    (re.compile(r"(?<!công )(?<!\w)việc(?!\w)", re.I), "việc"),
    (re.compile(r"(?<!thực )(?<!\w)sự(?!\w)", re.I), "sự"),
    (re.compile(r"được thực hiện bởi", re.I), "được thực hiện bởi"),
]
# Nói VỀ SLIDE thay vì nói VỀ CHỦ ĐỀ — đo được ở lần chạy đầu: "Trang này dạy...",
# "Thuật ngữ ở đây là...". Giảng viên thật không nói vậy.
META = re.compile(
    r"(?:trang|slide)(?: này)? (?:dạy|nói|cho thấy|trình bày|giới thiệu|minh hoạ|minh họa)"
    r"|thuật ngữ ở đây|như trên hình|ví dụ minh h[oọ]a này"
    r"|mô tả cho (?:biết|thấy)|trong (?:ảnh|hình|bức ảnh)|bức ảnh (?:cho|thể hiện)", re.I)
# Câu delivery rỗng, ra lệnh cho người nghe — đo được ở lần chạy thứ hai sau khi cấm
# delivery chứa thuật ngữ: LLM lùi về câu đệm vô nghĩa.
FILLER = re.compile(r"hãy chú ý|lắng nghe|cùng quan sát|tiếp theo thôi|tập trung vào", re.I)
# Khoảng giá trị đọc từ biểu đồ, kể cả viết bằng chữ ("từ một đến bốn")
NUM_WORD = r"(?:\d+|không|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)"
RANGE = re.compile(rf"từ {NUM_WORD}\b.{{0,20}}?đến", re.I)
# Đọc code thành tiếng: ngoặc, dấu bằng, gạch dưới, dạng a.b (nhưng cho phép 1.0)
CODE = re.compile(r"[()=\[\]{}_]|[A-Za-z]\.[A-Za-z]")


@dataclass
class Issue:
    code: str
    level: Literal["red", "fix", "warn"]
    msg: str

    def __str__(self) -> str:
        return self.msg


@dataclass
class BlockInfo:
    provenance: str          # text_layer | vlm | manual | ...
    is_title: bool
    syllables: int           # độ dài khối tiêu đề — để phát hiện câu "bơm" thêm vào tiêu đề


def check(ss: SlideScript, blocks: dict[str, BlockInfo], pron: Pronunciation,
          page_title: str | None = None) -> list[Issue]:
    """`blocks`: id -> thông tin của các khối CÓ nội dung trên trang đang viết."""
    out: list[Issue] = []
    S = ss.sentences
    valid_refs = set(blocks)

    if not S:
        return [Issue("empty_script", "red", "kịch bản rỗng")]

    cap = MAX_SENTENCES[ss.slide_type]
    if len(S) > cap:
        out.append(Issue("too_many_sentences", "fix",
                         f"có {len(S)} câu, loại trang {ss.slide_type} tối đa {cap} câu"))

    for i, s in enumerate(S, 1):
        t = s.text
        if s.syllables > MAX_SYLLABLES:
            out.append(Issue("too_long", "fix",
                             f"câu {i} có {s.syllables} âm tiết, tối đa {MAX_SYLLABLES}"))
        if CODE.search(t):
            out.append(Issue("code_read_aloud", "fix",
                             f"câu {i} đọc mã nguồn (có ngoặc/dấu bằng/dạng a.b): \"{t}\""))
        if META.search(t):
            out.append(Issue("meta_talk", "fix",
                             f"câu {i} nói VỀ SLIDE thay vì về chủ đề: \"{t}\""))
        for rx, word in BANNED:
            if rx.search(t):
                out.append(Issue("written_register", "fix",
                                 f"câu {i} dùng văn viết \"{word}\": \"{t}\""))

        if s.kind == "content":
            if ss.slide_type == "section_divider":
                out.append(Issue("divider_has_content", "red",
                                 f"câu {i} là content nhưng trang chuyển chương chỉ được dẫn dắt"))
            ref = s.grounding.ref if s.grounding else None
            if not ref:
                out.append(Issue("ungrounded_content_sentence", "red",
                                 f"câu {i} là content nhưng không có ref"))
            elif ref not in valid_refs:
                out.append(Issue("bad_grounding_ref", "red",
                                 f"câu {i} trỏ vào \"{ref}\", không phải khối nào của trang này "
                                 f"(hợp lệ: {', '.join(sorted(valid_refs))})"))
            else:
                b = blocks[ref]
                # Khối tiêu đề chỉ chứng minh được TÊN chủ đề. Câu dài hơn tiêu đề nhiều mà
                # trỏ vào tiêu đề = đang bơm kiến thức ngoài trang (đo được ở p20).
                if b.is_title and s.syllables > b.syllables + 6:
                    out.append(Issue("title_grounded_claim", "red",
                                     f"câu {i} trỏ vào khối TIÊU ĐỀ \"{ref}\" nhưng nói nhiều hơn "
                                     f"tên chủ đề — tiêu đề không chứng minh được điều đó. Trỏ "
                                     f"vào khối có nội dung, hoặc bỏ câu: \"{t}\""))
                # §10: số đọc từ biểu đồ là vlm, có thể sai -> không khẳng định
                if b.provenance == "vlm" and (re.search(r"\d", t) or RANGE.search(t)):
                    out.append(Issue("vlm_number", "fix",
                                     f"câu {i} nêu con số/khoảng giá trị lấy từ mô tả ảnh do máy "
                                     f"sinh ({ref}) — chỉ được nói xu hướng: \"{t}\""))
        else:
            if FILLER.search(t):
                out.append(Issue("filler_delivery", "fix",
                                 f"câu {i} là câu đệm ra lệnh, không nói gì cả: \"{t}\" — "
                                 f"thay bằng câu gợi tò mò về chủ đề hoặc nối với trang trước"))
            if re.search(r"\d", t):
                out.append(Issue("delivery_has_fact", "fix",
                                 f"câu {i} là delivery nhưng chứa con số: \"{t}\""))
            terms = [w for w in re.findall(r"\w+", t) if pron.lookup(w)]
            if terms:
                out.append(Issue("delivery_has_fact", "fix",
                                 f"câu {i} là delivery nhưng chứa thuật ngữ {terms}: \"{t}\""))

    if ss.slide_type == "section_divider" and page_title:
        if page_title.strip().lower() not in " ".join(s.text for s in S).lower():
            out.append(Issue("divider_no_title", "fix",
                             f"trang chuyển chương phải nêu tên chương \"{page_title}\""))

    if ss.unknown_terms:
        out.append(Issue("unknown_pronunciation", "warn",
                         f"từ tiếng Anh chưa có cách đọc: {sorted(set(ss.unknown_terms))}"))

    if ss.slide_type == "content" and len(S) >= 3:
        lo, hi = DELIVERY_RANGE
        r = ss.delivery_ratio
        if not lo <= r <= hi:
            out.append(Issue("delivery_ratio", "fix",
                             f"câu delivery chiếm {r:.0%} âm tiết, cần {lo:.0%}–{hi:.0%}"))

    if ss.slide_type == "content" and len(S) >= 4:
        sd = statistics.pstdev([s.syllables for s in S])
        if sd < STDEV_MIN:
            out.append(Issue("monotone_rhythm", "warn",
                             f"độ lệch chuẩn âm tiết/câu {sd:.1f} < {STDEV_MIN} — nhịp đều đều"))
    return out


def needs_fix(issues: list[Issue]) -> bool:
    return any(i.level in ("red", "fix") for i in issues)


def to_flags(issues: list[Issue]) -> list[str]:
    return sorted({i.code for i in issues})
