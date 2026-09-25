"""Dò cấu trúc section của deck từ `page_header`, validate BẰNG CODE.

docling dựng cây heading phẳng — mọi `section_header` đều `level=1`, nên không
biết trang nào thuộc mục nào. Nhưng nhiều deck có thanh tiêu đề chạy ở đỉnh
trang, và docling gắn nó nhãn `page_header` trong `content_layer: furniture`.
Thanh đó thường CHÍNH LÀ tên section.

"Thường" chứ không phải "luôn" — có deck nó là số trang, có deck là dòng ghi
nguồn. Nên phải kiểm trước khi tin, qua 3 luật:

    1. PHỦ ĐỦ RỘNG      >= 60% số trang có page_header
    2. KHỐI LIÊN TỤC    mỗi tên chiếm một dải trang liền nhau, không nhảy cóc
    3. KHÔNG PHẢI SỐ    loại '11 of 39', '5/40', 'Trang 7'...

Trượt bất kỳ luật nào -> KHÔNG đoán bừa, trả về None để pipeline quay lại
một-chunk-một-trang.

    python scripts/detect_sections.py "out/parse_api/<ten>.json"
    python scripts/detect_sections.py out/parse_api/*.json out/docling_cli/*.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

MIN_COVERAGE = 0.60
NOISE_RE = re.compile(r"^(?:trang|page|slide)?[\s\d/of\-–.]*$", re.IGNORECASE)


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def is_noise(s: str) -> bool:
    """'11 of 39 11 of 39 11 of 50' -> True. Bỏ hết số/of/gạch mà rỗng thì là số trang."""
    return bool(NOISE_RE.match(normalize(s)))


def headers_by_page(doc: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for t in doc["texts"]:
        prov = t.get("prov") or []
        if not prov or t["label"] != "page_header":
            continue
        txt = normalize(t["text"])
        if is_noise(txt):
            continue
        pg = prov[0]["page_no"]
        # trang có nhiều page_header -> lấy cái DÀI NHẤT (ngắn thường là số/ký hiệu)
        if pg not in out or len(txt) > len(out[pg]):
            out[pg] = txt
    return out


def outline_titles(doc: dict) -> list[str]:
    """list_item của trang mục lục (trang có >=4 list_item sớm nhất) — dùng đối chứng."""
    by_page: dict[int, list[str]] = {}
    for t in doc["texts"]:
        prov = t.get("prov") or []
        if prov and t["label"] == "list_item" and t["content_layer"] == "body":
            by_page.setdefault(prov[0]["page_no"], []).append(normalize(t["text"]))
    for pg in sorted(by_page):
        if len(by_page[pg]) >= 4:
            return by_page[pg]
    return []


def detect(doc: dict) -> tuple[list[dict] | None, list[str]]:
    """-> (sections | None, các dòng giải thích)"""
    total = len(doc["pages"])
    hdr = headers_by_page(doc)
    notes: list[str] = []

    cov = len(hdr) / total if total else 0.0
    notes.append(f"luat 1 PHU RONG   : {len(hdr)}/{total} trang = {cov:.0%} "
                 f"(nguong {MIN_COVERAGE:.0%}) -> {'DAT' if cov >= MIN_COVERAGE else 'TRUOT'}")
    if cov < MIN_COVERAGE:
        return None, notes

    # gom trang liên tiếp cùng tên thành khối
    blocks: list[dict] = []
    for pg in sorted(hdr):
        if blocks and blocks[-1]["title"] == hdr[pg] and blocks[-1]["end"] == pg - 1:
            blocks[-1]["end"] = pg
        else:
            blocks.append({"title": hdr[pg], "start": pg, "end": pg})

    seen: dict[str, int] = {}
    broken = [b["title"] for b in blocks if (seen.setdefault(b["title"], 0) or seen.update({b["title"]: seen[b["title"]] + 1}) or seen[b["title"]] > 1)]
    dup = [t for t, n in seen.items() if n > 1]
    notes.append(f"luat 2 LIEN TUC   : {len(blocks)} khoi, "
                 f"{len(dup)} ten bi cat roi -> {'DAT' if not dup else 'TRUOT: ' + ', '.join(dup[:3])}")
    if dup:
        return None, notes

    notes.append(f"luat 3 KHONG PHAI SO: da loc, con {len(blocks)} khoi hop le -> DAT")
    return blocks, notes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+")
    args = ap.parse_args()

    for path in args.json:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        print(f"=== {doc['name']}  ({len(doc['pages'])} trang)")
        secs, notes = detect(doc)
        for n in notes:
            print(f"    {n}")

        if secs is None:
            print("    => KHONG dung duoc page_header. Quay lai mot-chunk-mot-trang.")
            print()
            continue

        print(f"    => {len(secs)} section:")
        for s in secs:
            span = f"p{s['start']}" if s["start"] == s["end"] else f"p{s['start']}-{s['end']}"
            print(f"         {span:10} {s['title']}")

        # đối chứng với trang mục lục
        outline = outline_titles(doc)
        if outline:
            titles = {s["title"].lower() for s in secs}
            hit = sum(1 for o in outline if any(o.lower()[:12] in t or t[:12] in o.lower() for t in titles))
            print(f"    doi chung muc luc : {hit}/{len(outline)} bullet khop ten section")
            if hit < len(outline):
                miss = [o for o in outline if not any(o.lower()[:12] in t or t[:12] in o.lower() for t in titles)]
                print(f"         khong khop: {miss[:3]}")

        # trang có page_header lệch section_header -> cờ cho người duyệt
        sec_hdr = {}
        for t in doc["texts"]:
            prov = t.get("prov") or []
            if prov and t["label"] == "section_header" and t["content_layer"] == "body":
                sec_hdr.setdefault(prov[0]["page_no"], normalize(t["text"]))
        hdr = headers_by_page(doc)
        odd = [(pg, hdr[pg], sec_hdr[pg]) for pg in sorted(hdr)
               if pg in sec_hdr and hdr[pg].lower()[:10] not in sec_hdr[pg].lower()]
        if odd:
            print(f"    CO {len(odd)} trang page_header lech section_header (co cho S7):")
            for pg, h, s in odd[:5]:
                print(f"         p{pg}: header={h!r} vs title={s!r}")
        print()


if __name__ == "__main__":
    main()
