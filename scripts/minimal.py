"""Bản tối giản đúng như README của docling.

    python scripts/minimal.py "data/raw/3_DataVisualization (1).pdf"

Lưu ý: bản này dùng TOÀN BỘ mặc định của docling -> OCR bật, parse cả file.
Trên deck 40 trang của repo này là ~40 phút. Muốn nhanh thì dùng test_parse.py.
"""

import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

from docling.document_converter import DocumentConverter

source = sys.argv[1] if len(sys.argv) > 1 else "https://arxiv.org/pdf/2408.09869"
converter = DocumentConverter()
result = converter.convert(source)
print(result.document.export_to_markdown())
