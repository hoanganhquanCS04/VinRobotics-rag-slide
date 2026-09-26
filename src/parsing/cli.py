"""Chạy riêng qua dòng lệnh (§9: mỗi stage phải chạy độc lập được).

Nhận CẢ HAI loại file, tự nhận biết:

    .json thô của docling   -> parse thành ParsedDocument
    .json của ParsedDocument -> nạp lại để xem

    # parse rồi ghi ra
    python src/parsing/cli.py "out/parse_api/<ten>.json" -o out/parsed/<ten>.json

    # xem một trang
    python src/parsing/cli.py out/parsed/<ten>.json --page 11
    python src/parsing/cli.py out/parsed/<ten>.json --page 9,11 --full
    python src/parsing/cli.py out/parsed/<ten>.json --page 9-15
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):  # chạy thẳng file, không qua -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsing.flags import apply_flags
from parsing.from_docling import from_docling_json
from parsing.models import ParsedDocument, ParsedParagraph
from parsing.patch import apply_patch, find_patch, load_patch
from parsing.sections import apply_sections

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

try:
    import os

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

log = logging.getLogger("parsing")


# ------------------------------------------------------------------------- nạp


def load(
    path: str | Path,
    *,
    do_ocr: bool = False,
    vlm_model: str | None = None,
    area_threshold: float = 0.05,
    source_pdf: str | None = None,
) -> tuple[ParsedDocument, bool]:
    """-> (doc, vua_parse). `vua_parse=False` nghĩa là nạp lại file đã parse sẵn."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"khong thay file: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{p} khong phai JSON hop le: {e}") from None

    if raw.get("schema_name") == "DoclingDocument":
        doc = from_docling_json(
            path,
            do_ocr=do_ocr,
            vlm_model=vlm_model,
            picture_area_threshold=area_threshold,
            source_pdf=source_pdf,
        )
        apply_sections(doc)
        apply_flags(doc)
        return doc, True

    return ParsedDocument.load(p), False


# ------------------------------------------------------------------------ hiện


def parse_pages(spec: str) -> list[int]:
    """'11' | '9,11' | '9-15'"""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def _cut(s: str, full: bool, n: int = 72) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if full else (s[:n] + ("…" if len(s) > n else ""))


def show_pages(doc: ParsedDocument, pages: list[int], full: bool) -> None:
    for pg in pages:
        page = doc.page(pg)
        if page is None:
            log.warning("khong co trang %d", pg)
            continue
        sec = doc.section_of(pg)
        where = f"{sec.id} ({sec.title}, p{sec.start_page}-{sec.end_page})" if sec else "—"
        log.info("")
        log.info("--- trang %d | %s | chuong: %s", pg, page.title or "(khong tieu de)", where)
        log.info("    hash=%s  starved=%s", page.page_hash, page.is_text_starved)

        for b in page.blocks:
            kind = f"para/{b.role}" if isinstance(b, ParsedParagraph) else b.kind
            body = b.content or f"(rong — {getattr(b, 'why_empty', None)})"
            log.info("    %-10s %-12s %6.2f%% %-10s %s",
                     b.id, kind, b.area * 100, b.provenance.value, _cut(body, full))

        f = page.furniture
        if f.header or f.footer or f.page_number:
            log.info("    furniture: header=%s | footer=%s%s", f.header, " · ".join(f.footer),
                     f" | so trang in LECH: {f.page_number}" if f.page_number else "")

        for f in doc.flags:
            if f.page_no == pg:
                log.info("    [%s] %s — %s", f.severity, f.kind, f.detail)


def report(doc: ParsedDocument) -> None:
    n_body = sum(len(p.blocks) for p in doc.pages)
    n_hdr = sum(1 for p in doc.pages if p.furniture.header)
    log.info("")
    log.info("=== %s", doc.doc_id)
    log.info("    %d trang | %d block | %d trang co thanh header", doc.n_pages, n_body, n_hdr)
    log.info("    anh %d, mo ta duoc %d | bang %d",
             doc.n_images, doc.n_described_images, sum(len(p.tables) for p in doc.pages))

    if doc.sections:
        log.info("    %d section:", len(doc.sections))
        for s in doc.sections:
            log.info("        %s  p%d-%d  conf=%.2f  %s",
                     s.id, s.start_page, s.end_page, s.confidence, s.title)
    else:
        log.info("    0 section (khong dung duoc page_header)")

    if doc.flags:
        log.info("    %d co:", len(doc.flags))
        for f in doc.flags:
            where = f"p{f.page_no}" if f.page_no else "-"
            log.info("        [%s] %-22s %-5s %s", f.severity, f.kind, where, f.detail)
    else:
        log.info("    khong co co nao")


# ------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="parsing")
    ap.add_argument("json", help=".json cua docling HOAC .json cua ParsedDocument")
    ap.add_argument("-o", "--out", default=None, help="ghi ParsedDocument ra file")
    ap.add_argument("--page", default=None, help="xem trang: '11' | '9,11' | '9-15'")
    ap.add_argument("--full", action="store_true", help="in du, khong cat chu")
    ap.add_argument("--ocr", action="store_true",
                    help="file nay parse voi OCR bat -> chu khai la provenance=ocr")
    ap.add_argument("--vlm-model", default=os.environ.get("VLM_MODEL"),
                    help="mac dinh VLM_MODEL trong .env — ghi vao ParsedDocument.parser")
    ap.add_argument("--area-threshold", type=float, default=0.05)
    ap.add_argument("--source-pdf", default=None)
    ap.add_argument("--patch", default=None,
                    help="file va tay; bo trong = tu tim trong data/patches/")
    ap.add_argument("--no-patch", action="store_true", help="bo qua patch du co file")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s"
    )

    doc, just_parsed = load(
        args.json,
        do_ocr=args.ocr,
        vlm_model=args.vlm_model,
        area_threshold=args.area_threshold,
        source_pdf=args.source_pdf,
    )
    if not just_parsed:
        log.info("nap lai ParsedDocument co san (khong parse lai)")

    # Vá tay: áp SAU khi parse/nạp, rồi tính lại cờ vì trang được vá có thể hết rỗng.
    if not args.no_patch:
        pf = Path(args.patch) if args.patch else find_patch(doc.doc_id)
        if pf:
            log.info("va tay tu %s", pf)
            apply_patch(doc, load_patch(pf))
            apply_flags(doc)

    if args.page:
        show_pages(doc, parse_pages(args.page), args.full)
    else:
        report(doc)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc.to_json(), encoding="utf-8")
        log.info("")
        log.info("ghi -> %s (%d KB)", out, out.stat().st_size // 1024)

    n_err = sum(1 for f in doc.flags if f.severity == "error")
    if n_err and not args.page:
        log.info("exit 1: co %d co muc error (de CI bat duoc). Parse van THANH CONG.", n_err)
    return 1 if (n_err and not args.page) else 0


if __name__ == "__main__":
    raise SystemExit(main())
