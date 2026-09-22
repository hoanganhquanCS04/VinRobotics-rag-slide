# Tài liệu hệ thống

| Nhóm | Nội dung |
|---|---|
| [`offline/`](./offline/) | Đặc tả nhánh offline S0–S7: input, output, luật, failure mode, quality gate |
| [`runtime/`](./runtime/) | Đặc tả nhánh runtime R1–R7: vì sao có lớp, cơ chế, failure mode, chỉ số |
| `eval/` | *(chưa viết)* bộ test có nhãn, ablation, báo cáo |

## Nhánh offline

Đọc [`offline/00-overview.md`](./offline/00-overview.md) trước, rồi theo **thứ tự chạy thật**
(số stage là lớp khái niệm, không phải thứ tự thực thi):

| Đọc theo thứ tự | File | Một câu |
|---|---|---|
| — | [00-overview](./offline/00-overview.md) | **Bốn** nguyên tắc, hai nhánh, hai index, sơ đồ khối từng stage, incremental |
| 1 | [S0 Ingest](./offline/s0-ingest.md) | Parse pptx + render PNG. Thuần parsing, không model |
| 2 | [S1 Slide Understanding](./offline/s1-slide-understanding.md) | VLM sinh **ý nghĩa** · `message` phải **tự đứng được** |
| 3 | [S2 Deck Structure](./offline/s2-deck-structure.md) | Nhìn toàn cục, **không viết câu nào** · `concept_map[].gloss` |
| ∥ | [S5 KB Construction](./offline/s5-kb-construction.md) | Chunk + contextual enrichment + hybrid index. Chạy song song từ t=0 |
| 4 | [S3 Alignment](./offline/s3-alignment.md) | Tìm chunk **là nguồn gốc** của slide, không phải chunk giống slide |
| ∥ | [S6a Build SlideIndex](./offline/s6-precompute.md) | Multi-field embed + **self-retrieval check**. Song song với S3 |
| 5 | [S4 Scenario](./offline/s4-scenario.md) | Kịch bản nói · `content` vs `delivery` · 7 đòn bẩy tự nhiên |
| 6 | [S6b Precompute](./offline/s6-precompute.md) | TTS theo câu, một giọng duy nhất, qa_cache, bản nghe thử |
| 7 | [S7 HITL Review](./offline/s7-hitl-review.md) | Duyệt **chỉ phần bị flag** · vòng ĐỌC + vòng **NGHE** (MOS) |

Hai thay đổi lớn đã áp vào toàn bộ bộ docs:

- **NT4 — tự nhiên là yêu cầu.** Gỡ va chạm với NT3 bằng cách tách câu `content` / `delivery`
- **Bỏ nhồi context, làm RAG truy xuất chuẩn.** `slide_index` thành index thật ở S6a;
  prompt runtime co từ ~3.6k xuống ~1.3k token

## Nhánh runtime

Đọc [`runtime/00-overview.md`](./runtime/00-overview.md) trước — nó giải thích **vì sao
R2/R3/R4 không phải ba lần gọi** mà là ba mặt của một lần gọi. Không nắm chỗ đó thì đọc
từng file riêng sẽ hiểu sai thành pipeline tuần tự.

| | File | Một câu |
|---|---|---|
| — | [00-overview](./runtime/00-overview.md) | Hai vòng lặp, một lần gọi LLM, state, ngân sách, 3 quyết định đã chốt |
| **R1** | [Intake & fast-path](./runtime/r1-intake-fastpath.md) | Hàng đợi + khử trùng · regex điều hướng ~5ms |
| **R2** | [Slide navigation](./runtime/r2-navigation.md) | LLM chọn trang toàn cục + **confidence gate** |
| **R3** | [Context-aware rewriting](./runtime/r3-context-rewriting.md) | Giải tiền ngữ bám **trạng thái phi ngôn ngữ** |
| **R4** | [Grounded answering](./runtime/r4-grounded-answering.md) | 3 phạm vi · trích dẫn trang · biết nói không biết |
| **R5** | [Streaming speech](./runtime/r5-streaming-speech.md) | Cắt câu từ token stream → TTS từng câu |
| **R6** | [State machine & sync](./runtime/r6-state-sync.md) | Nguồn chân lý duy nhất · hợp đồng ack · resume |
| **R7** | [Interrupt & turn-taking](./runtime/r7-interrupt-turntaking.md) | Khi nào được ngắt · hàng đợi · barge-in |

Escalation **không** là lớp riêng — nó là nhánh kết thúc của R4.

Context ngắn gọn cho AI coding agent nằm ở [`../CLAUDE.md`](../CLAUDE.md) — đó là bản rút gọn
để nhét vào context window. Bộ docs này là bản đầy đủ có lý do đằng sau mỗi luật.
Khi hai bên mâu thuẫn, `CLAUDE.md` là bản chuẩn về *luật*, docs là bản chuẩn về *lý do*.
