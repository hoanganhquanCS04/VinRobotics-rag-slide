# R2 — Slide navigation

**Vào:** `query_expanded` (từ [R3a](./r3-context-rewriting.md)) + `slide_index` (Qdrant) + state
**Ra:** `slide_id` để nhảy, **hoặc** một câu hỏi lại kèm thumbnail
**Cơ chế:** hybrid retrieve → rerank → LLM chọn trong top-3

---

## 1. Vì sao có lớp này

### 1.1 Điều hướng là hành động vật lý, nhìn thấy được, và bất đối xứng

Đây là điều làm R2 khác hẳn [R4](./r4-grounded-answering.md):

| | Trả lời sai | Nhảy sai trang |
|---|---|---|
| Ai thấy | người hỏi | **cả hội trường, ngay lập tức** |
| Sửa được không | nói lại câu sau | phải nhảy lại, ai cũng thấy là đã sai |
| Hậu quả | mất một câu | **khán giả mất dấu mạch bài** |

Chi phí bất đối xứng dẫn tới một kết luận thiết kế không hiển nhiên:

> **Mục tiêu của R2 không phải "trúng tuyệt đối". Trúng tuyệt đối là mục tiêu không đạt được.**
> Mục tiêu là **không bao giờ nhảy sai mà không hỏi lại.**

Hỏi lại tốn 2 giây. Nhảy sai giữa buổi thì hỏng không cứu được. Vì vậy chỉ số quan trọng
nhất của R2 là **harmful jump rate**, không phải Top-1 accuracy — và hai con số này
**tối ưu ngược chiều nhau**.

### 1.2 Vì sao truy xuất, không nhồi index vào prompt

Bản thiết kế trước nhét cả `slide_index` (~1.4k token, 20 trang) vào prompt và để LLM chọn
toàn cục. Cách đó **chạy được ở N=20** nhưng hỏng ở ba chỗ:

| | Nhồi prompt | Truy xuất |
|---|---|---|
| **Điểm cho confidence gate** | LLM tự khai — **lệch có hệ thống**, nó chấm cho chính lựa chọn của mình | **reranker: số thật, calibrate được** |
| **Ablate từng thành phần** | không — một hộp đen | dense / +sparse / +rerank / +LLM verify |
| **Khi deck to lên** | vỡ | vẫn chạy |

Chỗ đầu tiên là chỗ ăn tiền. Confidence gate là **cơ chế an toàn quan trọng nhất của R2**,
mà trước đây nó phải dựa vào một con số mà model tự chấm cho mình. Giờ nó dựa vào điểm của
một model khác, không biết LLM nghĩ gì.

### 1.3 Cái giá phải trả, nói thẳng

**`recall@k` trở thành failure mode mới.** Khi LLM nhìn cả 20 trang thì không bao giờ có
chuyện "trượt vì không được nhìn thấy". Truy xuất top-5 thì có thể xếp trang đúng ở hạng 6.

> **Trượt ở tầng truy xuất thì tầng LLM KHÔNG cứu được.**

Kiểm soát bằng ba thứ:
- `k = 5` trên 20 trang là rộng rãi (25% deck)
- Bộ eval 50 câu đo `recall@5` **trực tiếp**; dưới 95% thì nới `k`
- `self_retrieval_check` ở [S6a](../offline/s6-precompute.md) bắt trước từ offline những
  slide có biểu diễn dễ lẫn

---

## 2. Công dụng cụ thể

| Không có R2 (chỉ có fast-path) | Có R2 |
|---|---|
| Chỉ điều hướng được bằng số trang | "quay lại chỗ nói về việc không cần train lại" |
| Khán giả phải nhớ số trang | Khán giả nói theo **ý** và theo **phần** |
| — | Không chắc thì hỏi lại thay vì nhảy bừa |

Câu *"quay lại chỗ nói về việc không cần train lại"* là ví dụ then chốt: cụm đó
**không xuất hiện ở đâu trên slide**. Nó chỉ khớp được với `message` — thứ
[S1](../offline/s1-slide-understanding.md) sinh ra và [S6a](../offline/s6-precompute.md)
embed thành `v_message`.

Và đây là lý do S1 có luật **`message` phải tự đứng được**: nó bị embed một mình, nên
"khắc phục hạn chế vừa nêu" thì vector vô nghĩa và R2 không bao giờ tìm thấy trang đó.

---

## 3. Đường đi

```
query_expanded  (từ R3a — deterministic, ~5ms)
   │
   ├─> [hybrid retrieve]  trên slide_index__{deck}__{model}     ~20–35ms
   │       dense multi-field:  v_message · v_title · v_desc · v_relations
   │       sparse (BM25):      entities + keywords
   │       + v_section (đường mức section, xem §6)
   │       -> top-k = 5
   │
   ├─> [rerank]  bge-reranker-v2-m3                             ~10–25ms
   │       -> top-3 kèm ĐIỂM THẬT
   │
   ├─> [LLM verify + chọn]  trong lần gọi LLM duy nhất
   │       chỉ nhìn 3 ứng viên, không nhìn cả deck
   │       trả về slide_id + lý do
   │
   └─> [confidence gate]  dùng điểm RERANKER, không dùng điểm LLM
```

Tổng thêm **30–60ms**, nhưng prompt ngắn đi ~2k token nên lần gọi LLM nhanh lại tương
đương. **Ròng ≈ hoà.**

### Vì sao multi-field, không gộp một vector

```
"chỗ nói về việc không cần train lại"  -> khớp v_message
"cái sơ đồ ba khối"                     -> khớp v_desc
"BM25"                                  -> khớp sparse
"quay lại phần đánh giá"                -> khớp v_section
```

Gộp tất cả vào một vector thì **làm loãng cả bốn**. Chi tiết dựng index ở
[S6a §2](../offline/s6-precompute.md).

### Tool schema

```json
find_slide(
  slide_id: 7,
  from_candidates: [7, 16, 11],
  why: "message trang 7 nói tách truy xuất khỏi sinh, cập nhật không cần train lại"
)
```

Khác bản trước: LLM **không còn tự khai điểm**. Nó chỉ chọn trong 3 ứng viên đã được
rerank và nói lý do. Điểm đến từ reranker.

`why` có hai công dụng: buộc model đối chiếu thật, và là thứ **hiện lên khi hỏi lại**.

Validate bằng code: `slide_id` phải nằm trong `from_candidates`. Không nằm → model bịa
→ coi như gate không đạt.

---

## 4. Confidence gate ★

```
margin  = rerank_score(top1) − rerank_score(top2)
floor   = rerank_score(top1)

NHẢY khi:     margin >= T_margin  AND  floor >= T_floor
              AND  LLM chọn đúng top1

HỎI LẠI khi:  margin < T_margin           -> 2 thumbnail + why
              hoặc LLM chọn top2 thay vì top1  -> nó thấy gì đó reranker không thấy,
                                                  nhưng chưa đủ để nhảy thẳng
TỪ CHỐI khi:  floor < T_floor             -> "bạn mô tả rõ hơn được không"
```

### Ba kết cục, và cách nói ra

| Kết cục | Robot làm gì |
|---|---|
| **Nhảy** | Render trước, nói sau: *"Đây rồi, trang 7."* |
| **Hỏi lại** | 2 thumbnail cạnh nhau + `why` · **không** nhảy · không đổi state |
| **Từ chối** | *"Mình chưa rõ ý bạn, bạn mô tả thêm được không?"* |

Thumbnail lấy từ `precomputed/thumbs/s{n}.jpg` do [S6b](../offline/s6-precompute.md) sinh.
Không có thumbnail thì câu hỏi lại chỉ có chữ, và khán giả sẽ đoán sai.

### `known_confusable_pairs` — nới gate đúng chỗ

[S7 §4b](../offline/s7-hitl-review.md) cho phép người duyệt đánh dấu cặp trang **trùng chủ
đề thật** (trang 8 "Retriever" và 11 "Chunking" đều xoay quanh truy xuất).

```
top1 và top2 nằm trong known_confusable_pairs
   -> LUÔN hỏi lại, bất kể margin
```

Chấp nhận một cặp là dễ lẫn **không có nghĩa là chấp nhận nhảy sai** — nó có nghĩa là ở
đúng cặp đó, hệ thống luôn hỏi.

---

## 5. Ngưỡng KHÔNG được đoán — phải fit

`T_margin` và `T_floor` **không có giá trị mặc định đúng**. Chúng phụ thuộc reranker, deck,
và cách khán giả nói chuyện.

```
1. Bộ eval R2: 50 câu điều hướng có nhãn trang đúng
   (README xếp việc này TRƯỚC khi code runtime — đây là lý do)
2. Đo recall@5 trước   -> < 95% thì nới k, chưa fit ngưỡng vội
3. Quét T_margin, với mỗi T đo cặp:  harmful_jump_rate  vs  ask_rate
4. Chọn điểm vận hành: harmful_jump < 2%, chấp nhận ask_rate ~15%
```

Bước 2 là bước mới và phải làm **trước**: fit ngưỡng trên một retriever có recall kém thì
chỉ đang tối ưu cách xử lý rác.

Hai chỉ số ở bước 3 đánh đổi ngược chiều. **Không có T nào tối ưu cả hai.** Chọn điểm vận
hành là **quyết định sản phẩm**: buổi quan trọng thì kéo `T_margin` lên (hỏi nhiều hơn,
an toàn hơn), buổi nội bộ thì hạ xuống. Để trong config, **không hardcode**.

### Bộ eval 50 câu gồm gì

| Loại | Số câu | Ví dụ |
|---|---|---|
| Rõ ràng, khớp `title` | 10 | "cho xem lại kiến trúc RAG" |
| Khớp `message`, không khớp chữ trên slide | 15 | "chỗ nói về việc không cần train lại" |
| Mức section | 10 | "quay lại phần đánh giá" |
| **Mơ hồ có chủ ý** (2 trang đều hợp lý) | 10 | "chỗ so sánh hai cách" |
| Không tồn tại trong deck | 5 | "trang nói về giá cả" |

10 câu mơ hồ là phần quan trọng nhất — **nhãn đúng của chúng là "phải hỏi lại"**, không
phải một số trang. Không có nhóm này thì không đo được gate.

---

## 6. Ba loại điều hướng, ba đường khác nhau

| Khán giả nói | Đường | Cách giải |
|---|---|---|
| "trang 12" | [R1](./r1-intake-fastpath.md) fast-path | regex, 5ms |
| "quay lại **phần** đánh giá" | R2 **mức section** | truy xuất trên `v_section` → `sections[].slides[0]` |
| "chỗ nói về việc không cần train lại" | R2 **mức trang** | truy xuất trên `v_message` |

**Loại 2 hay bị bỏ sót.** Khán giả nghĩ theo **phần**, không theo số trang — họ nhớ
"phần đánh giá", không nhớ "trang 14". Không xử riêng thì câu đó rơi vào trang 15 hoặc 16.

Hai đường chạy **cùng một lần truy xuất** (section và slide nằm chung index, khác
`content_type`), rồi code quyết định theo loại của top-1. Không tốn thêm round-trip.

`deck_map.txt` (~150 token) vẫn nằm inline trong prompt để LLM biết deck có mấy phần, tên
gì — cho câu chuyển và câu báo tiến độ. Đó là **trạng thái**, không phải index.

---

## 7. Sau khi quyết định nhảy

```
1. push resume_stack  <- CHỈ khi rời phase "presenting"
2. R6: render(slide_id, build_step = CUỐI)  -> chờ ack
3. nói: "Đây rồi, trang 7."
```

`build_step` khi nhảy tới: **bước cuối cùng** của trang đó. Khán giả muốn xem lại nội dung
đã trình bày, không muốn xem animation chạy lại từ đầu.

Thứ tự **render → ack → nói** là bất biến, chi tiết ở [R6](./r6-state-sync.md).

---

## 8. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| **Trang đúng không lọt top-5** | `recall@5` thấp trên bộ eval | Nới `k`; nếu vẫn thấp thì lỗi ở `message` — xem `self_retrieval` của S6a |
| LLM chọn `slide_id` ngoài `from_candidates` | Validate bằng code | Coi như gate không đạt → hỏi lại |
| Reranker cho điểm phẳng đều | `margin` luôn nhỏ, `ask_rate` vọt lên | Deck có nhiều trang gần giống nhau — kiểm `self_retrieval` trước khi đổ lỗi reranker |
| Query quá ngắn ("cái kia") | Truy xuất trả rác | Đó là việc của [R3a](./r3-context-rewriting.md) — mở rộng query trước khi tới đây |
| Deck có 2 trang gần giống nhau | Gate luôn chặn ở cặp đó | **Đúng, không phải lỗi.** Đưa vào `known_confusable_pairs` |
| Khán giả hỏi trang của deck khác | — | Trả lời bằng **lời** + câu mềm, **KHÔNG điều hướng** |
| Câu vừa điều hướng vừa hỏi nội dung | "quay lại trang kiến trúc và giải thích mũi tên đỏ" | Nhảy trước, trả lời sau — hai tool call trong cùng lượt |

---

## 9. Chỉ số

| Chỉ số | Ngưỡng | Vì sao |
|---|---|---|
| **harmful jump rate** (nhảy sai mà **không** hỏi lại) | **< 2%** | Chỉ số quan trọng nhất của cả R2 |
| **recall@5** (tầng truy xuất) | **≥ 95%** | **Mới.** Trượt ở đây thì LLM không cứu được |
| Top-1 accuracy | báo cáo | Hữu ích để so model, **không** phải mục tiêu tối ưu |
| ask rate | ~15% | Cao quá thì robot nhát, thấp quá thì liều |
| section-level accuracy | báo cáo | Đo riêng vì đây là đường khác |
| MRR sau rerank | báo cáo | Cho ablation |

### Ablation nên chạy

Đây là phần mà thiết kế truy xuất **mua được** so với nhồi prompt — từng thành phần tách ra
đo được:

1. **dense · +sparse · +rerank · +LLM verify** — bốn mức, đo `recall@5` và `Top-1`.
   Chứng minh từng tầng đáng giá bao nhiêu.
2. **gộp một vector vs multi-field** — chứng minh §3.
3. **có gate vs không gate** — `harmful_jump` giảm bao nhiêu, đổi lại `ask_rate` tăng bao nhiêu.
4. **Nhồi prompt (bản cũ) vs truy xuất (bản này)** theo N = 20 / 50 / 100 / 200 —
   tìm điểm giao. Đây là con số trung thực nhất để đưa vào báo cáo.

Ablation 4 đáng chạy kể cả khi kết quả cho thấy nhồi prompt thắng ở N=20: nó xác định
**giới hạn áp dụng** của cả hai, và đó là đóng góp thật.

---

## 10. Cấm

- **Nhồi cả `slide_index` vào prompt** — đó là việc của index
- **Gộp một vector cho cả slide**
- **Dùng điểm LLM tự khai làm confidence gate** khi đã có điểm reranker
- Nhảy khi confidence gate không đạt
- Nhảy ở cặp nằm trong `known_confusable_pairs`
- Đoán `T_margin` thay vì fit trên bộ eval
- Fit ngưỡng trước khi `recall@5` đạt 95%
- Hỏi lại mà không kèm thumbnail
- Coi Top-1 accuracy là mục tiêu tối ưu chính
- Điều hướng sang deck khác
