# ParsedDocument — cấu trúc dữ liệu sau khi parse

**Code:** [`src/parsing/`](../../src/parsing/) · **Vào:** `.json` docling sinh (từ `.pdf` hoặc `.pptx`)
· **Ra:** `out/parsed/<ten>.json` + `out/parsed/<ten>.compact.json`

---

## 0. Bối cảnh v0 ★

Một file duy nhất vừa là **deck** (robot nói gì) vừa là **KB** (robot tra gì) — xem
[CLAUDE.md §3.0](../../CLAUDE.md). Hệ quả: không có `chart_data`/`tables` chuẩn từ XML, S3
Alignment vô nghĩa, robot chỉ trả lời ở mức **mô tả slide**. Lối thoát duy nhất là đưa
tài liệu nguồn thật vào, tách khỏi deck.

```
data/raw/<ten>.{pdf,pptx}           file gốc
out/parse_api/<ten>.{md,json}       docling thô              (scripts/parse_api.py)
out/parsed/<ten>.json               ParsedDocument ĐẦY ĐỦ    ← pipeline đọc file này
out/parsed/<ten>.compact.json       bản GỌN để người đọc     ← tự ghi kèm, pipeline KHÔNG đọc
```

---

## 1. Cấu trúc — đọc qua bản gọn

Mở `<ten>.compact.json` là thấy toàn bộ cấu trúc. Tài liệu → trang → block:

```
📦 doc_id, n_pages
 ├── sections[]    chương: {id, title, pages: [đầu, cuối]}
 ├── flags[]       chỗ cần người xem
 └── pages[]
      └── 📄 page_no, title, section_id
           ├── blocks[]      NỘI DUNG THẬT, theo thứ tự đọc
           │    └── 🧩 id · kind · role · content · polygon · provenance
           └── furniture     {header, footer[]} — chỉ chữ; page_number chỉ hiện khi lệch page_no
```

**Mỗi block trả lời đúng ba câu**, loại nào cũng vậy:

| | field | ví dụ |
|---|---|---|
| nói gì | `content` | `"Đồ thị dạng đường"` — thứ đem đi chunk làm KB |
| nằm đâu | `polygon` | 4 góc `[[l,t],[r,t],[r,b],[l,b]]`, `[0,1]`, gốc **trên-trái** |
| tin được không | `provenance` | `text_layer` (chữ thật, đúng 100%) · `vlm` (máy tả, có thể sai) · `manual` (người sửa) |

`content` theo từng loại:

| `kind` | `content` là | thêm |
|---|---|---|
| `paragraph` | chữ trên slide | `role` — luôn có, xem bảng dưới · `urls` khi `role: links` |
| `image` | mô tả của VLM | `why_empty` khi `content: null`: `decorative` · `area_below_threshold` · `not_described` |
| `table` | markdown của bảng | `caption` |

`kind` = mẩu này **là gì** (chữ / ảnh / bảng). `role` = robot **đối xử với chữ đó thế nào**:

| `role` | ở đâu | nghĩa | ai gán |
|---|---|---|---|
| `body` | blocks | đoạn văn thường | mặc định |
| `title` | blocks | tiêu đề trang | docling |
| `list` | blocks | bó gạch đầu dòng — S4 diễn đạt lại, không đọc bullet | docling |
| `links` | blocks | ≥ nửa số dòng là URL — **không đọc URL thành tiếng** | luật |
| `caption` | blocks | chú thích | docling |
| `header` | furniture | thanh tiêu đề chạy — nguồn dựng chương | docling |
| `footer` | furniture | tác giả, tên môn… | docling |
| `page_number` | furniture | `"11 / 40"` — docling gộp vào footer, luật tách ra. Bản gọn chỉ hiện khi LỆCH `page_no` (slide ẩn/xoá/đánh số sai) | luật |

Deck `.pptx` hiện chưa có furniture: docling không gắn nhãn header/footer cho pptx.

Ví dụ thật — trang 11 của `3_datavisualization`:

```json
{
  "page_no": 11, "title": "Đồ thị dạng đường", "section_id": "sec_00",
  "blocks": [
    {"id": "p011.b01", "kind": "paragraph", "role": "title",
     "content": "Đồ thị dạng đường",
     "polygon": [[0.023, 0.083], [0.373, 0.083], [0.373, 0.138], [0.023, 0.138]],
     "provenance": "text_layer"},
    {"id": "p011.b02", "kind": "image",
     "content": "Đoạn mã Python và biểu đồ đường ... plt.savefig('line_graph.png') ...",
     "polygon": [[0.22, 0.181], [0.776, 0.181], [0.776, 0.962], [0.22, 0.962]],
     "provenance": "vlm"},
    {"id": "p011.b03", "kind": "image", "content": null,
     "polygon": [[0.78, 0.934], [0.993, 0.934], [0.993, 0.961], [0.78, 0.961]],
     "provenance": "vlm", "why_empty": "area_below_threshold"}
  ],
  "furniture": {
    "header": "Đồ thị dạng đường",
    "footer": ["VH Thư", "Nhập môn Khoa học dữ liệu"]
  }
}
```

Trang này chỉ có **1 mẩu chữ**, trùng tiêu đề với 6 trang khác cùng chương. Thứ phân biệt
nó là mô tả ảnh — `plt.savefig` chỉ tồn tại nhờ tầng VLM. Đó là insight §1 CLAUDE.md:
slide là bản nén mất mát.

Trang link — p38, block `links` kèm `urls` tách sẵn:

```json
{"id": "p038.b03", "kind": "paragraph", "role": "links",
 "content": "https://www.nhatot.com/mua-ban-bat-dong-san-ha-noi\nhttps://batdongsan.com.vn/...",
 "urls": ["https://www.nhatot.com/mua-ban-bat-dong-san-ha-noi", "https://batdongsan.com.vn/...", "..."],
 "polygon": [[0.07, 0.343], [0.894, 0.343], [0.894, 0.883], [0.07, 0.883]],
 "provenance": "text_layer"}
```

Header p38 ghi `"Dữ liệu địa lý"` nhưng tiêu đề là `"Bài tập nhóm chương 2+3"` — trang bài
tập kế thừa header chương trước. Lệch này là tín hiệu nhận trang `exercise` (CLAUDE.md §5).

---

## 2. Bản đầy đủ = bản gọn + phần cho máy

Pipeline đọc file đầy đủ vì cần thêm mấy thứ bản gọn bỏ đi:

| chỉ có ở bản đầy đủ | ai cần |
|---|---|
| `page_hash` | S4 — biết trang nào đổi để viết lại kịch bản (§8 CLAUDE.md) |
| `source`, `parser` | biết file gốc nào, docling bản nào, VLM nào — đổi mà không parse lại là lẫn dữ liệu |
| `described_by`, `prompt_hash` của ảnh | đổi prompt → biết mô tả nào đã lạc hậu |
| `cells` của bảng | cắt bảng lớn theo hàng, lặp header (`rows_as_chunks()`) |
| `bbox`, `text`, `description` | field GỐC — `content`/`polygon` tính ra từ chúng |

Bản gọn bỏ những field **lặp nhau**: `bbox`/`area_ratio` (đã có `polygon`),
`text`/`text_raw`/`description` (đã có `content`), `page_no`/`reading_order`/`layer` (vị
trí trong mảng đã nói lên).

> Hướng sau: gộp hai bản làm một — `content`/`polygon` thành field lưu thật, bỏ
> `text`/`bbox`. Chưa làm vì `bbox` đang dùng ở ~6 chỗ và đổi `page_hash` là phải chạy lại S4.

---

## 3. Trong code

```
Block                     id · page_no · bbox · layer · reading_order · provenance
 │                        .content  .polygon   ← mỗi loại tự định nghĩa content
 ├── ParsedParagraph      text · text_raw · role · .lines · .urls
 ├── ParsedTable          cells · n_rows · n_cols · header_rows · caption · structure_provenance
 └── ParsedImage          description · described_by · prompt_hash · skip_reason · is_decorative

ParsedPage                page_no · title · section_id · page_hash · blocks · furniture
                          .paragraphs .images .tables · .running_header .page_label .is_text_starved
ParsedDocument            doc_id · source · parser · pages · sections · flags
SectionSpan               id · title · start_page · end_page · source · confidence
Flag                      kind · page_no · block_id · detail · severity
```

`.content` và `.polygon` là `computed_field`: **tính** từ field gốc, nhưng vẫn được ghi ra
JSON đầy đủ để mở file ra xem được.

```python
from parsing.models import ParsedDocument

doc = ParsedDocument.model_validate_json(open("out/parsed/xxx.json", encoding="utf-8").read())
doc.page(11)                  # trang 11
doc.section_of(11)            # thuộc chương nào
doc.pages_in("sec_00")        # chương gồm trang nào

for b in doc.page(11).blocks:
    b.content, b.polygon, b.provenance
```

Mấy luật dễ quên:

- **Bó gạch đầu dòng là MỘT block** `role="list"`, các dòng ngăn bằng xuống dòng. Dòng lẻ
  chỉ vài chữ, không trả lời được câu hỏi nào; S4 cần biết đây là danh sách để không đọc
  bullet nguyên văn.
- **Bảng có hai `provenance`**: chữ trong ô từ text layer (đúng), lưới do TableFormer dựng
  (`structure_provenance`, có thể sai).
- **Ảnh `content: null` phải biết VÌ SAO** — *chưa gọi* hay *gọi mà fail* xử lý khác hẳn nhau.
- **`sections` được SUY RA**, không parse ra — nên bắt buộc khai `source` + `confidence`.
- **Toạ độ `.pptx`**: docling gắn nhãn `BOTTOMLEFT` nhưng số thật đo từ ĐỈNH. `from_docling`
  không tin nhãn với `.pptx` — tin là lật trục y (đo được ở `tetnguyendan` p1).

---

## 4. Vì sao giữ `furniture`

152/252 mẩu chữ của `3_datavisualization` là header/footer lặp, nhìn như rác. Nhưng:

1. **Thanh header chạy là nguồn chương duy nhất** — docling cho `level=1` trên mọi tiêu đề.
2. **Bắt lỗi bộ slide** — header lệch tiêu đề ra ngay 3 trang (p38–40).
3. **Số trang in trên slide** (`"11 / 40"`) đối chiếu `page_no` → biết có sót trang.

Không đem vào KB, nhưng bỏ rồi muốn lấy lại phải parse lại — tốn tiền API.

---

## 5. Cờ

| `kind` | nghĩa |
|---|---|
| `header_title_mismatch` | header nói một đằng, tiêu đề trang một nẻo — cũng là tín hiệu trang bài tập |
| `empty_page` | không chữ, không mô tả ảnh → vào KB gần như rỗng |
| `image_not_described` | ảnh **trên** ngưỡng mà không tả được |
| `page_label_mismatch` | số trang in lệch số trang thật |
| `no_sections` | không dựng được chương (deck không có thanh header) |

---

## 6. Chạy

```powershell
# ① docling + VLM mô tả ảnh (gọi API)
.venv\Scripts\python.exe scripts\parse_api.py data\raw\<ten>.pptx

# ② ra cấu trúc của mình — ghi CẢ <ten>.json lẫn <ten>.compact.json
.venv\Scripts\python.exe src\parsing\cli.py "out\parse_api\<ten>.json" -o out\parsed\<ten>.json

# xem một trang
.venv\Scripts\python.exe src\parsing\cli.py out\parsed\<ten>.json --page 9-11
```

Bước ② nhận cả file đã parse — chạy lại để làm mới bản gọn mà không cần docling.
File vá tay `data/patches/<ten>.json` tự được áp nếu có.
Exit code `1` khi có cờ mức `error` — để CI bắt. Parse vẫn thành công.

```
docling .json ─► from_docling.py   theo body.children → thứ tự đọc; đổi toạ độ; tách body/furniture
              ─► patch.py          vá tay (nếu có)
              ─► sections.py       thanh header → chương
              ─► flags.py          soi luật → cờ
              ─► cli.py            ghi <ten>.json + <ten>.compact.json  ─► S5 KB
```

---

## 7. Số đã kiểm — chạy lại phải ra đúng, lệch là có lỗi

| | `3_datavisualization` (.pdf) | `tetnguyendan` (.pptx) |
|---|---|---|
| trang | 40 | 10 |
| block body | 54 đoạn + 11 bó bullet + 71 ảnh (+2 vá tay) | 43 đoạn + 15 ảnh |
| furniture | 152 | 0 |
| ảnh có `content` (vào KB) | 27 — VLM tả 28, 1 cái là `decorative` | 6 |
| chương | 7, chương đầu p9–15, khớp mục lục 7/7 | 0 — không có thanh header |
| cờ | 7 `empty_page` + 3 `header_title_mismatch` | 1 `no_sections` |
| file đầy đủ → gọn | 362 KB → 73 KB | 68 KB → 20 KB |

Ca âm tính — `Chương1.pdf`: chỉ 1/12 trang có thanh header → trượt luật phủ 60% →
**0 chương**, đúng như mong đợi (không đoán bừa).
