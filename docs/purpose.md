# Purpose

Robot tự thuyết trình một bộ slide và trả lời khán giả ngay trong lúc đang nói — hỏi gì
đáp nấy, muốn xem lại trang nào thì quay về trang đó.

Tách hai nhánh vì hai ràng buộc ngược nhau: **offline không giới hạn thời gian, online
chỉ có vài giây.** Mọi thứ tính trước được đều đẩy hết về offline.

## Phạm vi v1

**Một deck, hỏi đáp trong đúng deck đó.** Không có tài liệu nguồn ngoài — **kho tri thức
chính là bộ slide**. Làm chạy được cái này trước, mở rộng ra tài liệu ngoài sau.

| Trong v1 | Để lại v2 |
|---|---|
| 1 file PDF, mỗi bước animation một trang | Tài liệu nguồn ngoài deck (SRS, báo cáo, transcript) |
| Index duy nhất trên chính deck | Alignment slide ↔ chunk nguồn |
| Khán giả hỏi bằng lời | `qa_cache`, nhiều deck một phiên |

> **Cái giá phải trả, nói thẳng:** không có nguồn ngoài thì robot **không trả lời được câu
> "tại sao"** sâu hơn những gì slide viết. Hỏi vượt quá deck → nói không biết, đừng bịa.
> Chỉ cần thêm 1–2 tài liệu văn xuôi là đổi hẳn chất lượng, và code không phải viết lại.

---

## I. Offline — dựng sẵn trước giờ diễn

```
deck.pdf  ──► [ingest]  cắt + trích, KHÔNG gọi model
                 │        → text_raw, items(bbox, crop), hash
                 ▼
              [gom nhóm]  trang animation → slide ngữ nghĩa
                 │        → ~45 trang thành ~20 slide
                 ▼
              [1× LLM/slide]  hiểu slide
                 │        → content, image_content, scenario chia theo bước
                 ▼
              [index]  mỗi slide 1 điểm, 4 vector
                          → self-retrieval check
```

### Ingest — cắt và trích

PDF cho ba nguồn dữ liệu mỗi trang, lấy hết bằng PyMuPDF, **không cần model**: text layer
(chữ + bbox), vùng ảnh và vùng vẽ vector, và pixel khi render.

```
1. render trang → p12.png                    (~150 DPI, ~1600px cạnh dài)
2. trích text block + bbox, sort theo cột rồi theo y
3. dò vùng hình: get_drawings() cụm lại  +  get_images()
4. crop vùng hình TỪ PNG RENDER (không lấy file ảnh nhúng — nó chưa crop/che)
5. đoán title (luật ở dưới); không có thì để null
6. NFC hoá toàn bộ text
7. hash(text + bytes ảnh) → lần sau biết trang nào đổi
```

> **Vì sao tách ingest khỏi LLM:** ingest deterministic nên hash được, sửa 3 slide thì chỉ
> chạy lại LLM cho 3 slide. Gộp chung là mỗi lần build lại tốn tiền cho cả deck.

### Gom nhóm trang animation

Deck xuất **mỗi bước animation một trang**, nên phải tách rõ hai đơn vị — lẫn hai cái này là
hỏng cả index lẫn điều hướng:

| | Đơn vị | Số lượng | Dùng cho |
|---|---|---|---|
| **Trang chiếu** | 1 trang PDF = 1 bước | ~45 | Hiển thị · `next_slide` · `prev_slide` |
| **Slide ngữ nghĩa** | 1 nhóm trang = 1 slide gốc | ~20 | **Index · gọi LLM · scenario · `find_slide`** |

Gom nhóm bằng code, không cần model:

```
với mỗi cặp trang liền kề (k, k+1):
    text(k) ⊆ text(k+1)  và  drawings(k) ⊆ drawings(k+1)
        → cùng nhóm (k+1 chỉ là k cộng thêm phần tử)
    có phần tử BIẾN MẤT → mở nhóm mới
```

Animation kiểu đổi màu / highlight không thêm chữ nào — tập text bằng nhau. **Bằng nhau vẫn
tính là cùng nhóm**, chỉ tách khi có phần tử biến mất.

Index 45 trang gần giống hệt nhau thì self-retrieval loạn, `find_slide` trả về bước 2/5 của
một slide, và confidence gate lúc nào cũng báo "hai ứng viên sát nhau" — vì chúng **đúng là**
sát nhau.

### 1× LLM mỗi slide — hiểu slide

Gọi **một lần cho mỗi nhóm**, không phải mỗi trang. 20 call chứ không phải 45 — và quan trọng
hơn: 45 call cho ra 45 mô tả không nhất quán của cùng một cái hình.

| Đưa vào | Vì sao |
|---|---|
| `page_png` của **trang cuối nhóm** | Trạng thái đầy đủ. Cần thấy bố cục: mũi tên nối gì với gì, cột nào cao hơn |
| `text_raw` — chữ đã trích chính xác | Để model **khỏi đọc chữ từ pixel**. Chữ đã đúng sẵn, đưa vào để copy |
| `delta_text` từng bước | Tính bằng code. Để model chia `scenario` theo bước, không nói trước cái chưa hiện |
| `image_id[]` + bbox | Để model trả về đúng id nào ứng với vùng nào |
| Title slide trước/sau | Để hiểu mạch — **cấm để lọt vào chữ nó viết ra** |

Một lần gọi trả về hết: `content` của slide, `image_content` cho từng hình, và `scenario`
đã chia theo bước.

> **Luật ghi vào prompt:** `title` và các con số trong `text_raw` đã đúng sẵn — **cấm sinh
> lại**. Đưa cho model viết lại là tự tạo cơ hội cho nó bịa lại cái đang đúng.
> **Ngoại lệ:** trang scan (`text_source: "vlm"`) thì chữ chính là model đoán ra — lúc đó số
> liệu phải flag cho người soát.

### `slides.jsonl` — 1 dòng = 1 slide ngữ nghĩa

```json
{
  "deck_id": "vinrobotics-intro-2026",
  "slide_id": "s07",
  "pages": [12, 13, 14],
  "display_page": 14,
  "display_no": 7,
  "hash": "a3f9c1d2...",

  "title": "Kiến trúc hai nhánh",
  "text_raw": "Kiến trúc hai nhánh\nOffline · Online\nHội tụ tại Alignment",
  "text_source": "native",
  "page_png": "render/p14.png",

  "steps": [
    {"page_no": 12, "delta_text": "Kiến trúc hai nhánh"},
    {"page_no": 13, "delta_text": "Offline"},
    {"page_no": 14, "delta_text": "Online · Hội tụ tại Alignment"}
  ],

  "content": {
    "message": "Hệ thống tách làm nhánh offline và nhánh online, hội tụ tại bước alignment.",
    "description": "Sơ đồ hai cột chạy song song, mũi tên từ cả hai cột chụm vào một khối ở giữa.",
    "entities": ["offline", "online", "alignment"],
    "keywords": ["kiến trúc", "hai nhánh", "song song", "hội tụ"]
  },

  "items": [
    {
      "item_id": "s07_i01",
      "type": "text",
      "order": 0,
      "bbox": [0.08, 0.06, 0.92, 0.15],
      "text": "Kiến trúc hai nhánh",
      "role": "primary"
    },
    {
      "item_id": "s07_i02",
      "type": "figure",
      "order": 1,
      "bbox": [0.10, 0.22, 0.90, 0.78],
      "image_id": "s07_img01",
      "crop_path": "crop/s07_img01.png",
      "image_type": "diagram",
      "source": "vector",
      "image_content": "Sơ đồ hai nhánh chạy song song: nhánh trái xử lý deck, nhánh phải xử lý tài liệu nguồn, hai nhánh gặp nhau tại khối Alignment ở giữa.",
      "role": "primary"
    },
    {
      "item_id": "s07_i03",
      "type": "figure",
      "order": 2,
      "bbox": [0.88, 0.92, 0.98, 0.98],
      "image_id": "s07_img02",
      "crop_path": "crop/s07_img02.png",
      "image_type": "logo",
      "source": "bitmap",
      "image_content": null,
      "role": "decorative"
    }
  ],

  "scenario": {
    "steps": [
      {"page_no": 12, "text": "Đây là quyết định kiến trúc lớn nhất của cả hệ thống.", "est_seconds": 8},
      {"page_no": 13, "text": "Nhánh offline lo phần chuẩn bị, không bị ép thời gian.", "est_seconds": 16},
      {"page_no": 14, "text": "Còn nhánh online chỉ tra lại cái đã dựng sẵn.", "est_seconds": 18}
    ],
    "grounding": ["s07_i01", "s07_i02"]
  },

  "flags": [],
  "meta": {
    "ingested_at": "2026-09-21T10:12:03Z",
    "llm_model": "claude-opus-5",
    "prompt_version": "slide-understand-v3"
  }
}
```

| Trường | Ai sinh | Dùng để |
|---|---|---|
| `pages` / `display_page` | gom nhóm | Trang nào thuộc slide này · nhảy về thì chiếu trang nào (trang cuối = hình đầy đủ) |
| `display_no` | ingest | **Số in trên slide**, khác `page_no`. Khán giả nói *"slide 7"* theo số này |
| `steps[].delta_text` | gom nhóm | Bước này làm hiện thêm chữ gì → chia `scenario`, không nói trước |
| `text_source` | ingest | `native` = chữ đúng 100%, cấm sinh lại · `vlm` = model chép từ ảnh, phải soát |
| `title`, `text_raw` | ingest | **Trả lời** + hiển thị |
| `page_png`, `crop_path`, `bbox` | ingest | Hiển thị, khoanh đúng vùng đang nói tới |
| `hash` | ingest | Incremental build — slide không đổi thì không gọi lại LLM |
| `item_id` | ingest | **Phải ổn định giữa các lần build** — `grounding` trỏ vào đây |
| `items[].source` | ingest | `vector` = vẽ bằng shape · `bitmap` = ảnh nhúng. Để biết figure detection có chạy không |
| `content.message` | LLM | **Tìm slide** — trường quan trọng nhất |
| `content.description` | LLM | **Trả lời** câu "trên hình có gì" |
| `content.entities` / `keywords` | LLM | **Tìm** bằng từ khoá — bắt thuật ngữ tiếng Anh mà vector hay trượt |
| `items[].text` | ingest | **Trả lời** + khoanh vùng |
| `items[].image_content` | LLM | **Tìm + trả lời** — nối lại thành vector ảnh của slide. Deck ít chữ nhiều hình thì đây là nội dung chính |
| `items[].role` | LLM | Lọc — `decorative` thì **không embed**, không đưa vào câu trả lời |
| `items[].image_type` | LLM | `chart` → nhắc người soát lại số · `logo`/`icon` → bỏ qua |
| `scenario.steps[]` | LLM | Lời robot đọc, chia theo bước animation |
| `scenario.grounding` | LLM | Truy nguyên — câu này dựa vào mảnh nào |

> **`items` là các mảnh nhìn thấy được trên slide** — PDF vốn đã lưu như vậy: chữ theo block
> có toạ độ riêng, hình thành object riêng. Deck ít chữ nhiều hình thì **2–6 item/slide**.
> **Luật gộp:** block cùng cỡ chữ + sát nhau theo chiều dọc thì gộp làm một item, không thì
> một khổ bullet 5 dòng thành 5 mảnh vụn.

### Truy xuất — một mức, nhiều vector

**Mỗi slide là một điểm trong index.** Không tách index riêng cho từng mảnh: `image_content`
đã mô tả sẵn sơ đồ và biểu đồ rồi, gộp vào slide là đủ để tìm.

Và vì **kho tri thức chính là deck**, đây cũng là index duy nhất — không có index thứ hai nào
để tra cứu.

| Vector | Dựng từ | Bắt loại câu hỏi |
|---|---|---|
| `v_message` | `content.message` | *"phần nói về kiến trúc"* — hỏi theo ý |
| `v_image` | nối `image_content` của item không phải `decorative` | *"cái sơ đồ hai nhánh"*, *"biểu đồ chi phí"* |
| `v_title` | `title` | câu hỏi trích đúng tên slide |
| sparse | `entities` + `keywords` | thuật ngữ tiếng Anh mà vector hay trượt |

**Không gộp bốn thứ thành một vector.** Slide 5 dòng chữ + 1 hình mà gộp thì phần chữ át hết
phần hình, hỏi về hình sẽ không ra. Qdrant cho **nhiều named vector trên cùng một điểm** — vẫn
đúng một collection `slides__{deck}__{model_id}`, vẫn đúng một lần truy xuất.

Truy xuất: query cả 4 vector → hợp kết quả → rerank → top-3.

**Sparse dùng của `bge-m3`, không dựng BM25 riêng.** BM25 với tokenizer tiếng Anh trên tiếng
Việt gần như vô dụng — *"kiến trúc"* thành 2 token rời. `bge-m3` sinh dense và sparse trong
cùng một forward, sparse đó đã train đa ngữ, Qdrant nhận native. Bớt hẳn một thành phần.

> **Tìm ra slide rồi thì không cần truy xuất lần hai.** Đưa **cả slide** vào prompt —
> `items[]` một slide chỉ 2–6 mảnh, khoảng 200 token. Có `bbox` trong đó nên model tự biết
> mảnh nào bên trái, mảnh nào bên phải.

Hai lưu ý khi build index:

- **JSONL không chứa vector.** Vector nằm ở Qdrant, JSONL là nguồn sự thật để dựng lại index
  bất cứ lúc nào. Đổi embedding model thì build lại index, không đụng JSONL.
- **Payload Qdrant chỉ giữ id + trường lọc** (`slide_id`, `display_no`). Nhồi cả `text_raw`
  vào payload là phình index và có hai bản text lệch nhau.

> **Test rẻ, đáng giá:** build xong, lấy chính `content.message` của slide 7 đi query → top-1
> phải ra slide 7. Không ra = hai slide index không phân biệt nổi → online sẽ nhảy nhầm.
> Bắt ở đây mất 25 giây, bắt lúc demo thì muộn.

### Rủi ro xử lý dữ liệu — bốn cái phải canh

**1. Sơ đồ PowerPoint xuất PDF là vector, KHÔNG phải ảnh.** Rủi ro lớn nhất và im lặng hoàn
toàn: `get_images()` trả về mảng rỗng, pipeline chạy trơn tru, chỉ là `items[]` không có
figure nào → `image_content` rỗng → `v_image` rỗng → deck ít chữ nhiều hình thì tìm gì cũng
trượt. Phải dò vùng hình bằng `get_drawings()`: bỏ path mỏng chạy dài (đường kẻ) và path phủ
cả trang (nền), cụm các rect còn lại, cụm nào > ~2% diện tích trang thì là một figure.
**Text block nằm lọt trong cụm là nhãn của sơ đồ** — gắn vào figure, đừng tách thành text
item riêng.

**2. Trang scan.** `text_raw` lúc đó là máy đoán, không còn gì "đúng sẵn" để bảo vệ. Không
dựng OCR engine riêng — đã gửi ảnh cho VLM rồi thì cho nó chép chữ luôn trong cùng lần gọi,
ghi `text_source: "vlm"`, và flag mọi con số. Phát hiện theo **từng trang**, không theo cả
file: `chars_per_page < 10` hoặc `weird_char_ratio > 2%`.

**3. NFC/NFD.** `ế` lưu được hai cách — một code point, hoặc `e` cộng dấu tổ hợp. Nhìn trên
màn hình giống hệt nhau nhưng `==` trả `False`: sparse không khớp, dedup không bắt, filter
trượt. Debug cực khổ vì mắt không thấy. `unicodedata.normalize("NFC", ...)` ở **mọi điểm
vào**, kể cả query lúc runtime.

**4. Title không còn placeholder role.** PDF không nói đâu là title. Luật: ứng viên là text
block trong 1/3 trên, cỡ chữ ≥ 1.2× median của trang; block to nhất nằm giữa trang và là
block duy nhất → slide section header, lấy chính nó. Không ứng viên nào thoả → **`title:
null`, đừng bịa** — `content.message` gánh phần việc đó rồi.

### Ingest report — chạy mỗi lần build

Không có bảng này thì mọi lỗi trên đều **im lặng**: pipeline vẫn chạy xong, artifact vẫn sinh
ra, chỉ là sai.

| Chỉ số | Báo động khi |
|---|---|
| `pages_per_group` trung bình | = 1.0 → gom nhóm animation không chạy · có nhóm > 8 → gom nuốt cả slide sau |
| `slides_without_figure` | > 40% → figure detection chết (rủi ro 1) |
| `text_source == "vlm"` | > 20% số trang → deck chủ yếu là scan, hạ tin cậy cả bộ |
| `weird_char_ratio` | > 2% → font encoding vỡ |
| `title_null_rate` | > 30% → luật đoán title sai |
| `self_retrieval_top1` | < 90% → index không phân biệt nổi các slide |

Slide nào vượt ngưỡng thì in kèm thumbnail — người liếc mắt là thấy.

---

## II. Online — trong lúc thuyết trình

Robot đọc `scenario` theo từng bước. Khán giả **đứng dậy hỏi bằng lời** — mic thu, ASR chuyển
thành text, rồi mới vào luồng dưới.

```
[đang đọc scenario bước 2/3 của slide s12]
   │
khán giả đứng dậy hỏi → VAD + ASR → text
   │   CHỤP STATE NGAY: at_slide = s12
   ▼
fast-path regex ("next", "về slide 5") ──khớp──► gọi thẳng tool điều hướng   [~5ms]
   │ trượt
   ▼
mở rộng query (deterministic, ~5ms): + entities + image_content slide hiện tại
   │
   ▼
1 lần gọi LLM: định tuyến + viết lại câu hỏi + chọn tool
   ├─ hỏi về slide ĐANG CHIẾU → trả lời thẳng, KHÔNG gọi tool
   ├─ hỏi / xem slide khác    → find_slide  (+ goto_slide nếu cần chiếu lên)
   ├─ vượt quá deck           → nói không biết, KHÔNG bịa
   └─ không chắc              → hỏi lại kèm thumbnail, KHÔNG nhảy
   │
   ▼
sinh câu trả lời → cắt theo dấu chấm → TTS từng câu       [< 2.5s tới tiếng đầu]
   │
   ▼
resume(): "quay lại chỗ nãy nhé" → về bước đang dở
```

`at_slide` **chụp lúc nhận câu, không phải lúc xử lý** — xử lý xong robot đã sang trang khác,
lấy sau là giải "phần này" lệch một slide mà không ai thấy.

### Truy xuất — một phép tìm, trên cả chữ lẫn ảnh

Đúng một collection `slides__{deck}__{model}`, query chạy trên cả bốn vector của slide:
`v_message` · `v_image` (nối `image_content`) · `v_title` · sparse `entities`/`keywords`
→ hợp kết quả → rerank → top-3.

`find_slide` trả về **cả record của slide**: `title`, `content`, `items[]` kèm `bbox`. Trả lời
lấy thẳng từ đó, **không truy xuất lần hai** — một slide chỉ 2–6 mảnh, ~200 token, nhét vào
prompt là xong. Model nhìn `bbox` là biết mảnh nào bên trái, mảnh nào bên phải.

Vì KB chính là deck nên **một tool này phục vụ cả hai việc**: tìm slide để chiếu lên, và tìm
slide để lấy nội dung trả lời. Khác nhau ở chỗ có gọi `goto_slide` sau đó hay không.

### List tool

| Tool | Mục đích — dùng khi nào | Bên trong làm gì | Trả về |
|---|---|---|---|
| `find_slide(q)` | Khán giả nhắc tới một slide khác mà không nói số: *"phần kiến trúc lúc nãy"*. Cũng là đường lấy nội dung để trả lời | hybrid search `slides__` trên 4 vector → top-5 → rerank → confidence gate. **Không tự nhảy** | `slide_id` + `score` + `margin` + **cả record slide** (`items[]`, `bbox`), hoặc `ask` kèm thumbnail |
| `goto_slide(id)` | Chiếu một slide lên màn hình. **Mọi thay đổi trang đều phải đi qua đây** | nhảy tới `display_page` của slide → gửi lệnh renderer → **đợi ack ≤ 500ms** → commit state. Nhảy ra khỏi mạch thì push `return_stack` | ok / timeout |
| `next_slide()` / `prev_slide()` | Điều hướng tương đối: *"next"*, *"lùi một trang"*. Fast-path gọi thẳng, không qua LLM | đi **một trang PDF** = một bước animation | ok / timeout |
| `resume()` | Trả lời xong câu hỏi về slide cũ → về đúng bước đang thuyết trình dở | pop `return_stack`. **Nói ra miệng trước khi nhảy** | ok |

**Không có tool cho câu hỏi về slide đang chiếu** — slide đó đã nằm sẵn trong prompt nên model
trả lời thẳng. Đây là loại câu hỏi phổ biến nhất, và nó không tốn thêm lượt nào.

Hai luật gắn với tool:

- **Không nói trước khi có ack của renderer.** Robot bảo "đây là trang kiến trúc" trong khi
  màn hình còn trang cũ là lỗi chói nhất.
- **Hỏi vượt quá deck thì nói không biết.** v1 không có nguồn ngoài, nên không có gì để tra
  thêm. Cào đại một slide gần gần rồi trả lời là cách nhanh nhất để mất niềm tin của khán giả.

### Confidence gate

`margin = rerank(top1) − rerank(top2)` dưới ngưỡng → **không nhảy**, hỏi lại kèm thumbnail.
Điểm lấy từ **reranker** — số thật, calibrate được — không dùng điểm LLM tự khai. Ngưỡng
**fit trên bộ eval 50 câu có nhãn**, để trong config, không hardcode.

### Ba luật giữ được 2.5 giây

1. **Đúng một lần gọi LLM** cho định tuyến + viết lại + chọn tool. Tách router riêng là cộng
   thẳng 300–400ms mà không được gì.
2. **TTS phát theo từng câu**, cắt từ token stream. Đợi sinh xong mới đọc là +2–3 giây.
3. **Hỏi về slide đang chiếu thì trả lời thẳng**, không gọi tool — slide đó đã nằm sẵn trong
   prompt. Tiết kiệm 400–700ms cho đúng loại câu hỏi phổ biến nhất.

### Edge case + khi nào được ngắt

| Tình huống | Xử lý |
|---|---|
| 2 slide điểm sát nhau | Không nhảy — hỏi lại kèm thumbnail |
| Hỏi "phần này / slide này" | Giải tiền ngữ từ `at_slide`, không đi tìm |
| Khán giả nói *"slide 7"* | Map qua `display_no`, **không phải** `page_no` — 45 trang PDF mà khán giả đếm theo 20 slide |
| Hỏi về slide chưa chiếu | Trả lời ngắn, không nhảy tới |
| Câu hỏi trải 2 slide | Trả lời bằng lời, không nhảy |
| Hỏi ngoài phạm vi deck | Nói không biết, tuyệt đối không nhảy |
| Đang đọc scenario, hỏi **điều hướng** | Ngắt ở **ranh giới câu**, fade 80ms |
| Đang đọc scenario, hỏi **nội dung** | Đợi hết bước rồi trả lời |
| Đang chuyển trang | Xếp hàng, đợi ack xong đã |

Kiểm tra có người hỏi **sau mỗi câu** — không liên tục, cũng không đợi hết slide.
Orchestrator là **nguồn chân lý duy nhất** về đang ở trang nào; renderer chỉ nhận lệnh và ack.

---

## Quyết định đã chốt

| | Chốt | Kéo theo |
|---|---|---|
| Phạm vi v1 | **KB chính là deck** | Bỏ nhánh tài liệu nguồn, bỏ alignment, bỏ `qa_cache`. Đổi lại: không trả lời được "tại sao" sâu hơn slide |
| Định dạng deck | **PDF, mỗi bước animation một trang** | Trang PDF = bước chiếu, nhóm trang = slide ngữ nghĩa. `next_slide` đi từng bước, không cần `next_animation` |
| Scenario | **1 lần gọi LLM mỗi slide** (không phải mỗi trang) | Sinh cùng lúc `image_content` + `scenario` chia theo bước. ~20 call cho cả deck |
| Trang scan | **VLM chép chữ luôn** | Không dựng OCR engine riêng. `text_source` ghi lại, số liệu phải soát |
| Kênh hỏi | **Khán giả hỏi bằng lời** | Cần VAD + ASR + AEC; ngân sách 2.5s tính từ lúc dứt câu, ASR đã ăn ~300ms |
| Truy xuất | **Một mức, một index** | Mỗi slide một điểm, 4 vector. Sparse dùng của `bge-m3`, không dựng BM25 riêng |

Đánh đổi của PDF: số trong biểu đồ và bảng là VLM đọc từ pixel, không trích chính xác được
như pptx. Slide nào có số quan trọng thì cho người soát lại.

---

## Để dành cho v2

Bỏ khỏi v1 để kịp thời gian, nhưng schema đã chừa chỗ nên thêm vào không phải viết lại:

- **Tài liệu nguồn ngoài deck** → `kb_chunks.jsonl` + `related_chunks[]` trên mỗi slide.
  Đây là thứ mở khoá câu hỏi "tại sao".
- **`answer_depth`** — slide nào không có nguồn thì chỉ mô tả, cấm giải thích sâu. Chỉ có
  nghĩa khi đã có nguồn ngoài.
- **`qa_cache`** — sau khi có câu hỏi thật từ buổi chạy thử. Tự nghĩ câu hỏi để cache thì tỉ
  lệ trúng gần 0.
- **Nhiều deck một phiên** — cần tách `deck_id` ra khỏi tên collection.
