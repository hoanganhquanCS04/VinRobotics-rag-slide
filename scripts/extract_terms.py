"""Sinh bản NHÁP của pronunciation.json để người duyệt.

Xem docs/spec/pronunciation.md. Ba điều script này KHÔNG làm được, và đó là lý do phải
có người:

  1. **Không tách nổi tiếng Việt không dấu khỏi tiếng Anh.** `quan` `theo` `hoa` `xanh`
     `sai` trông y hệt `plot` `sin` `color`. Nên script chỉ lấy hai nhóm CHẮC CHẮN
     (có dấu chấm, hoặc toàn chữ hoa), còn lại người tự thêm.
  2. **Không biết từ nào sẽ được NÓI RA MIỆNG.** §5 S4: không đọc mã nguồn thành tiếng.
     Script cứ đề xuất, người xoá mục thừa.
  3. **Không biết đọc thế nào cho tự nhiên.** `matplotlib` là "mát plót líp" hay
     "mát-pờ-lót-líp"? Quyết định của người.

Mọi mục sinh ra mang `by: "auto"` — nhìn file là biết chỗ nào chưa ai duyệt.

    python scripts/extract_terms.py out/kb/<doc_id>.chunks.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kb.models import ChunkSet

log = logging.getLogger("terms")

VN = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
LETTER = "A-Za-z" + VN + VN.upper()
HEX = re.compile(r"^[0-9A-Fa-f]{4,8}$")

# Đọc từng chữ cái theo tên chữ tiếng Việt
LETTER_VI = {
    "a": "a", "b": "bê", "c": "xê", "d": "đê", "e": "e", "f": "ép", "g": "giê",
    "h": "hát", "i": "i", "j": "gi", "k": "ca", "l": "e lờ", "m": "em", "n": "en",
    "o": "o", "p": "pê", "q": "quy", "r": "e rờ", "s": "ét", "t": "tê", "u": "u",
    "v": "vê", "w": "vê kép", "x": "ích", "y": "i dài", "z": "dét",
}

# Mồi sẵn mấy từ hay gặp trong bài giảng CNTT tiếng Việt.
# Đây là ĐỀ XUẤT, không phải chân lý — người duyệt sửa thoải mái.
SEED: dict[str, tuple[str, str]] = {          # từ -> (say, mode)
    "python":      ("pai thon", "phonetic_vi"),
    "matplotlib":  ("mát plót líp", "phonetic_vi"),
    "numpy":       ("năm pai", "phonetic_vi"),
    "pyplot":      ("pai plót", "phonetic_vi"),
    "cartopy":     ("các tô pi", "phonetic_vi"),
    "pandas":      ("pan đát", "phonetic_vi"),
    "matlab":      ("mát láp", "phonetic_vi"),
    "iris":        ("ai rít", "phonetic_vi"),
    "savefig":     ("sếp phích", "phonetic_vi"),
    "errorbar":    ("e rơ ba", "phonetic_vi"),
    "linspace":    ("lin xpây", "phonetic_vi"),
    "scatter":     ("xcát tơ", "phonetic_vi"),
    "hist":        ("hít", "phonetic_vi"),
    "histogram":   ("hít tô gram", "phonetic_vi"),
    "plot":        ("plót", "phonetic_vi"),
    "subplot":     ("sấp plót", "phonetic_vi"),
    "colorbar":    ("cô lơ ba", "phonetic_vi"),
    "scatter3d":   ("xcát tơ ba đê", "phonetic_vi"),
    "plot3d":      ("plót ba đê", "phonetic_vi"),
    "contour":     ("con tua", "phonetic_vi"),
    "petal":       ("pe tồ", "phonetic_vi"),
    "sepal":       ("xe pồ", "phonetic_vi"),
}


def spell(word: str) -> str:
    """CSV -> 'xê ét vê'. Dùng cho viết tắt."""
    return " ".join(LETTER_VI.get(c.lower(), c) for c in word if c.isalnum())


def count_syllables(say: str) -> int:
    """Đếm cụm cách nhau bởi khoảng trắng. TÍNH TỰ ĐỘNG, người không gõ tay —
    gõ tay là mở cửa cho sửa `say` mà quên sửa số."""
    return len([x for x in say.split() if x])


# Bí danh module: KHÔNG bao giờ đọc ra miệng. §5 S4 — nói "gọi savefig",
# không nói "pi eo ti chấm savefig".
ALIAS = {"plt", "np", "mpl", "pd", "rng", "ccrs", "crs", "ax", "fig", "sns", "cv2"}
# Mảnh URL
URLISH = {"www", "com", "vn", "html", "htm", "http", "https", "org", "net", "png", "jpg", "csv"}
URL_RE = re.compile(r"https?://\S+|www\.\S+|[\w.-]+\.(?:com|vn|org|net)", re.I)


def harvest(text: str) -> tuple[Counter, Counter]:
    """-> (tên hàm cuối cùng sau dấu chấm, viết tắt toàn hoa).

    Ba thứ bị loại thẳng vì KHÔNG BAO GIỜ đọc ra miệng:
      1. URL và tên miền (chotot.com, batdongsan...) — loại cả câu chứa URL
      2. mã màu hex và mảnh của nó (#F0F8FF -> F0F8FF, FF, B8B)
      3. bí danh module (plt, np, mpl) — §5 S4 cấm đọc mã nguồn thành tiếng

    Chữ Việt VIẾT HOA (KHOA, QUAN từ tiêu đề "NHẬP MÔN KHOA HỌC...") cũng bị loại:
    nhận ra bằng cách xem nó có nằm trong một dải >= 3 từ viết hoa liên tiếp không.
    """
    text = URL_RE.sub(" ", text)                      # 1
    text = re.sub(r"#[0-9A-Fa-f]{3,8}", " ", text)    # 2

    # 4. chữ Việt viết hoa: dải >= 3 từ hoa liên tiếp -> là tiêu đề, không phải viết tắt
    title_words: set[str] = set()
    for run in re.findall(r"(?:[A-Z][A-Z]+[ 	]*){3,}", text):
        title_words |= {w.lower() for w in run.split()}

    tok = re.findall(r"[%s][%s0-9_.]*" % (LETTER, LETTER), text)
    words = [t.strip(".") for t in tok if t.strip(".")]
    words = [w for w in words
             if len(w) >= 2 and not any(c in VN for c in w.lower())
             and not HEX.match(w) and w.lower() not in title_words]

    dotted = Counter(w for w in words if "." in w)
    upper = Counter(w for w in words
                    if "." not in w and w.isupper() and w.lower() not in URLISH
                    and not re.fullmatch(r"[0-9A-F]+", w))   # mảnh hex còn sót
    return dotted, upper


def build(cs: ChunkSet) -> dict:
    text = "\n".join(c.text_raw for c in cs.chunks)
    dotted, upper = harvest(text)

    terms: dict[str, dict] = {}

    def add(key: str, say: str, mode: str, seen: int) -> None:
        if key.lower() in {k.lower() for k in terms}:
            return
        terms[key] = {"say": say, "syllables": count_syllables(say),
                      "mode": mode, "by": "auto", "seen": seen}

    # 1. Tên hàm: BỎ tiền tố module. §5 S4 cấm đọc mã nguồn thành tiếng —
    #    robot nói "gọi errorbar", không nói "pi eo ti chấm errorbar".
    bare: Counter = Counter()
    for full, n in dotted.items():
        part = full.split(".")[-1]          # CHỈ phần cuối: plt.savefig -> savefig
        if len(part) >= 3 and not part.isdigit() and part.lower() not in ALIAS                 and part.lower() not in URLISH:
            bare[part.lower()] += n
    for w, n in bare.most_common():
        s = SEED.get(w)
        add(w, s[0] if s else w, s[1] if s else "as_english", n)

    # 2. Viết tắt -> đọc từng chữ cái
    for w, n in upper.most_common():
        if len(w) <= 5:
            add(w, spell(w), "spell", n)

    # 3. Mồi: thư viện / thuật ngữ có trong bài mà không nằm hai nhóm trên
    low = text.lower()
    for w, (say, mode) in SEED.items():
        if w in low:
            add(w, say, mode, low.count(w))

    body = {k: {kk: vv for kk, vv in v.items() if kk != "seen"}
            for k, v in sorted(terms.items())}
    h = hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]

    return {
        "version": 1,
        "doc_id": cs.doc_id,
        "hash": h,
        "_huong_dan": [
            "MỞ FILE NÀY RA SỬA. Máy chỉ ĐỀ XUẤT, người CHỐT.",
            "1. Sửa 'say' chỗ đọc chưa đúng — viết bằng chữ Việt, cách nhau bởi khoảng trắng.",
            "2. XOÁ mục nào robot không bao giờ nói ra miệng (tên biến, tham số...).",
            "3. THÊM từ máy bỏ sót — máy KHÔNG tách được tiếng Việt không dấu khỏi tiếng Anh.",
            "4. Đổi 'by' từ 'auto' thành 'nguoi' ở mục đã duyệt.",
            "5. KHÔNG sửa 'syllables' và 'hash' — chạy lại script là tính lại.",
        ],
        "terms": body,
        "skip": ["mã màu hex (#F0F8FF...)", "URL", "đường dẫn file"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="extract_terms")
    ap.add_argument("chunks", help="out/kb/<doc_id>.chunks.json")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    cs = ChunkSet.model_validate(json.loads(Path(args.chunks).read_text(encoding="utf-8")))
    data = build(cs)

    out = Path(args.out or f"out/deck/{cs.doc_id}/pronunciation.json")
    if out.exists():
        # GIỮ mục người đã duyệt, chỉ thêm mục mới -> duyệt lại từ đầu là vô lý
        old = json.loads(out.read_text(encoding="utf-8"))
        kept = {k: v for k, v in old.get("terms", {}).items() if v.get("by") == "nguoi"}
        for k, v in kept.items():
            v["syllables"] = count_syllables(v.get("say", ""))
        n_new = len([k for k in data["terms"] if k not in kept])
        data["terms"] = dict(sorted({**data["terms"], **kept}.items()))
        log.info("giu %d muc da duyet, them %d muc moi", len(kept), n_new)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    n_auto = sum(1 for v in data["terms"].values() if v["by"] == "auto")
    log.info("")
    log.info("ghi -> %s", out)
    log.info("   %d muc, %d con la 'auto' (chua ai duyet)", len(data["terms"]), n_auto)
    log.info("   MO FILE RA SUA, roi doi by:'auto' -> 'nguoi'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
