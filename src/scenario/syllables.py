"""Đếm âm tiết theo `pronunciation.json`. Xem docs/spec/pronunciation.md.

CODE đếm, không để LLM tự khai: LLM đếm âm tiết tiếng Việt sai có hệ thống, và nó không
biết `savefig` đọc thành "sếp phích" là 2 âm tiết.

    "Gọi savefig kèm tên file"
      Gọi(1) savefig->"sếp phích"(2) kèm(1) tên(1) file(?)

`file` không có trong bảng -> đếm ước lượng VÀ báo `unknown_pronunciation`. Không được
lặng lẽ đếm bừa — đó là cách timing lệch mà không ai thấy.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

VN = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"

_TOKEN = re.compile(r"\w+(?:\.\w+)*")

# Một âm tiết tiếng Việt KHÔNG DẤU: (phụ âm đầu)? + nguyên âm + (phụ âm cuối)?
# Dùng để không báo oan "ba", "hai", "cho", "theo", "trong" là từ tiếng Anh.
_VI_PLAIN = re.compile(
    r"^(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|b|c|d|g|h|k|l|m|n|p|r|s|t|v|x)?"
    r"[aeiouy]{1,3}"
    r"(?:ng|nh|ch|c|m|n|p|t)?$"
)


class Pronunciation:
    def __init__(self, terms: dict[str, dict], hash_: str = ""):
        self.terms = {k.lower(): v for k, v in terms.items()}
        self.hash = hash_

    @classmethod
    def load(cls, path: str | Path) -> "Pronunciation":
        p = Path(path)
        if not p.exists():
            raise SystemExit(f"khong thay {p}\nchay scripts/extract_terms.py truoc")
        d = json.loads(p.read_text(encoding="utf-8"))
        terms = d.get("terms", {})
        h = d.get("hash") or hashlib.sha1(
            json.dumps(terms, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        return cls(terms, h)

    @property
    def keys(self) -> list[str]:
        return sorted(self.terms)

    def lookup(self, word: str) -> dict | None:
        w = word.lower()
        if w in self.terms:
            return self.terms[w]
        if "." in w:                                  # plt.savefig -> savefig
            return self.terms.get(w.split(".")[-1])
        return None


def _is_vietnamese(tok: str) -> bool:
    t = tok.lower()
    return any(c in VN for c in t) or bool(_VI_PLAIN.match(t))


def _number_syllables(tok: str) -> int:
    """Ước: '25' = hai mươi lăm (3), '2025' ~ 7. Thô, nhưng số ít gặp trong lời nói."""
    return max(1, 2 * len(tok) - 1)


def count(text: str, pron: Pronunciation) -> tuple[int, list[str]]:
    """-> (số âm tiết, các từ tiếng Anh KHÔNG có trong bảng)."""
    n = 0
    unknown: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok.isdigit():
            n += _number_syllables(tok)
            continue
        hit = pron.lookup(tok)
        if hit:
            n += int(hit.get("syllables") or len(hit.get("say", "").split()) or 1)
        elif _is_vietnamese(tok):
            n += 1
        else:
            # từ Anh chưa ai quyết cách đọc: ước theo cụm nguyên âm, và BÁO
            n += max(1, len(re.findall(r"[aeiouy]+", tok.lower())))
            unknown.append(tok)
    return n, unknown
