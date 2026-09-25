# KBChunk — cắt tài liệu thành mẩu để tìm

**Vào:** `out/parsed/*.json` (`ParsedDocument`) · **Ra:** `out/kb/*.json` · **Code:** `src/kb/` *(chưa viết)*

---

## 1. Chunk để làm gì

Khán giả hỏi một câu. Có **hai loại**, đi hai đường khác nhau:

```
"sơ đồ bên trái là gì?"            → hỏi về TRANG ĐANG CHIẾU
                                     → trang đó đã nằm SẴN trong prompt
                                     → lọc bbox → trả lời
                                     → KHÔNG đụng tới chunk

"Cartopy khác Basemap thế nào?"    → thứ không có trên màn hình
                                     → tìm trong 40 chunk → ra trang 36
                                     → ĐÂY mới là việc của chunk
```

Đây là ranh giới §6 CLAUDE.md đặt ra:

```
TRẠNG THÁI  -> inline, bounded   "tôi đang nhìn gì" — không index nào trả lời được
TRI THỨC    -> TRUY XUẤT         slide khác, chunk KB
```

Không thể nhét cả 40 trang vào prompt (§10 cấm). Nên cắt nhỏ, nhúng vector, rồi tìm.

**Chunk chỉ cần đủ tốt để tìm ra ĐÚNG TRANG.** Chỉ vào đúng phần tử nào trên trang là
việc của `bbox`, không phải của chunk.

---

## 2. Đơn vị: một trang = một chunk

Đo trên `3_DataVisualization` (40 trang):

```
token mỗi chunk:  min 18 · trung vị 144 · max 353
KHÔNG chunk nào vượt 500  ->  không phải cắt nhỏ
```

Ba lý do, xếp theo sức nặng:

1. **Trang là đơn vị điều hướng của runtime.** R2 nhảy tới *một trang*. Chunk vắt qua
   hai trang thì trả về không biết nhảy đâu. `KBChunk` trong
   [s5](../offline/s5-kb-construction.md) cũng chỉ có field `page` số ít.
2. **Trang đã đủ nhỏ.** Luật 300–500 token của §5 S5 nhắm vào tài liệu văn xuôi dày.
   Slide trung vị 144 — cắt nhỏ nữa thành vô nghĩa.
3. **Không cắt giữa câu** — tự động thoả, ranh giới chunk là ranh giới trang.

---

## 3. Hình dạng một chunk

```
[Đồ thị dạng đường · trang 11/40]          ← tiền tố ngữ cảnh (text_enriched)
Đồ thị dạng đường                           ← tiêu đề trang
Đoạn mã Python và biểu đồ đường hiển thị    ← paragraph + mô tả ảnh, theo thứ tự đọc
các câu lệnh `x = [1,2,3,4]`, `y = [1,4,9,16]`,
`plt.plot(x,y)`, `plt.savefig('line_graph.png')`...
```

**Tiền tố là phần contextual enrichment** mà §5 S5 gọi là "bước quan trọng nhất". Ta có
sẵn `sections` + `page_no` nên **không phải gọi LLM** — rẻ hơn hẳn cách gốc (sinh câu
bối cảnh bằng LLM cho từng chunk).

Với bộ deck này thì nó không phải trang trí: 7 trang `p9–p15` có tiêu đề **giống hệt
nhau**. Không có `· trang 11/40` thì càng khó tách.

Bỏ `furniture` (header/footer) — 152/252 mẩu chữ của deck là loại này, vào KB là 40 bản
sao của cùng một dòng.

---

## 4. Nhiều ảnh trên một trang → nhiều vector, cùng một trang

Đo được **5/40 trang** có từ 2 ảnh được mô tả trở lên, và mẫu rất rõ:

```
p19  code Python vẽ bubble chart  +  biểu đồ tán xạ kết quả
p24  code Python                  +  biểu đồ có thanh sai số
p34  code matplotlib + numpy      +  biểu đồ 3D scatter
p37  code cartopy                 +  quả địa cầu bán cầu Bắc
p20  3 ảnh hoa iris (setosa · versicolor · virginica)
```

Bốn trang đầu là **cùng một thứ**: đây là code, đây là cái nó vẽ ra. Tách đôi thì hỏng —
hỏi *"làm sao vẽ scatter 3D"* cần cả hai.

Nhưng gộp một vector thì **loãng**: chunk 338 token của p19 trộn từ ngữ của code lẫn mô
tả hình, vector ra là bình quân hai chủ đề.

Gỡ bằng đúng nguyên tắc §5 S6a đã dùng cho slide (*multi-field embed, KHÔNG gộp một
vector*):

```
trang 19  ──┬── vector A : cả trang           338 tok
            ├── vector B : mô tả ảnh code     212 tok
            └── vector C : mô tả ảnh biểu đồ  108 tok

            cả ba trỏ về  page_no = 19
```

Khớp vector nào cũng ra trang 19 — điều hướng không đổi, mà không loãng.

Chi phí: 40 chunk trang + ~33 mô tả ảnh ≈ **73 vector**. Chưa tới một xu.

---

## 5. Trang phân mục — đánh dấu, KHÔNG vứt

7 trang `p9, p16, p22, p25, p29, p32, p35` chỉ có dải tiêu đề, **18 token**. Chúng đúng
là trang mở đầu của 7 chương. Embed là rác lẫn vào index.

Nhưng **không xoá** — đánh `content_type: "section_divider"` rồi lọc khỏi truy vấn mặc
định. Hai lý do: §10 cấm vứt chunk, và nếu luật nhận diện sai thì còn dữ liệu để sửa,
khỏi parse lại (parse lại **tốn tiền API**).

---

## 6. Metadata

```python
chunk_id       "3_DataVisualization#p011"
page_no        11
section_id     "sec_00"
section_title  "Đồ thị dạng đường"
block_ids      ["p011.b01", "p011.b02"]      ← truy ngược về đúng mẩu
provenance     {"text_layer": 1, "vlm": 1}   ← phần nào chắc đúng, phần nào model sinh
content_type   "content" | "section_divider"
token_count    178
vector_role    "page" | "image"              ← multi-vector, xem §4
```

**`provenance` đếm theo mẩu** là chỗ cố ý khác luật gốc. NT2 đòi mọi field khai nguồn,
nhưng chunk **trộn** hai loại: tiêu đề từ text layer (đúng 100%), mô tả ảnh do VLM sinh
(có thể bịa). Không ghi tỉ lệ thì lúc R4 trả lời không biết phần nào tin được.

`block_ids` cho phép truy ngược về `ParsedDocument`, nên `grounding` của NT3 chỉ được
đúng vào ảnh `p019.b02` chứ không phải chung chung cả trang.

---

## 7. Khi nào cắt thêm

Chỉ khi chunk **vượt 500 token**. Lúc đó cắt theo **ranh giới block**, không cắt giữa
mẩu. Mỗi mảnh giữ nguyên tiền tố ngữ cảnh, thêm hậu tố `#p011.1`, `#p011.2`.

File hiện tại chưa có ca nào (max 353).

---

## 8. Nhúng vector

Đo thật trên endpoint đang dùng:

| model | chiều | độ trễ 1 câu | MIRACL đa ngữ | giá |
|---|---|---|---|---|
| **`text-embedding-3-small`** ✅ | 1536 | **719ms** | 44.0% | 1× |
| `text-embedding-3-large` | 3072 | 1352ms | 54.9% | 6.5× |
| `text-embedding-ada-002` | 1536 | 749ms | 31.4% | 1.3× |

**Chọn `3-small`.**

- **Loại `ada-002`**: cùng chiều, cùng độ trễ với `3-small` nhưng kém 13 điểm đa ngữ.
  Model 2022, đã bị thay thế. Thua mọi mặt.
- **Không chọn `3-large`** vì độ trễ. Ngân sách runtime là **< 2.5s tới byte audio đầu**
  (§2 NT1). Mỗi câu hỏi phải nhúng trước khi truy xuất được — nó nằm **trên đường găng**.
  `3-large` ăn 54% ngân sách chỉ để nhúng một câu. Đổi 11 điểm chất lượng lấy 633ms là
  không đáng, nhất là khi nút thắt hiện tại là **chất lượng parse**, không phải model nhúng.

Đổi model sau chỉ là một dòng config + nhúng lại 73 vector, mất vài giây.

**Hai điều phải nhớ:**

1. **API cho dense-only, không có sparse.** §5 S5 bắt buộc hybrid → phải thêm BM25 riêng
   (`rank-bm25`). Với tiếng Việt lẫn thuật ngữ Anh (`matplotlib`, `plt.savefig`,
   `Cartopy`) thì BM25 không phải tuỳ chọn — nó bắt đúng mấy từ khoá dense hay trượt.
2. **719ms là giá của việc gọi mạng.** Đã đo `bge-m3` local trên chính máy này:
   **182ms/câu hỏi**, nhanh gấp 4, không cần mạng, và cho cả dense lẫn sparse trong một
   lần forward — đúng thứ §9 chỉ định. Vẫn chọn API vì nó ngốn 4.3 GB đĩa và lần nạp
   nguội đầu mất ~10 phút. Khi siết ngân sách 2.5s thì đây là chỗ quay đầu đầu tiên.
   Lý do đầy đủ ở [embedding.md §2](./embedding.md).

> Lưu ý kỹ thuật: endpoint chặn User-Agent của `urllib` (Cloudflare error 1010).
> Phải gọi bằng `httpx` hoặc `requests`.

---

## 9. Luật chốt

```
đơn vị        1 trang = 1 chunk chính
+ phụ         mỗi mô tả ảnh = 1 vector phụ, cùng trỏ về page_no
tiền tố       [<tên chương> · trang N/M]
nội dung      tiêu đề + paragraph + mô tả ảnh, theo thứ tự đọc
bỏ qua        furniture (header/footer)
đánh dấu      trang phân mục -> content_type=section_divider, lọc khỏi tìm kiếm
cắt thêm      chỉ khi > 500 token, cắt theo ranh giới block
nhúng         text-embedding-3-small (API) + BM25 (rank-bm25)
```

---

## 10. Phải đo, chưa biết

Hai câu chỉ có số mới trả lời được — làm xong `src/kb/` thì chạy ngay:

**Self-retrieval** (§5 S6a · gate §11 ≥ 90%): lấy nội dung trang `i` làm truy vấn, top-1
phải ra đúng trang `i`. Đây là **vòng phản hồi đầu tiên** của cả dự án — nó đo xem parse
có đủ tốt để tìm được không, bằng số thật.

Nghi ngờ cụ thể cần kiểm:

- **7 trang `p9–p15` cùng tiêu đề** — tiền tố `· trang N/40` tách được bao nhiêu?
- **`p15` mất nội dung** (docling bỏ sót code + bảng màu, xem
  [parsed-document.md §0](./parsed-document.md)) — chunk 18 token, chắc chắn trượt
- **7 trang phân mục** — lọc đúng chưa, hay lọc nhầm trang có nội dung

Kết quả audit quyết định việc tiếp theo: sinh `message` (S1), cứu `p15`, hay thêm
`slide_type`. **Đừng đoán trước khi có số.**
