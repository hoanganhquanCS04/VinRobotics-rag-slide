"""Chạy docling trên từng trang cụ thể của một file và xem nó hoạt động thế nào.

Báo: thời gian parse mỗi trang, docling nhận ra những gì, ghi markdown ra để đọc.

    # 1 trang
    python scripts/test_parse.py "data/raw/file.pdf" --pages 7

    # nhiều trang rời + khoảng
    python scripts/test_parse.py "data/raw/file.pdf" --pages 3,7,12-14

    # cả file
    python scripts/test_parse.py "data/raw/file.pdf" --pages all

    # bật VLM mô tả ảnh, in markdown ra luôn
    python scripts/test_parse.py "data/raw/file.pdf" --pages 7 --describe-pictures --print
"""

import argparse
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Windows không cho tạo symlink nếu chưa bật Developer Mode / chạy admin -> HF hub
# fail khi tải model. Bắt nó copy file thay vì symlink. Phải đặt TRƯỚC khi import HF.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Console Windows mac dinh cp1252 -> print tieng Viet nem UnicodeEncodeError.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
# docling/httpx log rất ồn, chỉ giữ cảnh báo
for noisy in (
    "httpx",
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
log = logging.getLogger("docling_test")


def parse_page_spec(spec: str, total: int) -> list[int]:
    """'3,7,12-14' -> [3, 7, 12, 13, 14];  'all' -> tất cả các trang."""
    if spec.strip().lower() == "all":
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(part))
    bad = [p for p in pages if p < 1 or p > total]
    if bad:
        raise SystemExit(f"trang không tồn tại: {sorted(bad)} (file có {total} trang)")
    return sorted(pages)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument(
        "--pages",
        default="1",
        help="trang cần parse: '7' | '3,7,12-14' | 'all'  (mặc định: 1)",
    )
    # Mode mặc định của docling (PDF_AWARE_LAYOUT_REGIONS) chỉ OCR vùng PDF
    # không có text thật, nên KHÔNG phá text layer. Nhưng với deck đã có text
    # layer thì nó chỉ tốn thời gian mà không thêm gì -> mặc định TẮT.
    ap.add_argument("--ocr", action="store_true", help="bật OCR (chỉ cần cho PDF scan)")
    ap.add_argument(
        "--force-ocr",
        action="store_true",
        help="OcrMode.FULL_PAGE: OCR cả trang, ĐÈ LÊN text layer đang đúng. "
        "Làm mất dấu tiếng Việt và vẫn không đọc được chữ trong ảnh. Đừng dùng.",
    )
    ap.add_argument("--fast-table", action="store_true", help="TableFormer fast thay vì accurate")
    ap.add_argument(
        "--describe-pictures",
        action="store_true",
        help="bật VLM mô tả ảnh (mặc định SmolVLM-256M, chạy local trên CPU)",
    )
    ap.add_argument("--classify-pictures", action="store_true", help="phân loại ảnh (chart/logo/...)")
    ap.add_argument(
        "--vlm",
        metavar="MODEL",
        nargs="?",
        const="granite_docling",
        help="dùng VlmPipeline: VLM đọc cả ảnh trang thay vì layout model. "
        "Phiên được cả chữ nằm trong ảnh. Mặc định granite_docling.",
    )
    ap.add_argument(
        "--api-describe",
        metavar="MODEL",
        help="mô tả ảnh qua API thay vì VLM local. Đọc OPENAI_API_KEY + "
        "OPENAI_BASE_URL từ .env. VD: --api-describe gpt-4o-mini",
    )
    ap.add_argument(
        "--api-prompt",
        default=(
            "Mô tả hình này bằng tiếng Việt, 2-3 câu. Nếu trong hình có chữ, "
            "hãy ghi lại nguyên văn phần chữ đó. Nếu là biểu đồ, nói rõ loại biểu "
            "đồ, trục, và xu hướng chính. Giữ nguyên thuật ngữ tiếng Anh."
        ),
        help="prompt gửi kèm mỗi ảnh khi dùng --api-describe",
    )
    ap.add_argument("--api-concurrency", type=int, default=4, help="số request song song")
    ap.add_argument(
        "--area-threshold",
        type=float,
        default=0.05,
        help="chỉ mô tả ảnh chiếm > tỉ lệ này của trang (mặc định 0.05 = 5%%), "
        "để khỏi tốn tiền cho logo/icon",
    )
    ap.add_argument("--print", dest="do_print", action="store_true", help="in markdown ra console")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--outdir", default="out/parse")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(f"không thấy file: {pdf}")

    import pypdfium2 as pdfium

    total = len(pdfium.PdfDocument(str(pdf)))
    pages = parse_page_spec(args.pages, total)

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    accel = AcceleratorOptions(num_threads=args.threads, device=AcceleratorDevice.CPU)
    fmt_kwargs: dict = {}

    if args.vlm:
        # VlmPipeline: KHONG dung layout model. VLM doc ca anh trang -> doctags.
        from docling.datamodel import vlm_model_specs
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.pipeline.vlm_pipeline import VlmPipeline

        # CLI cua docling goi la 'granite_docling', constant trong code la
        # GRANITEDOCLING -> thu ca hai cach viet.
        spec = None
        for name in (args.vlm.upper(), args.vlm.upper().replace("_", "")):
            for cand in (name + "_TRANSFORMERS", name):
                spec = getattr(vlm_model_specs, cand, None)
                if spec is not None:
                    break
            if spec is not None:
                break
        if spec is None:
            avail = sorted(
                n.removesuffix("_TRANSFORMERS").lower()
                for n in dir(vlm_model_specs)
                if n.endswith("_TRANSFORMERS")
            )
            raise SystemExit(f"không biết model '{args.vlm}'. Chạy được trên CPU: {avail}")

        opts = VlmPipelineOptions(vlm_options=spec)
        opts.accelerator_options = accel
        opts.do_picture_classification = args.classify_pictures
        fmt_kwargs = {"pipeline_cls": VlmPipeline, "pipeline_options": opts}
        desc = f"VlmPipeline model={spec.repo_id} prompt={spec.prompt!r}"
    else:
        opts = PdfPipelineOptions()
        opts.do_ocr = args.ocr or args.force_ocr
        if args.force_ocr:
            # FULL_PAGE OCR ca trang, DE LEN ca chu da co text layer -> lam mat
            # dau tieng Viet. Mode mac dinh (PDF_AWARE_LAYOUT_REGIONS) chi OCR
            # vung khong co text thật, an toan hon.
            from docling.datamodel.pipeline_options import OcrMode

            opts.ocr_options.mode = OcrMode.FULL_PAGE
        opts.do_table_structure = True
        opts.table_structure_options.mode = (
            TableFormerMode.FAST if args.fast_table else TableFormerMode.ACCURATE
        )
        opts.do_picture_description = args.describe_pictures or bool(args.api_describe)
        opts.do_picture_classification = args.classify_pictures
        opts.accelerator_options = accel

        if args.api_describe:
            # Mo ta anh qua API OpenAI-compatible. docling chan goi mang tru khi
            # enable_remote_services=True.
            from docling.datamodel.pipeline_options import PictureDescriptionApiOptions
            from dotenv import load_dotenv

            load_dotenv()
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise SystemExit("thiếu OPENAI_API_KEY trong .env")

            opts.enable_remote_services = True
            opts.picture_description_options = PictureDescriptionApiOptions(
                url=f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                params={"model": args.api_describe, "max_tokens": 300},
                prompt=args.api_prompt,
                timeout=90,
                concurrency=args.api_concurrency,
                provenance=args.api_describe,
                picture_area_threshold=args.area_threshold,
            )

        fmt_kwargs = {"pipeline_options": opts}
        desc = (
            f"StandardPdfPipeline ocr={opts.do_ocr} force_ocr={args.force_ocr} "
            f"table={opts.table_structure_options.mode.value} "
            f"describe={'api:' + args.api_describe if args.api_describe else opts.do_picture_description} "
            f"classify={opts.do_picture_classification}"
        )

    t0 = time.perf_counter()
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(**fmt_kwargs)})
    log.info("%s  |  %d trang, parse: %s", pdf.name, total, pages)
    log.info("%s threads=%d  (khoi tao %.1fs)", desc, args.threads, time.perf_counter() - t0)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    times: list[float] = []

    for p in pages:
        t0 = time.perf_counter()
        res = conv.convert(str(pdf), page_range=(p, p))
        dt = time.perf_counter() - t0
        times.append(dt)

        doc = res.document
        md = doc.export_to_markdown()
        labels = Counter(str(it.label) for it, _ in doc.iterate_items())

        log.info("")
        log.info("--- trang %d: %.1fs  |  %s  |  %d ky tu", p, dt, res.status.value, len(md))
        log.info("    %s", dict(labels) or "(rỗng)")
        if doc.tables or doc.pictures:
            log.info("    tables=%d pictures=%d", len(doc.tables), len(doc.pictures))

        # VLM mo ta anh nam trong pic.meta (field `annotations` da deprecated)
        for i, pic in enumerate(doc.pictures):
            meta = pic.meta
            if meta is None:
                continue
            if meta.description:
                log.info(
                    "    pic[%d] desc (by %s): %s",
                    i,
                    meta.description.created_by,
                    meta.description.text[:200],
                )
            if meta.classification:
                top = meta.classification.predictions[:3]
                log.info("    pic[%d] class: %s", i, [(p.class_name, round(p.confidence, 2)) for p in top])
            if meta.tabular_chart:
                log.info("    pic[%d] chart: %s", i, str(meta.tabular_chart.title)[:120])

        out = outdir / f"{pdf.stem}_p{p:03d}.md"
        out.write_text(md, encoding="utf-8")
        if args.do_print:
            print(f"\n===== {out.name} =====\n{md}\n")

    if len(times) > 1:
        log.info("")
        log.info(
            "TONG %d trang: %.1fs  |  min %.1fs  max %.1fs  tb %.1fs/trang",
            len(times),
            sum(times),
            min(times),
            max(times),
            sum(times) / len(times),
        )
    log.info("ghi -> %s/", outdir)


if __name__ == "__main__":
    main()
