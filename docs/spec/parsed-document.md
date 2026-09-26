# ParsedDocument — cấu trúc dữ liệu sau khi parse

**Code:** [`src/parsing/`](../../src/parsing/) · **Vào:** `.json` docling sinh (từ `.pdf` hoặc `.pptx`)
· **Ra:** `out/parsed/<ten>.json` — **một file duy nhất**, vừa để người đọc vừa để pipeline chạy

---

## 0. Bối cảnh v0 ★

Một file duy nhất vừa là **deck** (robot nói gì) vừa là **KB** (robot tra gì) — xem
[CLAUDE.md §3.0](../../CLAUDE.md). Hệ quả: không có `chart_data`/`tables` chuẩn từ XML, S3
Alignment vô nghĩa, robot chỉ trả lời ở mức **mô tả slide**. Lối thoát duy nhất là đưa
tài liệu nguồn thật vào, tách khỏi deck.

```
data/raw/<ten>.{pdf,pptx}           file gốc
out/parse_api/<ten>.{md,json}       docling thô              (scripts/parse_api.py)
out/parsed/<ten>.json               ParsedDocument           (src/parsing/cli.py)
```

---

## 1. Cấu trúc

```
ParsedDocument
├── doc_id
├── source      {path, sha256}
├── parser      {docling_version, vlm_model, do_ocr, picture_area_threshold, options_hash}
├── sections[]  {id, title, pages: [đầu, cuối], source, confidence}
├── flags[]     {kind, severity, page_no, block_id, detail}
└── pages[]
     ├── page_no · title · slide_type · section_id · page_hash
     ├── blocks[]        NỘI DUNG, theo thứ tự đọc
     │    └── id · kind · role · content · polygon · provenance  (+ trường riêng từng loại)
     └── furniture       {header, footer[]}  (+ page_number khi LỆCH page_no)
```

**Mỗi block trả lời ba câu**, loại nào cũng vậy:

| | field | |
|---|---|---|
| nói gì | `content` | chữ · mô tả VLM · markdown bảng — thứ đem đi chunk làm KB |
| nằm đâu | `polygon` | 4 góc `[[l,t],[r,t],[r,b],[l,b]]`, `[0,1]`, gốc **trên-trái**, làm tròn 3 chữ số |
| tin được không | `provenance` | `text_layer` đúng 100% · `vlm` máy tả, có thể sai · `manual` người sửa · `ocr` |

Trường riêng theo `kind`:

| `kind` | `content` là | thêm |
|---|---|---|
| `paragraph` | chữ trên slide | `role` (luôn có) · `urls` khi `role: links` |
| `image` | mô tả của VLM | `why_empty` khi `content: null` |
| `table` | markdown **sinh từ** `cells` | `cells` (bản gốc, hàng đầu là header) · `caption` · `structure_provenance` |

**`role`** — `kind` nói mẩu này **là gì**, `role` nói robot **đối xử với chữ đó thế nào**:

| `role` | nghĩa | ai gán |
|---|---|---|
| `body` | đoạn văn thường | mặc định |
| `title` | tiêu đề trang | docling |
| `list` | bó gạch đầu dòng, MỘT block — S4 diễn đạt lại, không đọc bullet | docling |
| `links` | ≥ nửa số dòng là URL — **không đọc URL thành tiếng** | luật, tự gán cả lúc nạp lại |
| `caption` | chú thích | docling |

**`why_empty`** — ảnh không có `content` thì phải biết VÌ SAO:

| giá trị | nghĩa | cần xem? |
|---|---|---|
| `decorative` | logo, hoạ tiết — VLM xem rồi, không có nội dung | không |
| `area_below_threshold` | ảnh nhỏ hơn ngưỡng (5% trang), không gọi VLM | không |
| `not_described` | ảnh đủ to mà không có mô tả — mất nội dung thật | **có** → cờ `image_not_described` |
| `api_error` | gọi VLM mà lỗi — chạy lại có thể được | **có** |

**`furniture`** — chữ lặp ở mọi trang. **Không** vào KB, nhưng:

| field | nghĩa |
|---|---|
| `header` | thanh tiêu đề chạy — nguồn **duy nhất** dựng chương. Mẩu `page_header` đầu tiên; không có nhãn thì mẩu sát đỉnh (y < 0.15) |
| `footer` | mọi chữ lặp còn lại (tác giả, tên môn…) |
| `page_number` | số in trên slide (`"11 / 40"`) — **chỉ ghi khi LỆCH `page_no`** (slide ẩn/xoá/đánh số sai) → cờ `page_label_mismatch` |

Deck `.pptx` chưa có furniture: docling không gắn nhãn header/footer cho pptx.

**`slide_type`** — luật trên chính trang đó, không gọi model. Tính lại mỗi lần nạp, ghi ra
JSON để đọc. S4 viết theo loại trang, KB lọc trang phân mục:

| `slide_type` | luật | robot làm gì |
|---|---|---|
| `section_divider` | đúng 1 mẩu chữ, là tiêu đề, tâm giữa trang (cy ≥ 0.30, cx ∈ [0.35, 0.65]) | 1–2 câu chuyển chương |
| `exercise` | header LỆCH tiêu đề + có "bài tập \| yêu cầu \| deadline" | ĐỌC yêu cầu, không giảng |
| `content` | còn lại | giảng |

`title` (trang bìa) và `agenda` (mục lục) chưa làm — 2/40 trang, lợi ích nhỏ.

**Ghi JSON gọn:** trường rỗng (`null` / `[]` / `{}`) không ghi — trừ `content`, để nhìn là
thấy block nào không có nội dung. Nạp lại thì trường vắng lấy giá trị mặc định.
Mảng ngắn (polygon, hàng bảng, footer) viết trên một dòng.

---

## 2. Ví dụ thật — `3_datavisualization`

Trang 11 — một mẩu chữ, một ảnh có mô tả, một ảnh nhỏ bỏ qua:

```json
{
  "page_no": 11,
  "title": "Đồ thị dạng đường",
  "section_id": "sec_00",
  "page_hash": "c84115e0250727a7",
  "blocks": [
    {
      "id": "p011.b00",
      "kind": "paragraph",
      "role": "title",
      "content": "Đồ thị dạng đường",
      "polygon": [[0.023, 0.083], [0.373, 0.083], [0.373, 0.138], [0.023, 0.138]],
      "provenance": "text_layer"
    },
    {
      "id": "p011.b01",
      "kind": "image",
      "content": "Đoạn mã Python và biểu đồ đường ... plt.savefig('line_graph.png') ...",
      "polygon": [[0.22, 0.181], [0.776, 0.181], [0.776, 0.962], [0.22, 0.962]],
      "provenance": "vlm"
    },
    {
      "id": "p011.b02",
      "kind": "image",
      "content": null,
      "polygon": [[0.78, 0.934], [0.993, 0.934], [0.993, 0.961], [0.78, 0.961]],
      "provenance": "vlm",
      "why_empty": "area_below_threshold"
    }
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

Trang 38 — block link, `urls` tách sẵn:

```json
{
  "id": "p038.b02",
  "kind": "paragraph",
  "role": "links",
  "content": "https://www.nhatot.com/mua-ban-bat-dong-san-ha-noi\nhttps://batdongsan.com.vn/...",
  "urls": ["https://www.nhatot.com/mua-ban-bat-dong-san-ha-noi", "https://batdongsan.com.vn/...", "..."],
  "polygon": [[0.07, 0.343], [0.894, 0.343], [0.894, 0.883], [0.07, 0.883]],
  "provenance": "text_layer"
}
```

Header p38 là `"Dữ liệu địa lý"` nhưng tiêu đề là `"Bài tập nhóm chương 2+3"` — trang bài
tập kế thừa header chương trước. Lệch này là tín hiệu nhận trang `exercise` (CLAUDE.md §5).

---

## 3. Trong code

```python
from parsing.models import ParsedDocument

doc = ParsedDocument.load("out/parsed/3_datavisualization.json")   # file cũ -> báo 1 câu
page = doc.page(11)
doc.section_of(11)                          # chương của trang

for b in page.blocks:
    b.content, b.polygon, b.provenance      # field lưu
    b.box, b.center, b.area                 # tính từ polygon

page.paragraphs · page.images · page.tables # lọc theo loại
page.furniture.header                       # = page.running_header
page.compute_hash()                         # nội dung + vị trí + furniture

doc.to_json()                               # đúng định dạng ghi ra file
```

Luật dễ quên:

- **Không có `page_no` / `reading_order` / `layer` trong block.** Block nằm trong trang
  nào là biết trang; thứ tự đọc là thứ tự trong mảng; furniture đã tách riêng.
- **`id` ổn định**: `p<trang>.b<số thứ tự>`, chỉ đánh cho block nội dung. Block vá tay là
  `p<trang>.m<số>`. Chunk và câu kịch bản trỏ vào `id`.
- **Bảng có hai `provenance`** (NT2): chữ trong ô từ text layer (đúng), lưới hàng/cột do
  TableFormer dựng (`structure_provenance: vlm`, có thể xếp số nhầm hàng).
- **`content` của bảng và `urls` của link được tính lại mỗi lần NẠP** — không lệch được
  với `cells` / chữ gốc. Sửa `cells` trong bộ nhớ thì phải dựng lại object.
- **`sections` được SUY RA**, không parse ra — nên bắt buộc khai `source` + `confidence`.
- **Toạ độ `.pptx`**: docling gắn nhãn `BOTTOMLEFT` nhưng số thật đo từ ĐỈNH. `from_docling`
  không tin nhãn với `.pptx` — tin là lật trục y (đo được ở `tetnguyendan` p1).
- **`vlm_model` đọc từ chính output docling**, không từ `.env` — `.env` có thể đã đổi sau
  lần gọi VLM.

---

## 4. Cờ

| `kind` | nghĩa |
|---|---|
| `header_title_mismatch` | header nói một đằng, tiêu đề trang một nẻo. KHÔNG bắn ở trang `exercise` — ở đó lệch là tín hiệu phân loại |
| `empty_page` | không chữ, không mô tả ảnh → vào KB gần như rỗng. KHÔNG bắn ở trang `section_divider` — rỗng là đúng thiết kế |
| `image_not_described` | ảnh có `why_empty` là `not_described` / `api_error` |
| `page_label_mismatch` | số trang in trên slide lệch số trang thật |
| `no_sections` | không dựng được chương (deck không có thanh header) |

---

## 5. Chạy

```powershell
# ① docling + VLM mô tả ảnh (gọi API)
.venv\Scripts\python.exe scripts\parse_api.py data\raw\<ten>.pptx

# ② ra ParsedDocument
.venv\Scripts\python.exe src\parsing\cli.py "out\parse_api\<ten>.json" -o out\parsed\<ten>.json

# xem một trang
.venv\Scripts\python.exe src\parsing\cli.py out\parsed\<ten>.json --page 9-11
```

- ② tự áp file vá tay `data\patches\<ten>.json` nếu có. Áp lại bao nhiêu lần cũng như một lần.
- ② thoát mã `1` khi có cờ mức `error` — vẫn ghi file, mã lỗi để CI bắt. Hai deck hiện đều ra `0`.
- File parse theo định dạng cũ không nạp được → chạy lại ② từ `out\parse_api\` (miễn phí).

```
docling .json ─► from_docling.py   theo body.children → thứ tự đọc; đổi toạ độ; tách furniture
              ─► patch.py          vá tay (nếu có)
              ─► sections.py       thanh header → chương
              ─► flags.py          soi luật → cờ
              ─► cli.py            ghi <ten>.json  ─► S5 KB · S4 kịch bản
```

---

## 6. Số đã kiểm — chạy lại phải ra đúng, lệch là có lỗi

| | `3_datavisualization` (.pdf) | `tetnguyendan` (.pptx) |
|---|---|---|
| trang | 40 | 10 |
| block | 43 title + 13 body + 10 list + 1 links + 71 ảnh (gồm 2 block vá tay) | 43 body + 15 ảnh |
| ảnh có `content` (vào KB) | 27 — VLM tả 28, 1 cái là `decorative` | 6 |
| trang có header | 32 | 0 — pptx không có nhãn |
| chương | 7, chương đầu p9–15, khớp mục lục 7/7 | 0 |
| `slide_type` | 30 content + 7 section_divider + 3 exercise (p38–40) | 10 content |
| cờ | **0** (trước khi có `slide_type`: 7 `empty_page` oan + 3 `header_title_mismatch`) | 1 `no_sections` |
| kích thước file | 74 KB (định dạng cũ: 362 KB) | 21 KB (cũ: 68 KB) |

Ca âm tính — `Chương1.pdf`: chỉ 1/12 trang có thanh header → trượt luật phủ 60% →
**0 chương**, đúng như mong đợi (không đoán bừa).
