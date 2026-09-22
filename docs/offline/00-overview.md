# Nhánh offline — tổng quan

## 1. Vì sao có nhánh offline

> Slide là bản nén mất mát của kiến thức. Người thuyết trình là nơi chứa phần bị mất.
> **Toàn bộ nhánh offline tồn tại để tái tạo phần đó.**

Deck mục tiêu: ~20 trang, ít chữ nhiều hình, trung bình **dưới 20 từ mỗi trang**.
Con số này không phải chi tiết phụ — nó là lý do RAG text thuần chết ở đây và là lý do
phải có tầng VLM. Nếu deck 80 từ/trang thì phần lớn thiết kế dưới đây là thừa.

Nhánh offline trả trước toàn bộ chi phí suy luận để runtime chỉ còn việc **tra cứu**.

---

## 2. Bốn nguyên tắc bất di bất dịch

### NT1 — Offline không có ràng buộc thời gian, online thì có

Mọi thứ tính trước được phải đẩy vào offline. 6 phút build một deck là rẻ; 300ms thêm
ở runtime là đắt. Runtime budget: **< 2.5s tới byte audio đầu tiên**.

Hệ quả: gặp lựa chọn "làm kỹ, chậm" vs "làm nhanh, ẩu" ở offline → luôn chọn kỹ.
2 pass VLM, LLM verify từng cặp alignment, enrich từng chunk — đều đáng.

### NT2 — Dữ liệu chính xác KHÔNG BAO GIỜ để model sinh lại

`title`, `chart_data`, `tables`, `build_steps` đã có bản **đúng 100%** từ parsing pptx.
Đưa cho LLM là tự tạo cơ hội bịa lại cái đang đúng.

Hệ quả cứng: mọi artifact phải khai `provenance`, mỗi field thuộc đúng một trong hai nhóm:

```json
"provenance": {
  "deterministic": ["title", "chart_data", "tables", "build_steps", "word_count"],
  "vlm":           ["message", "description", "relations", "entities", "..."]
}
```

Không có field nào ở giữa. Nếu không biết xếp vào đâu → thiết kế sai, tách field ra.

### NT3 — Ảo giác offline nguy hiểm gấp nhiều lần online

Bịa ở runtime → sai một lần, trước một câu hỏi.
Bịa trong `Scenario` → robot nói sai ở **mọi buổi thuyết trình**, và không ai kiểm lại.

Hệ quả: mọi câu **nội dung** phải có `grounding`. `grounding: null` là **cờ đỏ**, bắt người
duyệt ở S7, không được im lặng cho qua. Sai ở S1 lan xuống S3, thành kịch bản sai ở S4,
rồi thành lời nói trước khán giả — sai ở đây là **sai có hệ số nhân**.

### NT4 — Tự nhiên là YÊU CẦU, không phải điểm cộng

Robot nghe như đọc bản tin thì hệ thống **thất bại**, dù alignment coverage 95% và
ungrounded rate 2%. Không ai ngồi nghe hết 30 phút giọng máy đọc.

**NT4 va thẳng vào NT3.** Nói tự nhiên nghĩa là có "thì", "nhé", "đúng không ạ", câu hỏi
tu từ, câu chuyển mạch. **Không câu nào trong đó có nguồn.** Theo NT3 nguyên bản, mỗi câu
như vậy là một cờ đỏ → hoặc ungrounded rate nổ tung, hoặc robot vẫn cứng.

Gỡ bằng cách tách hai loại câu, **không nới NT3**:

```
kind: "content"    grounding ∈ {slide_repr, kb_chunk, speaker_notes}
                   null = CỜ ĐỎ                      <- luật cũ giữ nguyên, không nới

kind: "delivery"   grounding ∈ {structure, style}
                   KHÔNG mang thông tin sự thật mới
                   validate BẰNG CODE: không chứa số
                                       không chứa entity chưa xuất hiện
                                       không chứa mệnh đề khẳng định về sự thật
```

- `ungrounded_rate` từ nay tính **trên câu `content`**
- Câu `delivery`: **10–25% tổng âm tiết**. 25% là trần chống lan man;
  **10% là SÀN CỨNG** — pass 2 của S4 không được cắt xuống dưới (xem [S4](./s4-scenario.md))

Nới NT3 thay vì tách câu là mở cửa cho ảo giác đi vào đúng chỗ nguy hiểm nhất. Đừng làm.

**NT1 và NT4 không mâu thuẫn:** mọi thứ làm cho tự nhiên (prosody, nhịp, từ điển phát âm)
đều tính trước được ở offline. Không cái nào tốn thêm một millisecond nào ở runtime.

---

## 3. Kiến trúc: hai nhánh, hội tụ tại S3

```
NHÁNH NGUỒN                         NHÁNH DECK
source/*.pdf                        deck.pptx
    |                                   |
 S5 KB Construction                  S0 Ingest ──> render PNG ──> thumbs
    |  chunk · enrich · index           |
    |                                S1 Slide Understanding
    v                                   |   message PHẢI TỰ ĐỨNG ĐƯỢC
 [kb_chunks] Qdrant · SHARED            ├──> pronunciation.json
    |                                   v
    |                                S2 Deck Structure
    |                                   |   concept_map[].gloss
    |                   +---------------+---------------+
    |                   v                               v
    |          S6a BUILD SLIDEINDEX               S3 Alignment
    |            multi-field embed                      |
    |            slide · section · concept              v
    |                   |                            S4 Scenario
    |          [slide_index_{deck}] Qdrant              |  content / delivery
    |                   |                               |  prosody · nhịp
    |          self-retrieval check                     v
    |                   |                            S6b TTS + qa_cache
    +-------------------+---------------+---------------+
                                        v
                                 S7 HITL  (đọc + NGHE)
                                        |
                                 DeckBundle -> Runtime
```

**Thứ tự chạy thật** (số stage là lớp khái niệm, KHÔNG phải thứ tự thực thi):

```
S5 || S0 -> S1 -> S2 -+-> S6a -> self-retrieval check --+
                      +-> S3 -> S4 -> S6b --------------+-> S7
```

- **S5 không phụ thuộc deck** → chạy song song từ t=0. Deck thứ hai dùng chung nguồn thì skip hẳn.
- **S3 là điểm hội tụ duy nhất** của hai nhánh.
- **S2 không đi qua S3**, nhảy thẳng xuống S4. S2 chỉ cần biết deck nói gì, không cần biết nguồn.
- **S6 tách đôi** vì hai nửa có phụ thuộc khác nhau: S6a chỉ cần S1+S2 → **chạy song song
  với S3**; S6b cần S4.

### 3.1 Offline giờ là một hệ thống dựng INDEX

Thay đổi cấu trúc lớn nhất so với bản trước: offline không chỉ sinh nội dung + audio nữa,
nó sinh **hai index truy xuất**, và runtime **truy vấn** chúng thay vì đọc file.

| Index                                  | Phạm vi           | Nội dung                           | Dựng ở      |
| -------------------------------------- | ------------------ | ----------------------------------- | ------------- |
| `kb_chunks__{model_id}`              | **SHARED**   | chunk từ tài liệu nguồn         | S5            |
| `slide_index__{deck_id}__{model_id}` | **PER-DECK** | slide (5 field) + section + concept | **S6a** |

Cùng `bge-m3`, cùng Qdrant, cùng `bge-reranker-v2-m3`. **Một hạ tầng, hai index** —
không phát sinh phụ thuộc mới.

`model_id` nằm trong tên collection là **bắt buộc**: đổi embedding model mà quên rebuild
thì runtime truy vấn index cũ bằng vector mới và trả về rác **mà không báo lỗi**.

### 3.2 Dòng thời gian thật (deck 20 trang, build lần đầu)

```
t=0                                                            t ~ 6 phút
│
├── S5 KB ════════════════════════╗   chạy SONG SONG, không cần deck
│   (~2 phút, 1 lần / corpus)     ║   deck thứ 2 dùng chung nguồn --> SKIP
│                                 ║
├── S0 ═══╗                       ║
│  (~30s) ╚═ S1 ═══════╗          ║
│            (~90s)    ╚═ S2 ═╗   ║
│                      (~15s) ║   ║
│                             ╠═══╡ S6a ═╗                  <- song song với S3
│                             ║  (~25s)  ╚═ self-retr (~5s) ═╗
│                             ╚═══╩═ S3 ═══╗                 ║
│                                  (~105s) ╚═ S4 ═══╗        ║
│                                            (~2ph) ╚═ S6b ══╗║
│                                                    (~90s)  ╚╩═ S7
│                                                             (người, 10–20ph)
```

Ba thứ đọc được từ hình này: **S5 không nằm trên đường găng**; **S3 là nút thắt**
(không có nó thì S4 không chạy được); và **S6a nằm gọn trong bóng của S3** nên việc dựng
SlideIndex **không tốn thêm một giây nào**.

Hệ quả thứ ba mới là cái đáng giá: `self-retrieval check` xong **trước khi S4 chạy**, nên
nó bắt được slide có biểu diễn lẫn nhau **trước khi tiêu tiền viết kịch bản** cho chúng.

### 3.3 Bên trong từng stage

#### S0 · Ingest — `deck.pptx` → `RawSlide[]`

```
VÀO  deck.pptx
  │
  ├─> [parse XML]  duyệt group ĐỆ QUY, giữ group_path
  │                sort reading order theo bbox    <- KHÔNG theo shape order
  │                lọc hidden slide (show="0")     <- không lọc là lệch số trang
  │                chart series lấy từ XML         <- KHÔNG để VLM đọc pixel
  │                tables: giữ cấu trúc ô + merge
  │                placeholder type + layout_name + section_native
  │                bbox EMU ──> [0,1]
  │
  ├─> [LibreOffice --headless] ─> PDF ─> [PyMuPDF] ─> render/s{n}.png
  │                                                        │
  │                                          [Pillow] cắt ảnh theo bbox
  │                                          <- KHÔNG lấy file ppt/media/
  │
  └─> [hash]  SHA(XML normalized + bytes ảnh)     <- cho incremental build
                    │
                    v
              RawSlide[]  ─> [quality gate]
                              avg_text_per_slide < 20 từ ─> xác nhận "ít chữ nhiều hình"
                              charts_from_xml < 100%     ─> flag
                              notes_word_count_avg = 0   ─> flag thông tin
RA   RawSlide[]  ──> S1
```

#### S1 · Slide Understanding — `RawSlide[i]` → `SlideRepr[i]`

```
VÀO  RawSlide[i] + tiêu đề deck + title trang trước/sau (CHỈ title)
  │
  ├─> [passthrough]  title · chart_data · tables · build_steps
  │        │                                      <- VLM KHÔNG được đụng
  │        │
  ├─> [dựng prompt]  png_render + text_runs đã sort + shapes + group_path
  │        │         + chart.series & table.cells LÀM HINT + ngữ cảnh deck
  │        │
  │        ├─> [VLM pass A  t=0.2] ─┐
  │        └─> [VLM pass B  t=0.7] ─┤
  │                                 v
  │                        [so ĐÚNG 3 thứ]
  │                          message   cosine  < 0.85 ─┐
  │                          entities  Jaccard < 0.6  ─┼─> flags ──> S7
  │                          relations tập triple khác ┘
  │                                 │
  │                          lấy bản t=0.2 nếu ổn định
  │                                 v
  ├─ merge ────────────────> SlideRepr[i] + provenance{deterministic | vlm}
  │        │
  │        └─> [check TỰ ĐỨNG ĐƯỢC]   message / description
  │              danh sách từ cấm: nó, cái này, như trên, vừa nêu, trang trước
  │              phải chứa >= 1 entity của chính trang đó
  │              <- vì S6a sẽ EMBED chúng MỘT MÌNH, không có trang kề bên cạnh
  │
  └─> [bổ sung pronunciation.json]  entities mới (RAG, BM25, retriever...)
          viết tắt <= 4 ký tự toàn hoa ─> mặc định đọc rời từng chữ, FLAG cho S7
          <- S4 cần bảng này để đếm âm tiết cho đúng
RA   SlideRepr[i]  ──> S2, S3, S4, S6a
```

#### S2 · Deck Structure — 20 dòng nén → `DeckStructure`

```
VÀO  SlideRepr[] NÉN còn 1 dòng/trang (~1.5k token)
       slide_id · title · slide_type · message · entities
     + section_native (nếu pptx có)  + time_budget_min (người nhập)
  │
  └─> [1x LLM TOÀN CỤC]   <- KHÔNG so từng cặp trang
            │              <- KHÔNG viết một câu tiếng Việt nào
            ├─> sections{id, title, slides, summary, role}
            │                                  ^ summary bị EMBED ─> tự đứng được
            ├─> concept_map{concept: introduced_at, used_at[], depth, GLOSS}   *
            │                                                        ^ MỚI
            │     gloss = MỘT CÂU tự đứng được, S6a embed thành v_concept
            │     <- thay cho việc dump cả bảng concept_map vào prompt runtime
            ├─> dependencies[{slide, requires[], via}]
            ├─> arc{hook, problem, solution, evidence, closing}
            └─> time_budget{total_min, allocation, rationale}
                        │
                        v
            [validate BẰNG CODE — 5 luật + 1]
              1 sections phủ kín + không chồng ─┐
              2 sections liên tục               ├─ vi phạm ─> LỖI LLM ─> retry
              4 DAG, không chu trình           ─┘
              3 dependencies phải LÙI          ─┐
              5 introduced_at <= min(used_at)  ─┴─ vi phạm ─> LỖI BỘ SLIDE ─> S7
              6 gloss + summary qua check tự đứng được    ─> retry
RA   DeckStructure  ──> S4, S6a, runtime
```

#### S5 · KB Construction — `source/*.pdf` → `KBChunk[]` + `KBIndex`

```
VÀO  source/*.pdf                  <- chạy SONG SONG từ t=0, không cần deck
  │
  ├─> [S5.1 parse]  PyMuPDF + unstructured/docling
  │       cây heading · đoạn + số trang · bảng · hình+caption · công thức
  │       lọc rác: header/footer lặp, số trang, mục lục, references
  │
  ├─> [S5.2 chunk]  STRUCTURE-AWARE theo cây heading, 300–500 tok, overlap 50
  │       mục <= 500 tok ─> 1 chunk
  │       mục >  500 tok ─> cắt theo ranh giới ĐOẠN VĂN
  │       bảng nhỏ       ─> 1 chunk markdown
  │       bảng lớn       ─> mỗi hàng 1 chunk, LẶP HEADER mỗi hàng
  │       hình           ─> [VLM] caption ─> chunk content_type=figure
  │
  ├─> [S5.3 enrich]  * bước quan trọng nhất
  │       [LLM batch 10] prepend câu bối cảnh ─> text_enriched
  │       + [S5.4] phân loại content_type          (CÙNG một lượt gọi)
  │
  └─> [S5.5 embed]  bge-m3 ─> dense 1024 + sparse
          EMBED text_enriched          <- KHÔNG phải text_raw
                │
                v
          Qdrant + BM25   (hybrid BẮT BUỘC: tiếng Việt lẫn thuật ngữ Anh)
RA   KBChunk[] + KBIndex  ──> S3
     (deck_ids, related_slides, align_role còn RỖNG — S3 điền)
```

#### S3 · Alignment — `SlideRepr[]` + `KBIndex` → `AlignmentMap[]`

```
VÀO  SlideRepr[] + KBIndex                    <- ĐIỂM HỘI TỤ hai nhánh
  │
  ├─ skip slide_type ∈ {title, agenda, section_header, thank_you, qa}
  │
  ├─> [S3.1 retrieve]  4 truy vấn / slide
  │       q1 title    ─┐
  │       q2 message   ├─ top-10 mỗi q ─> hợp + khử trùng ─> 20–25 ứng viên
  │       q3 entities  │  (sparse bắt thuật ngữ, viết tắt)
  │       q4 relations ┘
  │
  ├─> [S3.2 verify]  LLM, batch 5 cặp      <- RETRIEVAL MỘT MÌNH KHÔNG ĐỦ
  │       "chunk này THỰC SỰ chống lưng slide, hay chỉ trùng từ khoá?"
  │       ─> relation: source_of | elaborates | evidence_for | contrast | none
  │       ─> conf 0..1
  │       ─> TRÍCH tối đa 2 câu bằng chứng
  │              │
  │              └─ evidence không phải substring của text_raw ─> hạ conf <= 0.5
  │
  └─> [S3.3 backfill HAI CHIỀU]
        xuôi:   slide 7 ─> links[]              ─> AlignmentMap[7]
        ngược:  c118 ─> related_slides: [7]     ─> ghi ngược vào KBChunk
                c203 ─> related_slides: []
                        align_role: "background"
                        ^ GIỮ LẠI — đây là phần kiến thức slide đã lược bỏ
RA   AlignmentMap[] + coverage report  ──> S4, S7
```

#### S4 · Scenario — tất cả trên → `Scenario[]`

```
VÀO  SlideRepr[] + DeckStructure + AlignmentMap[] + KBChunk[]
     + pronunciation.json  (+ speaker_notes)
  │
  ├─ notes_word_count_avg > 30 ? ─> chế độ REFINE  :  ─> chế độ GENERATE
  │
  ├─> [PASS 1 — viết]  song song 5 luồng
  │       chia theo build_step        <- không tiết lộ phần chưa hiện lên
  │       đổi giọng theo arc[slide]
  │       concept_map: khái niệm đã introduced_at trước ─> KHÔNG định nghĩa lại
  │       │
  │       ├─ kind="content"   grounding{slide_repr|kb_chunk|speaker_notes}
  │       │                   null ─> CỜ ĐỎ
  │       └─ kind="delivery"  grounding{structure|style}      <- NT4
  │                           đặt ở RANH GIỚI cấu trúc (đầu build_step,
  │                           sau một con số, trước một tương phản)
  │                           lấy vị trí từ arc + dependencies
  │                           <- rải ngẫu nhiên TỆ HƠN không có
  │       │
  │       └─ nhịp: trộn câu 6–12 / 15–20 / 25–30 âm tiết
  │          văn NÓI: cấm "việc…", "sự…", "được thực hiện bởi", danh từ hoá
  │          prosody mỗi câu: emphasis[] · pause_before_ms · speed
  │
  ├─> [PASS 2 — cân giờ]  theo time_budget.allocation của S2
  │       actual > budget*1.15 ─> NÉN theo THỨ TỰ:
  │            (1) trùng lặp ở câu content   (2) câu content phụ
  │            (3) câu delivery — CUỐI CÙNG, và KHÔNG xuống dưới SÀN 10%
  │            ^ không có luật thứ tự này thì cân giờ vài vòng là kịch bản khô lại
  │       actual < budget*0.85 ─> GIÃN bằng nội dung TỪ KB
  │                               <- cấm giãn bằng câu content grounding=null
  │
  └─> [đếm ÂM TIẾT]  190–210 âm tiết/phút      <- KHÔNG đếm từ
          đếm THEO pronunciation.json           <- "BM25" đọc sao thì đếm vậy
          ghi hash bảng vào Scenario            <- S6b sẽ so hash trước khi synth
          max 30 âm tiết / câu                  <- ranh giới ngắt của R7 là ranh giới câu
          target_sec = syllables / (200/60)
RA   Scenario[]   slide ─> steps[] ─> sentences[]{kind, prosody, tts_hash}  ──> S6b
```

#### S6a · Build SlideIndex — `SlideRepr[]` + `DeckStructure` → Qdrant

```
VÀO  SlideRepr[] + DeckStructure        <- KHÔNG cần S3, KHÔNG cần S4
  │                                        => chạy SONG SONG với S3
  │
  ├─> [multi-field embed]   bge-m3, KHÔNG gộp một vector
  │       mỗi slide ─> v_message     <- quan trọng nhất cho điều hướng
  │                    v_title
  │                    v_desc         (description)
  │                    v_relations    (triple serialize)
  │                    sparse         (entities + keywords, BM25)
  │       mỗi section ─> v_section    (summary)
  │       mỗi concept ─> v_concept    (gloss)
  │
  │       <- vì sao multi-field: "chỗ nói về việc không cần train lại" khớp message;
  │          "cái sơ đồ ba khối" khớp description; "BM25" khớp sparse.
  │          Gộp một vector làm LOÃNG cả ba.
  │
  ├─> [Qdrant]  slide_index__{deck_id}__{model_id}
  │                                    ^ model_id BẮT BUỘC trong tên
  │
  ├─> [SELF-RETRIEVAL CHECK]   phép thử THẬT, end-to-end
  │       với mỗi slide i:  query = message[i]  ─> top-1 có phải slide i không?
  │           không ─> biểu diễn hai trang LẪN NHAU
  │                 ─> R2 SẼ trượt ở runtime
  │                 ─> flag NGAY, TRƯỚC khi S4 tiêu tiền viết kịch bản
  │       gate: >= 90% slide đạt top-1
  │
  └─> [deck_map.txt]  ~150 token: danh sách section + tên
          <- thay cho slide_index.txt cũ (~1.4k). LLM chỉ cần biết deck có mấy phần
RA   slide_index (Qdrant) + deck_map.txt + audit/self_retrieval.json  ──> S7, runtime
```

#### S6b · Precompute — `Scenario[]` → `precomputed/`

```
VÀO  Scenario[] + pronunciation.json + SlideRepr[] + AlignmentMap[]
  │
  ├─> [so hash pronunciation]   Scenario.pron_hash == hash(pronunciation.json) ?
  │       lệch ─> DỪNG. S4 đếm một đằng, TTS đọc một nẻo, timing sai mà không ai thấy
  │
  ├─> [TTS]  cache key = hash TỪNG CÂU    <- phần tốn tiền nhất, reuse triệt để
  │       tts_hash = SHA(normalize(text) + voice_id + speed + format)
  │       MỘT voice_id duy nhất, dùng chung với streaming TTS ở runtime
  │           <- lệch giọng giữa kịch bản và câu trả lời = artifact CHÓI TAI nhất
  │       áp prosody của S4: emphasis · pause_before_ms · speed
  │       ─> precomputed/tts/{hash}.mp3  + duration_ms THẬT
  │             └─> đối chiếu ước lượng âm tiết của S4; lệch >20% ─> chỉnh hằng số
  │
  ├─> [filler]  bộ câu đệm dùng chung mọi deck ─> data/kb/fillers/
  │
  ├─> [qa_cache]  LLM sinh 3–5 câu hỏi/slide ─> trả lời + TTS sẵn
  │       runtime match cosine > 0.88 mới dùng
  │
  ├─> [thumbs]  s{n}.jpg ~480px   <- cho confidence gate của R2 khi hỏi lại
  │
  └─> [BẢN NGHE THỬ]  3 trang + mọi câu bị flag ─> cho S7 NGHE, không chỉ đọc
RA   precomputed/ + manifest.json  ──> S7 ──> runtime
```

#### S7 · HITL Review — flags → `DeckBundle`

```
VÀO  mọi artifact + flags.json + BẢN NGHE THỬ    <- CHỈ duyệt phần bị flag
  │
  ├─> [VÒNG ĐỌC]  sắp theo độ LAN TOẢ, không theo số trang
  │     1  S4 ungrounded (câu content)  <- CỜ ĐỎ, robot sẽ NÓI RA MIỆNG
  │     2  S1 relations / image_text    <- sai ở đây lan xuống S3, S4
  │     3  S6a self_retrieval_fail      <- R2 sẽ trượt, sửa message hoặc chấp nhận
  │     4  S3 zero_coverage             <- quyết định trang nào được trả lời sâu
  │     5  S2 dependency                <- lỗi bộ slide, thường chỉ ghi nhận
  │     6  S0 / S6b                     <- kỹ thuật
  │           │
  │           ├─ accept / whitelist ─> review.json   (BỀN qua các lần build)
  │           ├─ edit               ─> chạy lại stage dưới của riêng slide đó
  │           └─ rerun + hint       ─> chạy lại stage đó
  │
  ├─> [VÒNG NGHE]  * MỚI — nghe bản nghe thử, chấm MOS 1–5, 3 người
  │       gate: MOS >= 3.8    <- RELEASE gate, KHÔNG phải CI gate
  │       sửa pronunciation.json ─> đếm lại âm tiết + synth lại câu liên quan
  │
  ├─ zero_coverage ─> người chọn 1 trong 3:
  │       ý riêng tác giả ─> answer_depth:"describe_only" ─> R4 sẽ CHẶN
  │       corpus thiếu    ─> bổ sung nguồn, chạy lại S5 + S3
  │       S3 chạy sai     ─> sửa, chạy lại S3
  │
  └─ self_retrieval_fail ─> người chọn 1 trong 2:
          message viết tệ  ─> sửa ─> chạy lại S6a
          hai trang TRÙNG CHỦ ĐỀ THẬT ─> đánh dấu "cặp đã biết, chấp nhận"
                vào review.json ─> LẦN SAU KHÔNG FLAG NỮA
                ^ không có lối này thì nó kêu mãi và người duyệt học cách bỏ qua flag
RA   DeckBundle verified ──> runtime     (còn cờ đỏ ─> KHÔNG đóng gói được)
```

---

## 4. Bảng stage

| Stage                                          | Input                                          | Output                                     | Model                      | Thời gian (deck 20 trang)    |
| ---------------------------------------------- | ---------------------------------------------- | ------------------------------------------ | -------------------------- | ----------------------------- |
| [S0](./s0-ingest.md) Ingest                     | `deck.pptx`                                  | `RawSlide[]`                             | không có, thuần parsing | ~30s (render là phần chậm) |
| [S1](./s1-slide-understanding.md) Understanding | `RawSlide[i]` + title deck + title trang kề | `SlideRepr[i]`                           | VLM, 2 pass                | ~90s (5 luồng)               |
| [S2](./s2-deck-structure.md) Structure          | 20 dòng nén từ S1                           | `DeckStructure`                          | 1x LLM toàn cục          | ~15s                          |
| [S5](./s5-kb-construction.md) KB                | `source/*.pdf`                               | `KBChunk[]` + `KBIndex`                | LLM + VLM + embedding      | ~2 phút / corpus             |
| [S3](./s3-alignment.md) Alignment               | `SlideRepr[]` + `KBIndex`                  | `AlignmentMap[]` + backfill              | retrieval + LLM verify     | ~105s                         |
| [S4](./s4-scenario.md) Scenario                 | tất cả trên +`pronunciation.json`         | `Scenario[]`                             | LLM, 2 pass                | ~2 phút                      |
| [S6a](./s6-precompute.md) Build SlideIndex      | `SlideRepr[]` + `DeckStructure`            | `slide_index` + `deck_map.txt` + audit | embedding                  | ~25s**(song song S3)**        |
| [S6b](./s6-precompute.md) Precompute            | `Scenario[]` + `pronunciation.json`        | `precomputed/`                           | TTS + embedding            | ~90s                          |
| [S7](./s7-hitl-review.md) HITL                  | mọi artifact + flags + bản nghe thử         | `DeckBundle` verified                    | —                         | 10–20 phút người          |

Tổng máy: **~6 phút** cho deck 20 trang, lần build đầu, chưa tính S5 nếu corpus đã có.
S6a không cộng vào tổng vì nó nằm trong bóng của S3.

---

## 5. Hợp đồng dữ liệu

Mọi artifact là **Pydantic v2 model**, ghi ra JSON, đọc lại được. Không dict trần giữa
các stage. Pipeline phải resume được từ bất kỳ stage nào — nghĩa là mỗi stage đọc file
của stage trước chứ không nhận object trong bộ nhớ.

```
data/
├── kb/                                <- SHARED LAYER, dùng chung mọi deck
│   ├── chunks.jsonl                   KBChunk[]
│   ├── index/                         Qdrant: kb_chunks__{model_id} + BM25
│   ├── pronunciation.json             <- MỚI. Thuật ngữ trùng nhau giữa các deck
│   ├── fillers/                       câu đệm prerecorded
│   └── sources/                       PDF gốc
│
├── decks/{deck_id}/
│   ├── deck.pptx
│   ├── raw/          slides.json      RawSlide[]            <- S0
│   │                 render/s{n}.png
│   ├── repr/         slides.json      SlideRepr[]           <- S1
│   ├── structure.json                 DeckStructure         <- S2
│   ├── alignment.json                 AlignmentMap[]        <- S3
│   ├── scenario.json                  Scenario[] + pron_hash <- S4
│   ├── index/                         Qdrant:               <- S6a
│   │                                  slide_index__{deck_id}__{model_id}
│   ├── deck_map.txt                   ~150 token, danh sách section  <- S6a
│   ├── audit/self_retrieval.json      <- S6a
│   ├── precomputed/
│   │   ├── tts/{sentence_hash}.mp3
│   │   ├── qa_cache.jsonl
│   │   ├── thumbs/s{n}.jpg
│   │   ├── listen_sample/             bản nghe thử cho S7   <- S6b
│   │   └── manifest.json
│   ├── flags.json                     gộp flag mọi stage    <- S0–S6
│   └── review.json                    quyết định của người  <- S7
│
└── eval/                              bộ test có nhãn
```

- **KB shared, Alignment per-deck, SlideIndex per-deck.**
- `pronunciation.json` ở **shared layer** vì thuật ngữ trùng nhau giữa các deck —
  "RAG", "BM25", "retriever" chỉ chốt cách đọc một lần.
- Query KB ở runtime **luôn kèm filter** `deck_ids ∋ active_deck_id`.
- Một phiên = một deck active. Không cross-deck navigation trong v1.
- **`model_id` trong tên collection là bắt buộc** — đổi embedding model mà quên rebuild
  thì runtime truy vấn index cũ bằng vector mới và trả rác, **không báo lỗi**.
  `kb_chunks` rebuild một lần, nhưng `slide_index` là per-deck nên phải rebuild **N lần**.

---

## 6. Incremental build

```
hash slide không đổi  -> reuse SlideRepr, Scenario, TTS
hash slide đổi        -> chạy lại S1, S3, S4 cho riêng slide đó
luôn chạy lại S2      -> cấu trúc toàn cục có thể lệch khi một trang đổi
luôn chạy lại S6a     -> SlideIndex phụ thuộc S1 + S2, và rẻ (~25s)
S5 gần như không bao giờ chạy lại (chỉ khi thêm/bớt tài liệu nguồn)
```

**Ca đặc biệt — người duyệt sửa `pronunciation.json` ở S7:**

```
đổi cách đọc "BM25"
  -> đếm LẠI âm tiết (rẻ, không gọi LLM)
  -> synth lại MỌI câu chứa từ đó
  -> lệch timing của section > 15% ? -> chạy lại PASS 2 của S4 (không phải pass 1)
```

Sửa 3/20 trang → **~40s** thay vì ~6 phút.

Hash tính trên **XML shape tree đã normalize + bytes ảnh**, không hash cả file pptx —
đổi metadata (tác giả, thời gian sửa) là hash đổi, build lại vô ích. Chi tiết ở [S0](./s0-ingest.md).

Điểm dễ sai: S4 của slide N phụ thuộc slide N−1 qua câu chuyển, và phụ thuộc các slide
khác qua `concept_map`. Khi slide N−1 đổi, phải chạy lại S4 cho cả N. Quy tắc an toàn:

```
dirty  = {slide có hash đổi}
dirty += {slide kề sau mỗi slide dirty}          (vì câu chuyển)
dirty += {slide có dependencies giao dirty}      (vì tham chiếu ngược)
```

---

## 7. Quy ước chung cho mọi stage

- Python 3.11+, type hints bắt buộc, Pydantic v2 cho schema.
- Mỗi stage là một module độc lập, **chạy riêng được qua CLI**:
  `python -m src.offline.s1_understand --deck-id rag-intro`
- Gọi LLM/VLM: retry exponential backoff, log **full prompt + response** vào `logs/`.
  Không log thì không bao giờ debug được vì sao model bịa.
- Mọi prompt nằm trong `prompts/*.md`. **Không hardcode prompt trong file `.py`.**
- Async cho mọi I/O. S1 và S4 phải song song hoá được (mặc định 5 luồng).
- Không `print()`. Dùng `logging` hoặc `rich`.
- Stage sinh flag thì **append vào `flags.json`**, không tự sửa dữ liệu, không tự quyết.
  Quyết định là việc của người ở S7.

---

## 8. Quality gate ra khỏi nhánh offline

Không đạt thì không deploy. Chạy được trong CI.

### Gate chạy được trong CI

| Chỉ số                                     | Ngưỡng                               | Đo ở        |
| -------------------------------------------- | -------------------------------------- | ------------- |
| Alignment coverage                           | ≥ 80% slide có ≥1 nguồn conf > 0.6 | S3            |
| Ungrounded rate (**câu `content`**) | < 10%                                  | S4            |
| Timing deviation                             | < 15% so với`time_budget`           | S4            |
| **Self-retrieval top-1**               | **≥ 90% slide**                 | **S6a** |
| Flag precision                               | ≥ 60%                                 | S7            |
| P95 latency tới byte audio đầu            | < 2.5s                                 | runtime       |

### Proxy tự nhiên — cũng chạy được trong CI

| Chỉ số                                                                       | Ngưỡng                | Đo ở |
| ------------------------------------------------------------------------------ | ----------------------- | ------ |
| Độ lệch chuẩn số âm tiết / câu                                         | ≥ 6                    | S4     |
| Từ văn viết bị cấm (`việc…`, `sự…`, `được thực hiện bởi`) | = 0                     | S4     |
| Tỉ lệ câu`delivery`                                                       | 10–25% tổng âm tiết | S4     |
| Câu > 30 âm tiết                                                            | < 5%                    | S4     |

### Release gate — KHÔNG chạy trong CI

| Chỉ số                  | Ngưỡng             | Cách đo                           |
| ------------------------- | -------------------- | ----------------------------------- |
| **Naturalness MOS** | **≥ 3.8 / 5** | 3 người NGHE bản nghe thử ở S7 |

MOS cần người ngồi nghe, nên đừng nhét nó vào CI rồi tự lừa mình bằng một con số giả.
Proxy tự động ở trên chạy mỗi lần build; MOS chạy **trước buổi thuyết trình thật**.

Mỗi stage còn có gate riêng, xem cuối từng file.

---

## 9. Bản đồ flag

Mọi flag từ mọi stage đổ về một file, S7 đọc file đó. Chi tiết ở [S7](./s7-hitl-review.md).

| Stage | Flag tiêu biểu                                                                                                                                                                  |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S0    | `chart_not_from_xml`, `parse_quality != full`, `no_speaker_notes`                                                                                                           |
| S1    | `low_confidence_message`, `two_pass_disagree`, `has_image_text`, `empty_relations_on_diagram`, **`message_not_standalone`**, **`unknown_pronunciation`**  |
| S2    | `dependency_forward`, `concept_used_before_introduced`, `no_structure`, **`gloss_not_standalone`**                                                                  |
| S3    | `zero_coverage`, `weak_coverage`, `over_linking`                                                                                                                            |
| S4    | `ungrounded_content_sentence` ← **cờ đỏ**, `timing_overflow`, **`delivery_below_floor`**, **`written_register_hit`**, **`monotone_rhythm`** |
| S6a   | **`self_retrieval_fail`**                                                                                                                                                 |
| S6b   | `duration_mismatch`, **`pronunciation_hash_mismatch`**, **`voice_id_mismatch`**                                                                                 |
