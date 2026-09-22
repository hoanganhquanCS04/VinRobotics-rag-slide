# CLAUDE.md — Context cho AI coding agent

Đọc file này trước khi sinh bất kỳ code nào trong repo.

---

## 1. Hệ thống này là gì

Agent tự thuyết trình một bộ slide và xử lý tương tác thời gian thực từ khán giả:
trả lời câu hỏi và điều hướng slide, trong khi luôn đồng bộ với trạng thái trình chiếu
và có nguồn truy nguyên được.

**Insight cốt lõi chi phối mọi thiết kế:**

> Slide là bản nén mất mát của kiến thức. Người thuyết trình là nơi chứa phần bị mất.
> Toàn bộ nhánh offline tồn tại để tái tạo phần đó.

Đặc điểm deck mục tiêu: ~20 trang, **ít chữ nhiều hình** (trung bình < 20 từ/trang).
Đây không phải chi tiết phụ — nó là lý do RAG text thuần thất bại và phải có tầng VLM.

---

## 2. Bốn nguyên tắc bất di bất dịch

1. **Offline không có ràng buộc thời gian, online thì có.** Mọi thứ tính trước được
   phải đẩy vào offline. Runtime budget: < 2.5s tới byte audio đầu tiên.
2. **Dữ liệu chính xác KHÔNG BAO GIỜ để model sinh lại.** Title, chart series, ô bảng
   đã có bản đúng 100% từ parsing pptx. Đưa cho LLM là tự tạo cơ hội bịa lại cái đang đúng.
   Mọi field phải khai `provenance`: `deterministic` hay `vlm`.
3. **Ảo giác offline nguy hiểm gấp nhiều lần online.** Bịa runtime sai một lần;
   bịa trong `Scenario` thì robot nói sai ở MỌI buổi thuyết trình.
   → Mọi câu **nội dung** phải có `grounding`; `null` = flag đỏ bắt người duyệt.
4. **Tự nhiên là YÊU CẦU, không phải điểm cộng.** Robot nghe như đọc bản tin thì
   hệ thống thất bại dù mọi chỉ số khác đạt.
   → S4 tách hai loại câu, hai chế độ grounding khác nhau:

   ```
   kind: "content"   grounding ∈ {slide_repr, kb_chunk, speaker_notes}   null = CỜ ĐỎ
   kind: "delivery"  grounding ∈ {structure, style}
                     KHÔNG mang thông tin sự thật mới — validate BẰNG CODE
   ```

   `ungrounded_rate` chỉ tính trên câu `content`. Câu `delivery`: **10–25% tổng âm tiết**,
   10% là SÀN CỨNG (pass 2 không được cắt xuống dưới).

**NT1 và NT4 không mâu thuẫn**: mọi thứ làm cho tự nhiên đều tính trước được ở offline.
**NT3 và NT4 thì có** — gỡ bằng đúng cách tách hai loại câu ở trên, KHÔNG nới NT3.

---

## 3. Kiến trúc: hai nhánh, hội tụ tại S3

```
NHÁNH DECK                          NHÁNH NGUỒN
deck.pptx                           source/*.pdf
  S0 Ingest                           S5 KB Construction
  S1 Slide Understanding              (chunk, enrich, index)
  S2 Deck Structure                         │
     ├──────────────┐                       ▼
     │              │                 [kb_chunks] Qdrant · SHARED
     ▼              ▼                       │
 S6a BUILD      S3 Alignment ◄──────────────┘
 SLIDEINDEX         │
     │              ▼
[slide_index_   S4 Scenario
  {deck}]           │
  Qdrant            ▼
     │          S6b TTS + qa_cache
     └──────┬───────┘
            ▼
        S7 HITL Review  (đọc + NGHE)
            │
       DeckBundle → Runtime (R1–R7)
```

**Thứ tự chạy thật** (số stage là lớp khái niệm, KHÔNG phải thứ tự):

```
S5 ∥ S0 → S1 → S2 ─┬─► S6a → self-retrieval check ──┐
                   └─► S3 → S4 → S6b ───────────────┴─► S7
```

- S5 không phụ thuộc deck → chạy song song từ t=0; deck thứ 2 dùng chung nguồn thì skip
- S3 là điểm hội tụ duy nhất
- S2 KHÔNG đi qua S3, nhảy thẳng xuống S4
- **S6 tách đôi**: S6a chỉ cần S1+S2 → chạy **song song với S3** (không tốn thêm giờ);
  S6b cần S4
- **Offline sinh HAI index**: `kb_chunks` (shared) và `slide_index_{deck}` (per-deck).
  Cùng `bge-m3`, cùng Qdrant, cùng reranker — một hạ tầng, hai index.

---

## 4. Stage: input → output

| Stage                  | Input                                          | Output                                                                    | Model                      |
| ---------------------- | ---------------------------------------------- | ------------------------------------------------------------------------- | -------------------------- |
| S0 Ingest              | `deck.pptx`                                  | `RawSlide[]`                                                            | không có, thuần parsing |
| S1 Slide Understanding | `RawSlide[i]` + title deck + title trang kề | `SlideRepr[i]`                                                          | VLM, 2 pass                |
| S2 Deck Structure      | 20 dòng tóm tắt từ S1                      | `sections`, `concept_map`, `dependencies`, `arc`, `time_budget` | 1× LLM toàn cục         |
| S5 KB Construction     | `source/*.pdf`                               | `KBChunks[]` + `KBIndex`                                              | LLM + VLM + embedding      |
| S3 Alignment           | `SlideRepr[]` + `KBIndex`                  | `AlignmentMap` + backfill chunk                                         | retrieval + LLM verify     |
| S4 Scenario            | tất cả trên                                 | `Scenario[]`                                                            | LLM, 2 pass                |
| S6a Build SlideIndex   | `SlideRepr[]` + `DeckStructure`             | `slide_index_{deck}` + `deck_map.txt` + self-retrieval audit        | embedding                  |
| S6b Precompute         | `Scenario[]` + `pronunciation.json`         | `precomputed/`                                                          | TTS + embedding            |
| S7 HITL                | mọi artifact + flags                          | `DeckBundle` verified                                                   | — (người, đọc + nghe)   |

---

## 5. Luật riêng từng stage (agent hay làm sai chỗ này)

### S0

- Sort lại **reading order theo bbox**, KHÔNG dùng thứ tự shape trong XML
- Lọc hidden slide (`show="0"`) — không lọc là lệch số trang
- Chart data lấy từ **XML**, cấm để VLM đọc từ pixel
- Cắt ảnh từ **PNG render theo bbox**, không lấy file trong `ppt/media/` (ảnh đó chưa crop)
- Duyệt group **đệ quy**, giữ `group_path`
- Hash = SHA(XML shape tree normalized + bytes ảnh), KHÔNG hash cả file pptx
- Chuẩn hoá bbox EMU → `[0,1]`

### S1

- S1 **không đọc lại slide**, S0 đã đọc rồi. S1 chỉ sinh **ý nghĩa**.
- Passthrough từ S0, cấm VLM đụng: `title`, `chart_data`, `tables`, `build_steps`
- Bắt buộc bơm ngữ cảnh deck: tiêu đề deck + title trang trước/sau (CHỈ title)
- `message` (trang *muốn nói gì*) ≠ `description` (trang *vẽ gì*) — cả hai đều bắt buộc
- `relations` dạng triple, không phải văn xuôi
- `visual_elements[].role` phải phân loại `primary`/`supporting`/`decorative`
- 2 pass chỉ so 3 thứ: `message` (cosine<0.85), `entities` (Jaccard<0.6), `relations` (khác tập)
- **`message` PHẢI TỰ ĐỨNG ĐƯỢC** — nó bị S6a đem đi embed MỘT MÌNH, lúc đó không có
  trang kề nào bên cạnh để trỏ vào:
  - cấm đại từ trỏ ra ngoài trang (`nó`, `cái này`, `cách làm này`)
  - cấm từ chỉ vị trí (`như trên`, `vừa nêu`, `ở phần trước`, `tiếp theo`)
  - chủ thể phải được **gọi bằng TÊN** ít nhất một lần
  - **Vẫn bơm ngữ cảnh deck vào prompt** — dùng để VLM HIỂU, cấm rò rỉ vào CHỮ
  - `description` và `sections[].summary` cùng luật (đều bị embed)
- Sinh/bổ sung `pronunciation.json` từ `entities` mới (S4 cần để đếm âm tiết)

### S2

- Input phải **nén**: chỉ `slide_id`, `title`, `slide_type`, `message`, `entities` (~1.5k token)
- S2 **KHÔNG viết câu tiếng Việt nào** — chỉ sinh cấu trúc. S4 mới viết văn.
- Validate bằng code, không tin LLM:
  1. `sections` phủ kín + không chồng
  2. `sections` liên tục
  3. `dependencies` phải lùi (`requires < slide`)
  4. DAG, không chu trình
  5. `introduced_at ≤ min(used_at)`
- Vi phạm luật 3/5 thường là lỗi thật của bộ slide → báo S7, KHÔNG tự sửa
- `concept_map[].gloss` — **một câu tự đứng được** cho mỗi khái niệm. S6a embed nó
  thành `v_concept`, thay cho việc dump cả bảng vào prompt runtime.
- `sections[].summary` cũng bị embed → cùng luật tự đứng được như `message`

### S5

- Chunking **structure-aware** theo cây heading, 300–500 token, overlap 50
- KHÔNG fixed-size, không cắt giữa câu/bảng/công thức
- **Contextual enrichment là bước quan trọng nhất**: prepend câu bối cảnh vào mỗi chunk
  TRƯỚC khi embed. Embed `text_enriched`, không phải `text_raw`.
- Bảng lớn: mỗi hàng 1 chunk, **lặp header ở mỗi hàng**
- Hybrid bắt buộc: dense (`bge-m3`) + BM25. Tiếng Việt lẫn thuật ngữ Anh.
- Lọc rác: header/footer lặp, số trang, mục lục, references

### S3

- **S3 tìm chunk là NGUỒN GỐC của slide, không phải chunk GIỐNG slide.**
  Retrieval một mình không đủ — bắt buộc có bước LLM verify.
- 4 truy vấn mỗi slide: title / message / entities / relations → hợp + khử trùng
- Verify phải **bắt trích 2 câu bằng chứng**; không trích được → hạ confidence
- Quan hệ: `source_of` | `elaborates` | `evidence_for` | `contrast` | `none`
- **Backfill 2 chiều.** Chunk không map được → `align_role: "background"`, GIỮ LẠI.
  Đó là phần kiến thức slide đã lược bỏ, là lý do KB tồn tại.
- Skip align với `slide_type` ∈ {title, agenda, section_header, thank_you, qa}

### S4

- Mọi câu `content` phải có `grounding`; `null` → flag đỏ (NT4 §2)
- Chia theo `build_step`, không tiết lộ nội dung chưa hiện lên
- Pass 2 cân thời lượng theo `time_budget` của S2
- Tiếng Việt: **190–210 âm tiết/phút**. Đếm âm tiết, KHÔNG đếm từ,
  và đếm **theo `pronunciation.json`** (viết tắt đọc thế nào thì đếm thế ấy)
- Dùng `concept_map` để KHÔNG giải thích lại khái niệm đã định nghĩa ở trang trước
- **Tự nhiên — 7 đòn bẩy, xếp theo tác động:**
  1. **Văn nói ≠ văn viết** (nguyên nhân số một). Cấm `việc…`, `sự…`, `được thực hiện bởi`,
     danh từ hoá. Câu chủ động, mệnh đề ngắn.
  2. **Nhịp** — trộn câu 6–12 / 15–20 / 25–30 âm tiết. Đo bằng **độ lệch chuẩn ≥ 6**.
  3. **`prosody` mỗi câu**: `emphasis[]`, `pause_before_ms`, `speed`
  4. **Từ diễn ngôn đặt ĐÚNG ranh giới cấu trúc** (đầu `build_step`, sau một con số,
     trước một tương phản) — lấy từ `arc` + `dependencies`. Rải ngẫu nhiên tệ hơn không có.
  5. Câu hỏi tu từ ở ranh giới section (từ `arc`)
  6. Không đọc bullet, không đọc bảng theo hàng
  7. `max_syllables` mỗi câu = **30** (không phải 40) — ranh giới ngắt của R7 là ranh
     giới câu, câu 40 âm tiết ≈ 12s không ngắt được
- **Pass 2 cắt theo thứ tự: trùng lặp ở câu `content` TRƯỚC, câu `delivery` SAU CÙNG.**
  Sàn 10% `delivery` là cứng. Không có luật này thì cân giờ vài vòng là kịch bản khô lại.

### S6a — Build SlideIndex

- Multi-field embed, **KHÔNG gộp một vector**: `v_message` (quan trọng nhất) · `v_title`
  · `v_desc` · `v_relations` · sparse(`entities`+`keywords`) · `v_section` · `v_concept`
- **Self-retrieval check**: query bằng chính `message[i]` → top-1 phải là slide `i`.
  Không ra → biểu diễn lẫn nhau → R2 sẽ trượt ở runtime → flag NGAY, trước khi S4 tiêu tiền.
- Sinh `deck_map.txt` (~150 token: danh sách section) thay cho `slide_index.txt` cũ
- Tên collection phải nhúng `model_id` — đổi embedding model mà không rebuild thì runtime
  truy vấn index cũ bằng vector mới và trả rác **mà không báo lỗi**

### S6b — Precompute

- TTS cache key = **hash từng câu** (phần tốn tiền nhất, phải reuse)
- `qa_cache` match ngưỡng > 0.88 mới dùng
- **Một `voice_id` duy nhất** cho cả precomputed lẫn streaming runtime. Lệch giọng giữa
  câu kịch bản và câu trả lời là artifact chói tai nhất của cả hệ thống.
- Hash `pronunciation.json` ghi vào `Scenario`; S6b **so hash trước khi synth**.
  Lệch bảng = S4 đếm một đằng, TTS đọc một nẻo, timing sai mà không ai thấy.
- Xuất **bản nghe thử** (3 trang + mọi câu bị flag) cho S7

---

## 6. Runtime (R1–R7)

| | Lớp | | Lớp |
|---|---|---|---|
| **R1** | Intake & fast-path | **R5** | Streaming speech |
| **R2** | Slide navigation | **R6** | State machine & sync |
| **R3** | Context-aware rewriting | **R7** | Interrupt & turn-taking |
| **R4** | Grounded answering | | |

**R2, R3, R4 KHÔNG phải ba lần gọi** — chúng là ba mặt của MỘT lần gọi LLM.
Escalation không phải lớp riêng, nó là nhánh kết thúc của R4.

```
input → regex fast-path ──(khớp)──→ goto_slide()          [~5ms]
      └─(không khớp)─→ phát filler prerecorded (song song)
                     └→ 1× LLM function-calling
                        (state slide + slide_index + lịch sử)
                          ├→ goto_slide / find_slide → confidence gate
                          ├→ search_kb(query đã rewrite) → generate streaming → TTS theo câu
                          └→ meta_action
```

**Luật cứng:**

- **Đúng 1 lần gọi LLM** cho routing + rewrite + chọn tool. KHÔNG tách router riêng.
  (R3a là bước deterministic, KHÔNG phải lần gọi model thứ hai.)
- **KHÔNG nhồi index hay bảng toàn bộ vào prompt.** Ranh giới phân loại:

  ```
  TRẠNG THÁI  -> inline, bounded   "tôi đang nhìn gì" — không index nào trả lời được
                 SlideRepr trang hiện tại · history 3 lượt · deck_map (~150 tok)
  TRI THỨC    -> TRUY XUẤT         slide_index · concept · section · KB chunk
  ```

  Prompt mục tiêu **~1.3k token**, không phải 3.6k.
- **R2 = retrieve → rerank → LLM chọn.**
  - hybrid multi-field trên `slide_index_{deck}` → **top-k = 5** → rerank
    (`bge-reranker-v2-m3`) → **top-3** → LLM chỉ VERIFY và CHỌN trong 3, kèm lý do
  - Trượt ở tầng truy xuất thì tầng LLM KHÔNG cứu được → theo dõi `recall@k`,
    dưới 95% thì nới `k`
- **R3 tách đôi để gỡ vòng tròn** (muốn truy xuất cần query đã rewrite, muốn rewrite
  cần LLM, LLM chạy sau truy xuất):
  - **R3a — mở rộng query, DETERMINISTIC, ~5ms, không gọi model.** Khớp chuỗi từ chỉ trỏ
    vào `relations[].visual` / `visual_elements`, nối thêm `entities` trang hiện tại
    → `query_expanded` dùng để TRUY XUẤT.
  - **R3b — rewrite thật, trong lần gọi LLM duy nhất.** `query_rewritten` là tham số tool;
    `text` GỐC mới là thứ dùng để sinh câu trả lời.
- **Confidence gate:** `margin = rerank(top1) − rerank(top2) < threshold` → KHÔNG nhảy,
  hỏi lại + thumbnail.
  - Score lấy từ **RERANKER** — số thật, calibrate được. KHÔNG dùng điểm LLM tự khai
    (tự tin thái quá có hệ thống).
  - Ngưỡng **fit trên bộ eval 50 câu có nhãn**, KHÔNG đoán. Điểm vận hành:
    `harmful_jump < 2%`, chấp nhận `ask_rate ~15%`. Để trong config, không hardcode.
  - Chỉ có 1 ứng viên trên ngưỡng sàn → coi như `margin = 0` → hỏi lại.
- **QA_CURRENT trả lời thẳng trong lần gọi routing**, không gọi tool rồi gọi LLM lần nữa
  (tiết kiệm 400–700ms). Bắt buộc kèm `grounding` trỏ vào `slide_repr`, validate ref bằng code.
  `SlideRepr` đã qua S7 duyệt nên nó LÀ nguồn đã kiểm, không phải trí nhớ của model.
- **Ma trận ngắt (R7):** điều hướng → ngắt ngay ở ranh giới câu · hỏi nội dung → đợi hết
  trang (trừ khi hàng đợi > 3) · meta → áp dụng ngay, KHÔNG ngắt lời · đang `navigating`
  → đợi ack xong đã.
- **Kiểm tra ngắt sau MỖI CÂU**, không liên tục và không sau mỗi trang.
- **`at_slide` chụp lúc NHẬN câu hỏi**, không phải lúc xử lý — nếu không R3 giải sai tiền ngữ.
- **Orchestrator là nguồn chân lý duy nhất về state.** Renderer phải ngu, chỉ nhận lệnh + ack.
  Không ack trong 500ms → retry rồi mới cập nhật state.
- **TTS phải streaming theo câu**, cắt theo dấu chấm từ token stream. Đợi generate xong là +2–3s.
- **Resume phải nói ra miệng.** Nhảy lặng lẽ về trang cũ thì khán giả mất dấu.
- Câu trả lời **2–4 câu**, không phải 3 đoạn văn. Ép cả prompt lẫn `max_tokens`.
- Retrieval score thấp → **escalate người thật**, KHÔNG bịa.

---

## 7. Cấu trúc lưu trữ (nhiều deck)

```
SHARED LAYER              ← dùng chung mọi deck
├── KB chunks + embeddings (metadata: source_doc, deck_ids[], content_type)
│   └── Qdrant: kb_chunks__{model_id}
└── pronunciation.json     ← thuật ngữ trùng nhau giữa các deck

PER-DECK LAYER
└── deck_{id}/
    ├── SlideRepr[]  DeckStructure  AlignmentMap  Scenario
    ├── Qdrant: slide_index__{deck_id}__{model_id}   ← multi-field
    ├── deck_map.txt        (~150 token, danh sách section)
    ├── audit/self_retrieval.json
    └── precomputed/

SESSION LAYER
└── active_deck_id → nạp đúng 1 bundle
```

- KB **shared** (nhiều deck dùng chung nguồn), Alignment **per-deck**
- Query KB luôn kèm filter `deck_ids ∋ active_deck_id`
- **Một phiên = một deck active.** Không cho nhảy slide sang deck khác.
  Hỏi sang deck khác → trả lời bằng lời + câu mềm, KHÔNG điều hướng.

---

## 8. Incremental build

```
hash slide không đổi → reuse SlideRepr, Scenario, TTS
hash slide đổi       → chạy lại S1, S3, S4 cho riêng nó
luôn chạy lại S2     → cấu trúc toàn cục có thể lệch
luôn chạy lại S6a    → SlideIndex phụ thuộc S1+S2, rẻ (~25s)
S5 gần như không bao giờ chạy lại
```

Sửa 3/20 trang → ~40s thay vì ~6 phút.

Lan `dirty`: slide hash đổi → **cộng thêm** slide kề sau (vì câu chuyển) và slide có
`dependencies` giao tập dirty (vì tham chiếu ngược).

Người duyệt sửa `pronunciation.json` ở S7 → **đếm lại âm tiết** (rẻ, không gọi LLM) +
synth lại câu chứa từ đó; lệch timing > 15% thì chạy lại pass 2 của S4.

---

## 9. Quy ước code

- Python 3.11+, type hints bắt buộc
- **Pydantic** cho mọi artifact schema. Không dùng dict trần giữa các stage.
- Mỗi stage là một module độc lập, nhận/trả Pydantic model, **có thể chạy riêng qua CLI**
- Artifact ghi ra JSON, đọc lại được — pipeline phải resume được từ bất kỳ stage nào
- Gọi LLM/VLM: retry với exponential backoff, log full prompt + response vào `logs/`
- Mọi prompt nằm trong `prompts/*.md`, KHÔNG hardcode trong file .py
- Async cho mọi I/O; S1 và S4 phải song song hoá được (mặc định 5 luồng)
- Không `print()`, dùng `logging` hoặc `rich`

### Thư viện

| Việc            | Dùng                                                            |
| ---------------- | ---------------------------------------------------------------- |
| Parse pptx       | `python-pptx` + đọc XML thô cho animation timing            |
| Render PNG       | LibreOffice headless → PDF →`PyMuPDF` rasterize              |
| Parse PDF nguồn | `PyMuPDF`, `unstructured` hoặc `docling` cho cây heading |
| Embedding        | `bge-m3` (dense + sparse trong 1 forward)                      |
| Rerank           | `bge-reranker-v2-m3` — dùng cho cả R2 lẫn S3                |
| Vector DB        | Qdrant (cần metadata filter tốt)                               |
| Schema           | Pydantic v2                                                      |

**Cảnh báo:** LibreOffice render pptx không khớp 100% với PowerPoint (font thay thế,
SmartArt đôi khi vỡ). Phải cài font Việt vào container.

---

## 10. CẤM

- ❌ Để LLM sinh lại `title`, `chart_data`, `tables` — đã có bản đúng từ S0
- ❌ Fixed-size chunking ở S5
- ❌ Embed `text_raw` thay vì `text_enriched`
- ❌ Nhận link alignment chỉ dựa trên similarity score, bỏ qua bước verify
- ❌ Vứt chunk `background` (không map được vào slide nào)
- ❌ **Nhồi index hoặc bảng toàn bộ vào prompt** (`slide_index` cả deck, `concept_map`
  cả deck) — chỉ TRẠNG THÁI mới được inline, TRI THỨC phải truy xuất
- ❌ Gộp một vector cho cả slide — phải multi-field
- ❌ Dùng điểm LLM tự khai làm confidence gate khi đã có điểm reranker
- ❌ Tách router riêng ở runtime (thêm 300–400ms vô ích)
- ❌ Đợi generate xong mới TTS
- ❌ Nhảy slide khi confidence gate không đạt
- ❌ Để renderer tự quyết trang
- ❌ Dùng LLM tự phình kiến thức từ slide để làm KB khi thiếu tài liệu nguồn
- ❌ Bắt người duyệt cả 20 trang ở S7 — chỉ duyệt phần bị flag
- ❌ Hardcode prompt trong file .py
- ❌ Fast-path (R1) bắt câu hỏi nội dung — chỉ điều hướng tường minh
- ❌ Đoán ngưỡng confidence gate thay vì fit trên bộ eval
- ❌ Trích dẫn bằng ký hiệu `[slide 7]` — TTS đọc thành "ngoặc vuông slide bảy"
- ❌ Trả lời sâu về slide có `answer_depth: "describe_only"` (S7 đã đánh dấu là không có nguồn)
- ❌ Ngắt giữa câu (trừ điều hướng, và phải fade ~80ms)
- ❌ Đọc to câu hỏi troll rồi mới từ chối — đọc lên là troll thành công
- ❌ Nói trước khi nhận ack của renderer
- ❌ `message` / `description` / `gloss` / `summary` chứa đại từ trỏ ra ngoài trang
  hoặc từ chỉ vị trí — chúng bị embed một mình
- ❌ Pass 2 của S4 cắt câu `delivery` xuống dưới sàn 10%
- ❌ Giọng TTS của precomputed khác giọng của streaming runtime
- ❌ Đặt tên Qdrant collection không nhúng `model_id`

---

## 11. Quality gate (chạy được trong CI)

| Chỉ số                          | Ngưỡng                                    |
| --------------------------------- | ------------------------------------------- |
| Alignment coverage                | ≥ 80% slide có ≥1 nguồn conf > 0.6      |
| Ungrounded rate (câu `content`)  | < 10%                                       |
| Timing deviation                  | < 15% so với budget                        |
| Flag precision (S7)               | ≥ 60%                                      |
| P95 latency tới byte audio đầu | < 2.5s                                      |
| Self-retrieval top-1 (S6a)        | ≥ 90% slide                                |
| R2 recall@5                       | ≥ 95% — dưới thì nới k                  |
| R2 Top-1 accuracy                 | báo cáo                                   |
| R2 harmful jump rate              | báo cáo — nhảy sai mà không hỏi lại |

**Proxy tự nhiên — chạy được trong CI:**

| Chỉ số                       | Ngưỡng |
| ------------------------------ | -------- |
| Độ lệch chuẩn âm tiết/câu | ≥ 6     |
| Từ văn viết bị cấm       | = 0      |
| Tỉ lệ câu `delivery`        | 10–25%  |

**Naturalness MOS ≥ 3.8/5 KHÔNG phải gate CI** — nó cần 3 người ngồi nghe.
Đó là **release gate**, chạy trước buổi thuyết trình thật.

---

## 12. Phạm vi v1

**Trong phạm vi:** chỉ `.pptx` (không nhận PDF làm deck) · kênh hỏi bằng **text**
(QR → form web, không ASR) · app tự render slide · deck cố định lúc build ·
tiếng Việt, thuật ngữ giữ gốc tiếng Anh · 1 deck active mỗi phiên

**Ngoài phạm vi v1:** voice/ASR · robot vật lý · điều khiển PowerPoint ngoài ·
upload deck lúc runtime · cross-deck navigation
