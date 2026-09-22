# S6 — Build SlideIndex & Precompute

S6 **tách làm hai** vì hai nửa có phụ thuộc khác nhau:

| | Input | Output | Chạy được khi nào |
|---|---|---|---|
| **S6a** Build SlideIndex | `SlideRepr[]` + `DeckStructure` | Qdrant `slide_index` + `deck_map.txt` + audit | ngay sau S2 — **song song với S3** |
| **S6b** Precompute | `Scenario[]` + `pronunciation.json` | `precomputed/` | sau S4 |

```
S5 || S0 -> S1 -> S2 -+-> S6a -> self-retrieval check --+
                      +-> S3 -> S4 -> S6b --------------+-> S7
```

S6a nằm gọn trong bóng của S3 (~25s trong ~105s) nên **không tốn thêm một giây nào** vào
tổng thời gian build.

---

## 1. Vì sao có hai lớp này

### 1.1 S6a — offline giờ dựng INDEX, không chỉ dựng nội dung

Thay đổi so với bản trước: runtime **không còn được nhồi `slide_index` vào prompt**.
Ranh giới phân loại:

```
TRẠNG THÁI  -> inline, bounded   "tôi đang nhìn gì" — không index nào trả lời được
TRI THỨC    -> TRUY XUẤT         slide · section · concept · KB chunk
```

Nên `slide_index` phải trở thành một **index thật**, và S6a là nơi dựng nó.

Lợi ích không chỉ là prompt ngắn đi:

| | Nhồi prompt | Truy xuất |
|---|---|---|
| Điểm cho confidence gate | LLM tự khai, **lệch có hệ thống** | **reranker, số thật, calibrate được** |
| Ablate từng thành phần | không — một hộp đen | dense / +sparse / +rerank / +LLM verify |
| Khi deck to lên | vỡ | vẫn chạy |

### 1.2 S6b — mua latency của runtime

Đây là **NT1 ở dạng thuần khiết nhất**: mọi thứ tính trước được đều bị đẩy vào đây, để
runtime chỉ còn đọc file.

Kết quả: ~90% thời lượng buổi nói có **latency bằng 0**, và phần tương tác được che bằng
filler + hành động thị giác.

---

# S6a — Build SlideIndex

## 2. Multi-field embed — KHÔNG gộp một vector

```
mỗi slide  -> v_message     <- quan trọng nhất cho điều hướng
              v_title
              v_desc         (description)
              v_relations    (triple serialize)
              sparse         (entities + keywords, BM25)

mỗi section -> v_section     (summary)
mỗi concept -> v_concept     (gloss)
```

**Vì sao multi-field:**

```
"chỗ nói về việc không cần train lại"  -> khớp v_message
"cái sơ đồ ba khối"                     -> khớp v_desc
"BM25"                                  -> khớp sparse
"quay lại phần đánh giá"                -> khớp v_section
```

Gộp tất cả vào một vector thì **làm loãng cả bốn**. Đây đúng lớp lỗi mà
[S5](./s5-kb-construction.md) đã tránh bằng `text_enriched` — biểu diễn phải khớp với
dạng câu hỏi sẽ tới.

Điều kiện cần: `message`, `description`, `gloss`, `summary` phải **tự đứng được** —
xem [S1 §3.1](./s1-slide-understanding.md). Chúng bị embed **một mình**, không có trang kề
nào bên cạnh để trỏ vào.

## 3. Tên collection phải nhúng `model_id`

```
slide_index__{deck_id}__{model_id}
kb_chunks__{model_id}
```

Đổi embedding model mà quên rebuild → runtime truy vấn index cũ bằng vector mới và trả về
**rác, không báo lỗi**. Đây là lớp lỗi im lặng, tệ hơn crash.

`kb_chunks` rebuild một lần. `slide_index` là **per-deck** nên phải rebuild **N lần** —
nhớ khi lên kế hoạch đổi model.

Runtime **từ chối nạp** bundle khi `model_id` trong tên collection lệch với model đang dùng.

## 4. Self-retrieval check ★

Phép thử thật, end-to-end, chạy ngay sau khi index dựng xong:

```
với mỗi slide i:
    query = message[i]
    -> truy xuất trên chính slide_index vừa dựng
    -> top-1 có phải slide i không?

không ra top-1  ->  biểu diễn của trang này LẪN với trang khác
                ->  R2 SẼ trượt ở runtime
                ->  flag NGAY
```

**Giá trị nằm ở thời điểm:** nó chạy **trước S4**, nên bắt được vấn đề **trước khi tiêu
tiền viết kịch bản** cho những trang đó. Đây là lý do đáng tách S6a ra chạy sớm chứ không
gộp vào S6b.

```json
// audit/self_retrieval.json
{
  "pass_rate": 0.90,
  "fails": [
    {"slide_id": 8, "got_top1": 11, "score_self": 0.71, "score_top1": 0.79,
     "note": "message của 8 và 11 đều xoay quanh truy xuất"}
  ]
}
```

Gate: **≥ 90% slide đạt top-1.**

**Hai cách xử lý, người quyết ở S7:**

| | Khi nào | Làm gì |
|---|---|---|
| `message` viết tệ | Trang thật ra khác hẳn nhau | Sửa `message`, chạy lại S6a |
| **Trùng chủ đề THẬT** | Trang 8 "Retriever" và 11 "Chunking" đều xoay quanh truy xuất | Đánh dấu **"cặp đã biết, chấp nhận"** vào `review.json` → lần sau không flag nữa |

Lối thứ hai bắt buộc phải có. Không có nó thì check kêu oan mãi ở cùng một cặp, và người
duyệt sẽ học cách bỏ qua flag — lúc đó cả cơ chế flag mất giá trị.

## 5. `deck_map.txt` — thay cho `slide_index.txt`

```
DECK: Giới thiệu RAG cho hệ thống hỏi đáp nội bộ | 20 trang | 30 phút
[sec1] Mở đầu            trang 1-3
[sec2] Nền tảng          trang 4-6
[sec3] Kiến trúc         trang 7-10
[sec4] Kỹ thuật          trang 11-13
[sec5] Đánh giá          trang 14-17
[sec6] Kết luận          trang 18-20
```

**~150 token**, thay cho ~1.4k của `slide_index.txt` cũ.

Vì sao vẫn giữ chứ không bỏ hẳn: LLM cần biết deck có mấy phần và tên gì, để câu chuyển và
câu báo tiến độ (*"ta đang ở phần 3 trên 6"*) nghe tự nhiên. 150 token là **trạng thái**,
không phải "nhồi context".

## 6. Quality gate ra khỏi S6a

| Điều kiện | Hành động |
|---|---|
| `self_retrieval.pass_rate` < 90% | Flag mỗi slide fail, không chặn build |
| Slide thiếu `v_message` | Fail cứng |
| `gloss` thiếu ở khái niệm nào | Fail — S2 phải sửa |
| Tên collection thiếu `model_id` | Fail cứng |
| `deck_map.txt` > 400 token | Cảnh báo — nhiều section bất thường |

---

# S6b — Precompute

## 7. So hash `pronunciation.json` TRƯỚC KHI synth

```
Scenario.pron_hash == hash(pronunciation.json hiện tại) ?
    lệch -> DỪNG, không synth
```

Vì sao nghiêm trọng: S4 **đếm âm tiết** theo bảng A, S6b **synth** theo bảng B → mọi
`target_sec` sai, `time_budget` sai, và **không có triệu chứng nào nhìn thấy được** cho
tới lúc chạy thật thì buổi thuyết trình lố giờ.

Cùng lớp lỗi với `tts_hash` lệch hàm băm. Cả hai đều phải chặn bằng so hash, không bằng
quy trình.

## 8. TTS — cache theo câu, một giọng duy nhất

```
tts_hash = SHA256( normalize(text) + voice_id + speed + format )
file     = precomputed/tts/{tts_hash}.mp3
```

**Cache key = hash TỪNG CÂU**, không phải từng trang:

| Tình huống | Cache theo câu | Cache theo trang |
|---|---|---|
| Sửa 1 câu ở trang 7 | synth lại 1 câu | synth lại cả trang |
| Câu xã giao lặp ở nhiều deck | dùng lại | synth lại mỗi deck |

`normalize` bỏ whitespace thừa nhưng **giữ nguyên dấu câu** — dấu câu đổi thì ngữ điệu đổi,
phải coi là câu khác.

### Một `voice_id` duy nhất — luật cứng

> **`voice_id` và `speed` của audio precomputed phải TRÙNG với streaming TTS ở runtime.**

Lệch giọng giữa câu kịch bản và câu trả lời là **artifact chói tai nhất của cả hệ thống**:
robot đang nói bằng một giọng, khán giả hỏi, rồi câu trả lời phát ra bằng giọng khác.

`voice_id` chốt một lần trong config deck, [R5](../runtime/r5-streaming-speech.md) đọc cùng
config đó. Validate bằng code ở cả hai đầu.

### Áp `prosody` của S4

```json
"prosody": {"emphasis": ["tách hẳn"], "pause_before_ms": 250, "speed": 0.96}
```

`speed` ở đây là **delta quanh tốc độ nền**, không phải tốc độ tuyệt đối — nếu không thì
nó xung đột với luật một giọng ở trên.

Engine nào không nhận emphasis thì bỏ qua field đó, **không fail** — prosody là cải thiện,
không phải điều kiện đúng/sai.

### Đối chiếu ngược với ước lượng của S4

Lưu `duration_ms` **thật** của mỗi file. Lệch > 20% so với ước lượng âm tiết trên toàn deck
→ chỉnh lại hằng số 200 âm tiết/phút cho giọng đó và ghi vào config.

## 9. Filler prerecorded

Runtime phát filler ngay khi nhận câu hỏi, song song với lần gọi LLM — lớp che latency
quan trọng nhất (~2s).

```
"Để mình xem lại phần đó nhé."
"Câu hỏi hay, mình trả lời ngay đây."
"Mình tra nhanh trong tài liệu một chút."
```

**Filler phải TRUNG TÍNH, không được hứa.** "Để mình tra tài liệu" mà kết cục là escalate
thì nghe rất kỳ. Chọn ngẫu nhiên không lặp liền nhau.

Đặt ở `data/kb/fillers/` (shared), cùng `voice_id` với mọi thứ khác.

## 10. `qa_cache`

Câu hỏi dự đoán trước → trả lời sẵn → runtime hit cache trả về **~200ms**.

```json
{"q": "Embedding là gì?",
 "q_vec": [],
 "answer": "Embedding là cách biến văn bản thành vector số...",
 "slide_ref": 5,
 "grounding": {"type": "kb_chunk", "ref": "doc1#c012"},
 "tts_hash": "5c1a9b..."}
```

Nguồn sinh: LLM sinh 3–5 câu hỏi/slide từ `SlideRepr` + `AlignmentMap`, cộng câu hỏi thật
thu được từ các buổi trước (nếu có log).

**Ngưỡng match: cosine > 0.88 mới dùng.** Cố tình cao — cache trả nhầm một câu trả lời
gần đúng còn tệ hơn là chậm thêm một giây.

Audio của câu trả lời cache cũng synth sẵn; đó mới là chỗ tiết kiệm thật.

## 11. Thumbnail

`precomputed/thumbs/s{n}.jpg`, cạnh dài ~480px.

Dùng cho **confidence gate** của [R2](../runtime/r2-navigation.md): khi margin nhỏ, hệ
thống không nhảy mà hỏi lại kèm 2 thumbnail — *"Ý bạn là trang này hay trang này?"*.

Không có thumbnail thì câu hỏi lại chỉ có chữ, và khán giả sẽ đoán sai.

## 12. Bản nghe thử cho S7 ★

```
precomputed/listen_sample/
├── slide_03.mp3     3 trang đại diện (đầu / giữa / cuối deck)
├── slide_12.mp3
├── slide_18.mp3
└── flagged/         MỌI câu bị flag, mỗi câu 1 file
```

Vì sao cần: **naturalness không đọc ra được, phải nghe.** Kịch bản đạt cả 6 proxy tự động
vẫn có thể nghe như máy — ngữ điệu phẳng, ngắt sai chỗ, viết tắt đọc sai.

S7 chấm **MOS 1–5** trên bộ này, 3 người. Gate ≥ 3.8 và đó là **release gate**, không phải
CI gate.

## 13. Output layout

```
data/decks/{deck_id}/
├── index/                       <- S6a, Qdrant slide_index__{deck}__{model}
├── deck_map.txt                 <- S6a, ~150 token
├── audit/self_retrieval.json    <- S6a
└── precomputed/                 <- S6b
    ├── tts/{tts_hash}.mp3
    ├── qa_cache.jsonl
    ├── thumbs/s{n}.jpg
    ├── listen_sample/
    └── manifest.json            slide -> step -> sentence -> file + duration + prosody
```

`manifest.json` là thứ runtime đọc lúc khởi động. Nó phải đủ để phát cả buổi **mà không
cần mở lại `scenario.json`**.

## 14. Quality gate ra khỏi S6b

| Điều kiện | Hành động |
|---|---|
| `pron_hash` lệch | **Fail cứng, không synth** |
| Câu trong `Scenario` không có file audio | Fail cứng |
| `voice_id` khác config runtime | **Fail cứng** |
| `sum(duration_ms)` lệch `time_budget` > 15% | Flag `timing_overflow` — đây là số **thật**, tin hơn ước lượng của S4 |
| `qa_cache` rỗng | Cảnh báo, không chặn |
| `listen_sample/` rỗng | Fail — S7 không chấm MOS được |

## 15. Cấm

- Cache TTS theo trang thay vì theo câu
- Giọng precomputed khác giọng streaming runtime
- Synth khi `pron_hash` lệch
- Hạ ngưỡng `qa_cache` xuống dưới 0.88 để tăng hit rate
- **Nhồi cả `slide_index` vào prompt runtime** — đó là việc của index, không phải của prompt
- Gộp một vector cho cả slide
- Đặt tên collection không có `model_id`
- Filler hứa hẹn điều mà hệ thống có thể không làm được
