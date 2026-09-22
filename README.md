# Slide Presenter Agent

Agent tự thuyết trình một bộ slide và xử lý tương tác thời gian thực từ khán giả —
trả lời câu hỏi và điều hướng slide — trong khi luôn đồng bộ với trạng thái trình chiếu
và có nguồn truy nguyên được.

---

## Vấn đề

Slide là bản nén mất mát của kiến thức. Phần bị mất nằm trong đầu người thuyết trình.
Một hệ thống chỉ đọc slide thì chỉ đọc được bullet point — không giải thích được,
không trả lời được câu hỏi tiếp theo.

Deck mục tiêu có đặc điểm **ít chữ nhiều hình**: trung bình dưới 20 từ mỗi trang,
ngữ nghĩa nằm trong sơ đồ và biểu đồ. Pipeline RAG text thuần thất bại hoàn toàn ở đây.

Hệ thống giải quyết bằng cách tách làm hai nhánh: một nhánh **offline** tái tạo lại
phần kiến thức đã bị lược bỏ (và trả trước toàn bộ chi phí tính toán), một nhánh
**online** chỉ tra cứu lại những gì offline đã dựng sẵn, trong ngân sách 2.5 giây.

---

## Kiến trúc

```
NHÁNH DECK                          NHÁNH NGUỒN
deck.pptx                           source/*.pdf
    │                                   │
 S0 Ingest ──────┐                  S5 KB Construction
    │            │                  chunk · enrich · index
 S1 Understanding│                      │
    │            │                      │
 S2 Structure    └──── S3 Alignment ────┘
    │                       │
    └──────────────── S4 Scenario
                            │
                       S6 Precompute
                            │
                       S7 HITL Review
                            │
                       Runtime R1–R7
```

Thứ tự chạy thật: `S5 ∥ S0 → S1 → S2 → S3 → S4 → S6 → S7`
(số stage là lớp khái niệm, không phải thứ tự — S5 mang số lớn nhưng chạy sớm nhất)

| Stage | Nhiệm vụ |
|---|---|
| **S0** Ingest | Parse pptx (XML + render PNG) → `RawSlide[]`. Thuần parsing, không model |
| **S1** Slide Understanding | VLM sinh ngữ nghĩa mà parsing không lấy được → `SlideRepr[]` |
| **S2** Deck Structure | Stage duy nhất nhìn toàn cục: phần, phụ thuộc, mạch bài, bản đồ khái niệm |
| **S5** KB Construction | Chunk + contextual enrichment + hybrid index trên tài liệu nguồn |
| **S3** Alignment | Nối mỗi slide với đoạn nguồn đã đẻ ra nó. Điểm hội tụ của hai nhánh |
| **S4** Scenario | Sinh kịch bản nói, mỗi câu kèm `grounding` truy nguyên được |
| **S6** Precompute | TTS sẵn, Q&A cache, thumbnail — mua latency của runtime |
| **S7** HITL Review | Người duyệt **chỉ phần bị flag**, không duyệt toàn bộ |

---

## Cấu trúc repo

```
.
├── CLAUDE.md               # context cho AI coding agent — đọc trước khi code
├── README.md
├── pyproject.toml
│
├── src/
│   ├── schemas/            # Pydantic models cho mọi artifact
│   │   ├── raw_slide.py
│   │   ├── slide_repr.py
│   │   ├── deck_structure.py
│   │   ├── kb_chunk.py
│   │   ├── alignment.py
│   │   └── scenario.py
│   │
│   ├── offline/
│   │   ├── s0_ingest.py
│   │   ├── s1_understand.py
│   │   ├── s2_structure.py
│   │   ├── s3_align.py
│   │   ├── s4_scenario.py
│   │   ├── s5_kb.py
│   │   ├── s6_precompute.py
│   │   └── pipeline.py     # orchestrator, hỗ trợ resume + incremental
│   │
│   ├── runtime/
│   │   ├── orchestrator.py # nguồn chân lý duy nhất về state
│   │   ├── fast_path.py    # regex điều hướng, ~5ms
│   │   ├── agent.py        # 1× LLM function-calling
│   │   ├── navigation.py   # R2 + confidence gate
│   │   ├── retrieval.py    # R4
│   │   ├── state.py        # state machine + resume stack
│   │   └── tts.py          # streaming theo câu
│   │
│   ├── servers/            # MCP servers (tùy chọn)
│   │   ├── slide_control.py
│   │   └── knowledge.py
│   │
│   └── review/             # UI duyệt HITL
│
├── prompts/                # mọi prompt ở đây, không hardcode trong .py
│   ├── s1_understand.md
│   ├── s2_structure.md
│   ├── s3_verify.md
│   ├── s4_scenario.md
│   └── runtime_agent.md
│
├── data/
│   ├── decks/{deck_id}/    # per-deck bundle
│   ├── kb/                 # shared layer
│   └── eval/               # bộ test có nhãn
│
└── tests/
```

---

## Cài đặt

```bash
# Python 3.11+
uv sync            # hoặc: pip install -e .

# LibreOffice headless để render slide
sudo apt install libreoffice fonts-liberation

# Font tiếng Việt (bắt buộc, nếu không render sẽ vỡ dấu)
sudo apt install fonts-noto fonts-be-vietnam-pro

cp .env.example .env    # điền API key
```

---

## Sử dụng

### Build một deck

```bash
# chạy toàn bộ nhánh offline
python -m src.offline.pipeline build \
    --deck data/decks/rag-intro/deck.pptx \
    --source data/sources/rag/ \
    --budget-min 30

# chạy riêng một stage (mọi stage đều standalone)
python -m src.offline.s1_understand --deck-id rag-intro
python -m src.offline.s3_align      --deck-id rag-intro

# rebuild tăng dần — chỉ chạy lại slide có hash thay đổi
python -m src.offline.pipeline build --deck-id rag-intro --incremental
```

### Duyệt HITL

```bash
python -m src.review.app --deck-id rag-intro
# → http://localhost:8080
```

Chỉ hiện những chỗ bị flag: câu kịch bản `grounding: null`, slide coverage = 0,
chart trích từ ảnh, hai pass VLM bất đồng, dependency chỉ tiến.

### Chạy buổi thuyết trình

```bash
python -m src.runtime.orchestrator --deck-id rag-intro
# → màn hình trình chiếu:  http://localhost:3000
# → khán giả quét QR gửi câu hỏi: http://localhost:3000/ask
```

### Đánh giá

```bash
python -m src.eval.run --deck-id rag-intro --suite navigation
python -m src.eval.run --deck-id rag-intro --suite qa
python -m src.eval.run --deck-id rag-intro --suite latency
```

---

## Ngân sách hiệu năng

**Offline** (deck 20 trang, lần đầu): ~6 phút.
Rebuild tăng dần khi sửa 3 trang: ~40 giây.

**Online**, tới byte audio đầu tiên:

| Bước | Ngân sách |
|---|---|
| Regex fast-path | ~5 ms (bắt ~40% lệnh điều hướng) |
| 1× LLM function-calling | 400–700 ms |
| Retrieval | 50–150 ms |
| Generation, first token | 300–500 ms |
| TTS chunk đầu | 200–400 ms |
| **Tổng** | **1.2–1.8 s** |

Cộng thêm hai lớp che: filler audio phát ngay khi nhận câu hỏi (~2s), và hành động
thị giác (nhảy trang / highlight) đi trước lời nói. `qa_cache` hit thì trả về ~200ms.
TTS của kịch bản chính đã synth sẵn nên ~90% thời lượng buổi nói có latency bằng 0.

---

## Quality gate

Không đạt thì không deploy.

| Chỉ số | Ngưỡng |
|---|---|
| Alignment coverage | ≥ 80% slide có ≥1 nguồn conf > 0.6 |
| Ungrounded sentence rate | < 10% |
| Timing deviation | < 15% so với budget |
| Flag precision (S7) | ≥ 60% |
| P95 latency | < 2.5 s |

---

## Đánh giá

| Nhánh | Metric | Ground truth |
|---|---|---|
| S1 | Độ đúng `message`, `relations` | Annotate tay 20 slide |
| S3 | Precision / Recall / F1 của link | 20 slide × ~20 ứng viên = 400 cặp |
| S4 | Ungrounded rate, human rating | Đếm tự động + chấm tay |
| R2 | Top-1 accuracy, MRR, **harmful jump rate** | 20 slide × 50 câu điều hướng có nhãn |
| R4 | Faithfulness, tỉ lệ từ chối đúng | Bộ câu hỏi in-scope / out-of-scope |
| HITL | Số phút/deck, flag precision | Phiên duyệt thật |

**Harmful jump rate** (nhảy sai trang mà không hỏi lại) là con số quan trọng nhất
của R2, không phải Top-1 accuracy đơn thuần.

### Ablation

1. **S3**: dense · hybrid · hybrid + LLM verify → bước verify có đáng giá không
2. **S5**: chunk thô vs chunk enriched → contextual enrichment có đáng giá không
3. **R2**: nhét thẳng · prefilter+rerank · phân cấp, đo theo N = 20/50/100/200

---

## Phạm vi v1

**Trong phạm vi**
- Chỉ nhận `.pptx` (PDF mất animation, speaker notes, chart data gốc)
- Kênh hỏi bằng **text** — QR → form web, không ASR
- App tự render slide
- Deck cố định lúc build
- Tiếng Việt, thuật ngữ giữ gốc tiếng Anh
- Một deck active mỗi phiên

**Ngoài phạm vi v1**
- Voice / ASR (phòng ồn là rủi ro lớn nhất và không phải phần nghiên cứu)
- Robot vật lý
- Điều khiển PowerPoint / Google Slides bên ngoài
- Upload deck lúc runtime
- Cross-deck navigation

---

## Roadmap

- [ ] S0 — parser pptx + render, quality gate đầu ra
- [ ] Schema Pydantic cho toàn bộ artifact
- [ ] S5 — KB với contextual enrichment
- [ ] S1 — VLM understanding, 2 pass self-consistency
- [ ] **Bộ eval R2: 50 câu hỏi điều hướng có nhãn trang đúng** ← làm trước khi code runtime
- [ ] S3 — alignment + coverage report
- [ ] S2 — deck structure + validate 5 luật
- [ ] S4 — scenario với grounding trace
- [ ] S6 — precompute
- [ ] Runtime R1–R5
- [ ] S7 — UI duyệt HITL
- [ ] Ablation + báo cáo

---

## Tài liệu

Đặc tả nhánh offline — chi tiết từng stage, hợp đồng dữ liệu, failure mode, quality gate:
[`docs/offline/`](./docs/offline/), bắt đầu từ [`00-overview.md`](./docs/offline/00-overview.md).

| | | |
|---|---|---|
| [S0 Ingest](./docs/offline/s0-ingest.md) | [S1 Understanding](./docs/offline/s1-slide-understanding.md) | [S2 Structure](./docs/offline/s2-deck-structure.md) |
| [S5 KB](./docs/offline/s5-kb-construction.md) | [S3 Alignment](./docs/offline/s3-alignment.md) | [S4 Scenario](./docs/offline/s4-scenario.md) |
| [S6 Precompute](./docs/offline/s6-precompute.md) | [S7 HITL](./docs/offline/s7-hitl-review.md) | |

Đặc tả nhánh runtime — vì sao có từng lớp, cơ chế, failure mode, chỉ số:
[`docs/runtime/`](./docs/runtime/), bắt đầu từ [`00-overview.md`](./docs/runtime/00-overview.md).

| | | |
|---|---|---|
| [R1 Intake & fast-path](./docs/runtime/r1-intake-fastpath.md) | [R2 Navigation](./docs/runtime/r2-navigation.md) | [R3 Context rewriting](./docs/runtime/r3-context-rewriting.md) |
| [R4 Grounded answering](./docs/runtime/r4-grounded-answering.md) | [R5 Streaming speech](./docs/runtime/r5-streaming-speech.md) | [R6 State & sync](./docs/runtime/r6-state-sync.md) |
| [R7 Interrupt & turn-taking](./docs/runtime/r7-interrupt-turntaking.md) | | |

Context cho AI coding agent: [`CLAUDE.md`](./CLAUDE.md) — đọc trước khi sinh code.
