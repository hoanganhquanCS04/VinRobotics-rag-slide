"""Pipeline MẶC ĐỊNH của docling, chỉ thay phần VLM mô tả ảnh bằng API.

Không chỉnh gì khác: OCR, TableFormer, layout, ngưỡng lọc ảnh, scale — để nguyên
default của docling. Delta duy nhất so với `docling convert` là ba dòng:

    enable_remote_services = True          # docling chặn mọi lời gọi mạng nếu không bật
    do_picture_description = True
    picture_description_options = PictureDescriptionApiOptions(...)

    python scripts/parse_api.py "data/raw/Chương1.pdf"
    python scripts/parse_api.py "data/raw/Chương1.pdf" --pages 1-4

Xuất ra CẢ .md lẫn .json. File .json là DoclingDocument đầy đủ — giữ `prov`
(page_no + bbox) của từng item, thứ mà markdown vứt đi và S3/S5 cần để truy nguyên.

Key đọc từ .env: OPENAI_API_KEY, OPENAI_BASE_URL.
"""

import argparse
import logging
import os
import time
from pathlib import Path

# Phải đặt TRƯỚC khi import huggingface_hub (layout/table model vẫn tải local).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
for noisy in (
    "httpx",
    "urllib3",
    "docling.models.utils.hf_model_download",
    "huggingface_hub",
    "docling.pipeline.base_pipeline",
    "docling.document_converter",
    "docling.models.factories",
    "docling.models.factories.base_factory",
    "docling.utils.accelerator_utils",
    "docling.models.inference_engines.object_detection.transformers_engine",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("parse_api")

ROOT = Path(__file__).resolve().parent.parent
T_START = time.perf_counter()  # gồm cả thời gian nạp model local, không chỉ convert


def page_range(spec: str | None, total: int) -> tuple[int, int]:
    """'1-4' -> (1, 4);  '7' -> (7, 7);  None -> cả file."""
    if not spec:
        return (1, total)
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return (int(lo), int(hi))
    p = int(spec)
    return (p, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--pages", default=None, help="'1-4' | '7' | bỏ trống = cả file")
    # Hai cờ dưới là cách GỌI API, không phải tham số pipeline. Default của docling
    # (concurrency=1, timeout=20s) sinh ra để dùng với server local, chạy qua mạng
    # thì 1 luồng quá chậm và 20s quá ngắn.
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--outdir", default="out/parse_api")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(f"không thấy file: {pdf}")

    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY")
    base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    if not key:
        raise SystemExit("thiếu OPENAI_API_KEY trong .env")

    import pypdfium2 as pdfium

    total = len(pdfium.PdfDocument(str(pdf)))
    lo, hi = page_range(args.pages, total)

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        PictureDescriptionApiOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    prompt = (ROOT / "prompts" / "s5_picture_desc.md").read_text(encoding="utf-8")

    opts = PdfPipelineOptions()  # <- default của docling, không đụng vào
    # Ngoại lệ duy nhất với default. PDF ở đây export từ PowerPoint nên đã có text
    # layer thật; OCR không thêm được ký tự nào. Đo trên 7_XLA7 trang 11-16:
    # bật 73.1s / tắt 8.7s, markdown GIỐNG HỆT (588 ký tự cả hai).
    # OCR có đọc được nhãn trong hình ('A', '2d', '(a)') nhưng là mảnh vụn không
    # ngữ cảnh, và export_to_markdown bỏ qua chúng. Mô tả VLM bắt tốt hơn.
    opts.do_ocr = False
    opts.enable_remote_services = True
    opts.do_picture_description = True
    opts.picture_description_options = PictureDescriptionApiOptions(
        url=f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        params={"model": args.model, "temperature": 0.0},
        prompt=prompt,
        timeout=args.timeout,
        concurrency=args.concurrency,
        provenance=f"{args.model}@api",
    )

    log.info(
        "%s | %d trang, parse %d-%d | ocr=%s table=%s | VLM=%s qua %s",
        pdf.name, total, lo, hi,
        opts.do_ocr, opts.table_structure_options.mode.value, args.model, base,
    )

    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    t0 = time.perf_counter()
    res = conv.convert(str(pdf), page_range=(lo, hi))
    dt = time.perf_counter() - t0

    doc = res.document

    # docling nhan `provenance` trong options nhung KHONG doc no:
    # PictureDescriptionApiModel.__init__ khong gan self.provenance, nen created_by
    # ket o "not-implemented" cua lop cha. Dong dau vao day de NT2 con truy duoc
    # cau nao la `vlm`, cau nao la `deterministic`.
    stamp = f"{args.model}@api"
    for pic in doc.pictures:
        meta = getattr(pic, "meta", None)
        desc = getattr(meta, "description", None) if meta else None
        if desc is not None and desc.created_by in ("not-implemented", "", None):
            desc.created_by = stamp

    outdir = ROOT / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    tag = f"{pdf.stem}__{args.model}"
    md = doc.export_to_markdown()
    (outdir / f"{tag}.md").write_text(md, encoding="utf-8")
    doc.save_as_json(outdir / f"{tag}.json")

    described = sum(
        1 for p in doc.pictures if getattr(p, "meta", None) and getattr(p.meta, "description", None)
    )

    n = max(hi - lo + 1, 1)
    per_page = dt / n
    log.info("")
    log.info("=== %.1fs (%.1fs/trang) | %s", dt, per_page, res.status.value)
    log.info("    wall-clock ca script: %.1fs (ke ca nap model local)", time.perf_counter() - T_START)
    if n < total:
        log.info("    -> uoc tinh ca file %d trang: ~%.0fs (~%.1f phut)", total, per_page * total, per_page * total / 60)
    log.info("    markdown %d ky tu | pictures=%d (mo ta %d) tables=%d", len(md), len(doc.pictures), described, len(doc.tables))
    log.info("ghi -> %s.{md,json}", outdir / tag)


if __name__ == "__main__":
    main()
