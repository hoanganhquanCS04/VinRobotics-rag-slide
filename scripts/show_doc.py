"""Đọc file .json của docling ra dạng người xem được.

    python scripts/show_doc.py "out/parse_api/<ten>.json"              # tổng quan
    python scripts/show_doc.py "out/parse_api/<ten>.json" --page 5     # một trang
    python scripts/show_doc.py "out/parse_api/<ten>.json" --page 5 --full   # không cắt chữ

Đi theo `body.children` nên thứ tự in ra ĐÚNG THỨ TỰ ĐỌC, không phải thứ tự
trong mảng `texts[]` (hai cái đó khác nhau).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def resolve(doc: dict, ref: str) -> dict | None:
    """'#/texts/12' -> doc['texts'][12]"""
    parts = ref.lstrip("#/").split("/")
    cur: object = doc
    for p in parts:
        cur = cur[int(p)] if p.isdigit() else cur.get(p)  # type: ignore[union-attr]
        if cur is None:
            return None
    return cur  # type: ignore[return-value]


def page_of(item: dict) -> int | None:
    prov = item.get("prov") or []
    return prov[0]["page_no"] if prov else None


def render(doc: dict, node: dict, depth: int, want_page: int | None,
           full: bool, layer: str) -> list[str]:
    """Trả về list dòng. Group nào không có dòng con nào thì bị bỏ luôn."""
    out: list[str] = []
    for ref in node.get("children", []):
        item = resolve(doc, ref["$ref"])
        if item is None:
            continue
        pg = page_of(item)
        label = item.get("label", "?")
        pad = "  " * depth
        is_group = item.get("self_ref", "").startswith("#/groups/")

        if is_group:
            # group không có prov riêng -> lấy theo con
            kids = render(doc, item, depth + 1, want_page, full, layer)
            if kids:
                out.append(f"{pad}[{item.get('name', 'group')}]")
                out += kids
            continue

        if want_page is not None and pg != want_page:
            continue
        if item.get("content_layer") != layer:
            continue

        if label == "picture":
            desc = (item.get("meta") or {}).get("description") or {}
            txt = desc.get("text", "")
            by = desc.get("created_by") or "khong goi API"
            body = txt if full else txt[:100] + ("…" if len(txt) > 100 else "")
            out.append(f"{pad}[picture] p{pg}  <{by}>")
            out.append(f"{pad}          {body or '(khong co mo ta)'}")
        else:
            txt = item.get("text", "")
            body = txt if full else txt[:100] + ("…" if len(txt) > 100 else "")
            mark = "##" if label == "section_header" else ("-" if label == "list_item" else " ")
            out.append(f"{pad}{mark:2} p{pg:<3} {label:15} {body}")

        out += render(doc, item, depth + 1, want_page, full, layer)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--full", action="store_true", help="in đủ, không cắt 100 ký tự")
    args = ap.parse_args()

    doc = json.loads(Path(args.json).read_text(encoding="utf-8"))

    def on_page(it: dict) -> bool:
        """None = ca tai lieu; co --page thi chi item cua trang do."""
        if args.page is None:
            return True
        prov = it.get("prov") or []
        return bool(prov) and prov[0]["page_no"] == args.page

    texts = [t for t in doc["texts"] if on_page(t)]
    pics = [p for p in doc["pictures"] if on_page(p)]
    tbls = [t for t in doc["tables"] if on_page(t)]
    described = sum(1 for p in pics if (p.get("meta") or {}).get("description"))

    print(f"=== {doc['name']}  ({Path(args.json).stat().st_size // 1024} KB)")
    if args.page is None:
        print(f"    CA TAI LIEU: {len(doc['pages'])} trang | texts={len(texts)} "
              f"pictures={len(pics)} tables={len(tbls)} groups={len(doc['groups'])}")
    else:
        print(f"    TRANG {args.page}/{len(doc['pages'])}: texts={len(texts)} "
              f"pictures={len(pics)} tables={len(tbls)}")
    print(f"    label : {dict(Counter(t['label'] for t in texts))}")
    print(f"    layer : {dict(Counter(t['content_layer'] for t in texts))}")
    print(f"    anh co mo ta: {described}/{len(pics)}")
    print()
    scope = "" if args.page is None else f"| chi trang {args.page} "
    print(f"--- BODY: noi dung that (thu tu doc) {scope}---")
    print(chr(10).join(render(doc, doc["body"], 0, args.page, args.full, "body")) or "  (trong)")

    print()
    print(f"--- FURNITURE: header/footer, KHONG vao markdown {scope}---")
    furn = render(doc, doc["body"], 0, args.page, args.full, "furniture")
    print(chr(10).join(furn[:12]) or "  (trong)")
    if len(furn) > 12:
        print(f"  ... con {len(furn) - 12} dong")


if __name__ == "__main__":
    main()
