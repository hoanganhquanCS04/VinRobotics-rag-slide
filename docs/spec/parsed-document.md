# ParsedDocument — cấu trúc dữ liệu sau khi parse PDF

**Code:** [`src/parsing/`](../../src/parsing/) · **Vào:** file `.json` docling sinh · **Ra:** `out/parsed/*.json`

---

## 0. Bối cảnh v0 — một file làm cả hai việc ★

Thiết kế gốc ([CLAUDE.md §3](../../CLAUDE.md)) có hai nguồn tách biệt: deck `.pptx` để
trình chiếu, `source/*.pdf` làm tài liệu nền. **Hiện tại không như vậy** — chỉ có
**một file PDF, vừa là deck vừa là KB**.

Nên `ParsedDocument` đang gánh hai vai:

```
                      ┌──► làm DECK  →  S1 → S2 → S4 Scenario  (robot nói gì)
một file .pdf ──►  ParsedDocument
                      └──► làm KB    →  S5 chunk + embed       (robot tra gì)
```

**Ba hệ quả**, không lờ đi được:

1. **Không có `chart_data` / `tables` / `build_steps` bản chuẩn.** Chúng đến từ XML của
   pptx. Với PDF, số liệu biểu đồ do VLM đọc từ pixel → luôn là `provenance: vlm`.
2. **S3 Alignment vô nghĩa ở v0.** Align slide với nguồn mà nguồn chính là slide thì
   mỗi trang map vào chính nó, không sinh thêm tri thức. Bỏ qua cho tới khi có tài
   liệu nguồn riêng.
3. **Robot chỉ trả lời ở mức mô tả slide.** Đúng cảnh báo
   [s5 §8](../offline/s5-kb-construction.md). Ngưỡng từ chối phải nâng cao, và
   **tuyệt đối không để LLM tự phình kiến thức từ slide ra để bù**.

Lối thoát duy nhất: đưa vào **tài liệu nguồn thật** tách khỏi deck.

**Lưu ở đâu:** file JSON trên đĩa, chưa có vector DB.

```
data/raw/<ten>.pdf                        file gốc
out/parse_api/<ten>__<model>.{md,json}    docling thô
out/parsed/<ten>.json                     ParsedDocument   ← file này
out/pages/<ten>_pNNN.png                  ảnh có khung bbox
```

---

## 1. Để làm gì

Biến một file PDF thành thứ máy đọc được, theo ba tầng:

```
📦 TÀI LIỆU
   ├── 📄 TRANG   (40 cái)
   │      └── 🧩 MẨU   (chữ / bảng / ảnh)
   ├── 📑 CHƯƠNG  (trang nào thuộc chương nào)
   └── 🚩 CỜ      (chỗ nào có vấn đề, cần người xem)
```

Mỗi **mẩu** trả lời đúng ba câu:

| | field | ví dụ |
|---|---|---|
| nội dung gì | `embed_text()` | `"Đồ thị dạng đường"` |
| nằm chỗ nào | `bbox` | góc trên trái, chiếm 1.9% trang |
| ai sinh ra | `provenance` | `text_layer` (chắc đúng) / `vlm` (có thể sai) |

Cột cuối quan trọng nhất — nó là NT2 (§2 CLAUDE.md) đóng thành kiểu dữ liệu.

---

## 2. Cây kế thừa — ai là LOẠI của ai

```
Block                    ← tên gọi chung: "một mẩu nằm trên trang"
   │                       ai cũng có: id, page_no, bbox, layer, reading_order, provenance
   │
   ├── ParsedParagraph    mọi thứ là CHỮ
   ├── ParsedTable        bảng
   └── ParsedImage        ảnh
```

`Block` chỉ là tên gọi chung — không có mẩu nào "là Block thuần". Ba cái dưới mới là
hàng thật.

**Tác dụng:** khai `bbox`, `page_no`, `provenance` một lần ở `Block`, ba đứa con tự có.
Nhờ vậy duyệt được mà không cần biết đang cầm loại nào:

```python
for b in page.blocks:
    print(b.page_no)        # cái nào cũng có
    print(b.embed_text())   # mỗi loại tự trả kiểu của nó
```

---

## 3. Cây chứa — ai NẰM TRONG ai

```
ParsedDocument
 ├─ source            file nào, hash gì
 ├─ parser            model nào, có bật OCR không
 │
 ├─ pages     [40] ─► ParsedPage
 │                      ├─ title          tiêu đề trang
 │                      ├─ section_id     thuộc chương nào
 │                      ├─ page_hash      để build lại phần đổi thôi (§8)
 │                      ├─ blocks    [*]  ◄── NỘI DUNG THẬT
 │                      └─ furniture [*]  ◄── header/footer, để riêng
 │
 ├─ sections  [7]  ─► SectionSpan    "p9→15 = Đồ thị dạng đường"
 └─ flags     [11] ─► Flag           "p38 header ghi sai"
```

---

## 4. Từng class

### `Block` — lớp cha

| field | nghĩa |
|---|---|
| `id` | tên riêng, kiểu `p010.b03`. Cờ và chunk trỏ vào cái này |
| `page_no` | trang số mấy |
| `bbox` | toạ độ, chuẩn hoá `[0,1]`, gốc **trên-trái** |
| `layer` | `body` (nội dung) hay `furniture` (khung trang) |
| `reading_order` | thứ tự đọc trên trang |
| `provenance` | `text_layer` · `vlm` · `ocr` · `derived` |

### `ParsedParagraph` — mọi thứ là chữ

```
text       nội dung
text_raw   bản chưa dọn
role       title | body | list | caption
.lines     tách thành từng dòng (có nghĩa khi role="list")
```

**Bó gạch đầu dòng KHÔNG có class riêng.** Nó là `role="list"`, các dòng ngăn nhau
bằng xuống dòng. Trang 36 ra thế này:

```
p036.b01  paragraph  role=title  "Dữ liệu địa lý"
p036.b02  paragraph  role=list   "Một loại trực quan hóa phổ biến...
                                  Công cụ chính của Matplotlib...
                                  Cartopy là một thư viện Python...
                                  Cartopy được xem là người kế thừa...
                                  Bên cạnh đó hiện nay API Google Maps..."
```

Lý do giữ `role="list"` thay vì gộp hẳn vào `body`: §5 S4 cấm robot đọc bullet nguyên
văn — S4 cần biết mẩu này là danh sách để diễn đạt lại thành lời nói.

Lý do **gom cả bó vào một mẩu** thay vì tách từng dòng: mỗi dòng lẻ chỉ vài chữ, không
dòng nào trả lời được câu hỏi. Cả bó mới là một câu trả lời — ví dụ trang 40 có
`"Deadline: 25/10/2025"` nằm chung với hai dòng khác về bài tập.

### `ParsedTable` — bảng

`cells` (mảng 2 chiều) · `n_rows` · `n_cols` · `header_rows`

Có **hai** `provenance` vì hai nguồn khác nhau:
- `provenance` — chữ trong ô, từ text layer, **đúng**
- `structure_provenance` — lưới do TableFormer dựng, **có thể sai**

`rows_as_chunks()` cắt mỗi hàng một chunk và **lặp header ở mỗi hàng** (luật §5 S5).

### `ParsedImage` — ảnh

| field | nghĩa |
|---|---|
| `description` | lời VLM tả. Đây là **toàn bộ** nội dung của mẩu ảnh |
| `described_by` | model nào tả, vd `gemini-2.5-flash-lite@api` |
| `prompt_hash` | prompt nào sinh ra — đổi prompt thì mô tả cũ lạc hậu |
| `skip_reason` | vì sao không gọi API: `area_below_threshold` / `decorative` / `not_described` |
| `is_decorative` | logo, hoạ tiết → không có nội dung |
| `classification` | `[("line_chart", 0.52), …]` |

**`skip_reason` là thứ docling không lưu mà ta cần.** Nhìn `description=None` phải biết
được là *chưa gọi* hay *gọi mà fail* — hai ca xử lý khác hẳn nhau.

### `ParsedPage` — một trang

`title` · `section_id` · `blocks` · `furniture` · `page_hash`

| thuộc tính tính sẵn | nghĩa |
|---|---|
| `images` / `tables` / `paragraphs` | lọc theo loại |
| `body_text` | nối mọi mẩu thành một chuỗi |
| `running_header` | thanh tiêu đề chạy ở đỉnh — nguồn duy nhất dựng được chương |
| `page_label` | số trang in trên giấy, `"11 / 40"` — đối chiếu với `page_no` |
| `is_text_starved` | ≤1 mẩu chữ → trang sống chết nhờ mô tả ảnh |

### `SectionSpan` — một chương

`title` · `start_page` · `end_page` · `source` · `confidence`

**Được SUY RA, không phải parse ra** — nên bắt buộc khai `source` và `confidence`.
`source` ∈ `page_header` / `title_bbox` / `outline_page` / `manual`.

### `Flag` — chỗ cần người xem

`kind` · `page_no` · `block_id` · `detail` · `severity`

| kind | nghĩa |
|---|---|
| `header_title_mismatch` | thanh header nói một đằng, tiêu đề trang một nẻo |
| `empty_page` | không chữ, cũng không mô tả ảnh → vào KB gần như rỗng |
| `image_not_described` | ảnh **trên** ngưỡng mà không tả được |
| `page_label_mismatch` | số trang in trên giấy lệch số trang thật |
| `no_sections` | không dựng được chương |

---

## 5. Ví dụ thật — trang 11 của `3_DataVisualization`

```
title: Đồ thị dạng đường          thuộc: sec_00 (p9–15)

blocks:
   p011.b01  paragraph   1.89%   text_layer   Đồ thị dạng đường
   p011.b02  image      43.43%   vlm          Đoạn mã Python và biểu đồ đường...
   p011.b03  image       0.58%   vlm          (rỗng — thanh PowerPoint, bỏ qua)

furniture:
   Đồ thị dạng đường · VH Thư · Nhập môn Khoa học dữ liệu · 11 / 40
```

Trang này **chỉ có 1 mẩu chữ**, trùng tiêu đề với 6 trang khác cùng chương. Thứ phân
biệt nó là mô tả ảnh — `plt.savefig('line_graph.png')` chỉ tồn tại nhờ tầng VLM.
Đây chính là insight §1 CLAUDE.md: slide là bản nén mất mát.

---

## 6. Vì sao giữ `furniture`

Nhìn thì như rác — 152/252 mẩu chữ của deck này là header/footer lặp. Nhưng:

1. **`page_header` là nguồn chương duy nhất.** docling cho `level=1` trên cả 43 tiêu đề,
   không có phân cấp nào. Thanh header chạy mới gom được trang thành chương.
2. **Bắt lỗi bộ slide.** So header với tiêu đề ra ngay 3 trang lệch (p38–40).
3. **`page_footer` kiểm toàn vẹn.** `"11 / 40"` đối chiếu với `page_no` → biết có sót trang.
4. **Chứng minh được là đã loại**, chứ không phải quên loại: `len(blocks) + len(furniture)`
   phải khớp tổng mẩu của trang.

Giữ thì gần như miễn phí; bỏ rồi muốn lấy lại phải parse lại, mà parse lại **tốn tiền API**.

---

## 7. Dùng

```python
import json
from parsing.models import ParsedDocument

doc = ParsedDocument.model_validate(json.load(open("out/parsed/xxx.json", encoding="utf-8")))

doc.page(11)                  # lấy trang 11
doc.section_of(11)            # trang 11 thuộc chương nào
doc.pages_in("sec_00")        # chương sec_00 gồm trang nào
doc.iter_blocks()             # duyệt mọi mẩu của cả tài liệu

page = doc.page(11)
page.images                   # ảnh của trang
page.paragraphs               # mẩu chữ của trang
page.is_text_starved          # trang này ít chữ quá không
[b.embed_text() for b in page.blocks]
```

Sinh ra:

```powershell
.\.venv\Scripts\python.exe src\parsing\cli.py `
  "out\parse_api\<ten>__gemini-2.5-flash-lite.json" `
  --vlm-model gemini-2.5-flash-lite -o out\parsed\<ten>.json
```

Exit code `1` khi có cờ mức `error` — để CI bắt được. Parse vẫn thành công.

---

## 8. Dòng chảy

```
PDF ──docling──► file .json
                    │
                    ├─ from_docling.py   đi theo body.children → đúng thứ tự đọc
                    │                    đổi toạ độ, tách body/furniture
                    ├─ sections.py       đọc page_header → các chương
                    ├─ flags.py          soi 4 luật → danh sách cờ
                    └─ cli.py            gói lại, ghi ra JSON
                                              │
                                              ▼
                                         S5 KB Construction
```

Mỗi bước nhận `ParsedDocument`, trả `ParsedDocument`. Chạy riêng từng bước được, dừng ở
đâu cũng ghi ra file đọc lại được (§9).

---

## 9. Số đã kiểm — `3_DataVisualization.pdf`

Chạy lại phải ra đúng mấy số này, lệch là có lỗi:

| | |
|---|---|
| trang | 40 |
| tái dựng đủ mẩu chữ | 54 paragraph + 46 dòng bullet + 152 furniture = **252** |
| ảnh | 71, mô tả được 27 (1 cái trả `DECORATIVE`) |
| chương | 7, chương đầu p9–15 |
| đối chiếu mục lục | 7/7 → confidence 0.95 |
| cờ | 8 `empty_page` + 3 `header_title_mismatch` |

Ca âm tính — `Chương1.pdf`: chỉ 1/12 trang có thanh header → trượt luật phủ 60% →
**0 chương**, đúng như mong đợi (không đoán bừa).
