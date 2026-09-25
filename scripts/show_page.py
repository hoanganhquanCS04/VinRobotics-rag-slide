"""Vẽ bbox trong file .json của docling đè lên ảnh trang thật, để soi bằng mắt.

Dùng khi nghi docling khoanh sai vùng, hoặc muốn biết một item trong json ứng
với chỗ nào trên trang.

    python scripts/show_page.py <doc.json> <goc.pdf> --pages 10,11
    python scripts/show_page.py <doc.json> <goc.pdf> --pages 6 --no-furniture

Màu khung:
    đỏ    section_header      xanh dương  text        xanh lá  list_item
    cam   picture             tím         page_header xám      page_footer
"""

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

COLOR = {
    "section_header": (220, 30, 30),
    "text": (30, 120, 220),
    "list_item": (30, 160, 80),
    "picture": (200, 120, 0),
    "page_header": (150, 0, 150),
    "page_footer": (130, 130, 130),
}


def parse_pages(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("pdf")
    ap.add_argument("--pages", required=True, help="'10' | '10,11' | '6-9'")
    ap.add_argument("--no-furniture", action="store_true", help="chỉ vẽ content_layer=body")
    ap.add_argument("--width", type=int, default=1100, help="bề rộng ảnh xuất ra")
    ap.add_argument("--outdir", default="out/pages")
    args = ap.parse_args()

    import pypdfium2 as pdfium
    from PIL import ImageDraw

    doc = json.loads(Path(args.json).read_text(encoding="utf-8"))
    pdf = pdfium.PdfDocument(args.pdf)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip()

    for pg in parse_pages(args.pages):
        size = doc["pages"][str(pg)]["size"]
        W, H = size["width"], size["height"]
        img = pdf[pg - 1].render(scale=args.width / W).to_pil().convert("RGB")
        sx, sy = img.width / W, img.height / H
        dr = ImageDraw.Draw(img)

        print(f"--- trang {pg} ({W:.0f}x{H:.0f} pt)")
        rows = []
        for pool in ("texts", "pictures"):
            for i, it in enumerate(doc[pool]):
                prov = it.get("prov") or []
                if not prov or prov[0]["page_no"] != pg:
                    continue
                if args.no_furniture and it.get("content_layer") != "body":
                    continue
                b = prov[0]["bbox"]
                # bbox goc DUOI-TRAI -> toa do anh goc TREN-TRAI
                x0, x1 = b["l"] * sx, b["r"] * sx
                y0, y1 = (H - b["t"]) * sy, (H - b["b"]) * sy
                c = COLOR.get(it["label"], (0, 0, 0))
                dr.rectangle([x0, y0, x1, y1], outline=c, width=3)
                dr.text((x0 + 4, max(0, y0 - 13)), f"#/{pool}/{i}", fill=c)

                area = abs(b["r"] - b["l"]) * abs(b["t"] - b["b"]) / (W * H)
                if it["label"] == "picture":
                    desc = (it.get("meta") or {}).get("description") or {}
                    txt = norm(desc.get("text")) or "(khong goi API)"
                else:
                    txt = norm(it.get("text"))
                rows.append((b["t"], f"#/{pool}/{i}", it["label"], it["content_layer"], area, txt))

        for _, ref, lab, lay, area, txt in sorted(rows, key=lambda r: -r[0]):
            print(f"    {ref:15} {lab:15} {lay:10} {area * 100:5.2f}%  {txt[:58]}")

        out = outdir / f"{Path(args.pdf).stem}_p{pg:03d}.png"
        img.save(out)
        print(f"    -> {out}")


if __name__ == "__main__":
    main()
