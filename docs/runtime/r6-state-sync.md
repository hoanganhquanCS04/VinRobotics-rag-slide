# R6 — Presentation state machine & sync

**Vào:** action từ R1 / R2 / R4 / R7
**Ra:** lệnh render + cập nhật state
**Model:** không có. Máy trạng thái thuần.

---

## 1. Vì sao có lớp này

### 1.1 Hai nguồn chân lý = lỗi tệ nhất trong cả hệ thống

Có đúng một câu hỏi mà hệ thống phải luôn trả lời đúng: **"đang ở trang nào?"**

Nếu orchestrator nghĩ trang 8 còn màn hình đang ở trang 7 thì robot mô tả một thứ khán giả
không nhìn thấy. Lỗi này:

- **Cả hội trường thấy ngay lập tức**
- **Không tự phục hồi** — mỗi lệnh tiếp theo càng lệch thêm
- **Không tái hiện được trên máy dev**, vì nó chỉ xảy ra khi renderer chậm hoặc mất gói

Cách duy nhất chống được là **không bao giờ có hai nguồn**:

> **Orchestrator là nguồn chân lý duy nhất về state. Renderer phải ngu.**

Renderer nhận lệnh, vẽ, trả ack. Nó **không** giữ state riêng, **không** tự chạy animation
theo timer, **không** tự quyết trang tiếp theo. Mọi cám dỗ kiểu "cho renderer tự advance
cho mượt" đều dẫn thẳng tới lớp lỗi ở trên.

### 1.2 Vòng thuyết trình cần một máy trạng thái thật

Buổi thuyết trình không phải một chuỗi câu hỏi-trả lời. Nó có **trạng thái kéo dài**: đang
nói dở câu 2 của bước 3 trang 7, đã đi qua 7 trang, còn 18 phút, và có một điểm cần quay
về sau khi lạc đề.

Không mô hình hoá rõ thì "quay lại chỗ đang dở" trở thành đoán mò.

---

## 2. Công dụng cụ thể

| Không có R6 | Có R6 |
|---|---|
| Robot nói trang 8, màn hình ở trang 7 | Không bao giờ lệch |
| Renderer chết → hệ thống treo | Suy biến có kiểm soát, robot nói tiếp bằng lời |
| Lạc đề xong không biết về đâu | `resume_stack` |
| Quay về phát lại cả trang từ đầu | Về đúng `build_step` + đúng câu |

---

## 3. Máy trạng thái

```
presenting ──hỏi nội dung──> answering ──xong──> presenting
     │                            │
     │                            └──cần nhảy──> navigating ──> answering
     ├──điều hướng──> navigating ──ack──> presenting
     ├──pause──> paused ──resume──> presenting
     └──escalate──> escalated ──người xử lý xong──> presenting
```

| Phase | Nghĩa | Ngắt được không |
|---|---|---|
| `presenting` | Đang đọc kịch bản | Có, ở ranh giới câu |
| `answering` | Đang trả lời câu hỏi | Chỉ điều hướng ngắt được |
| `navigating` | Đang chờ ack sau lệnh render | **Không** — giai đoạn nguy hiểm, xem §5 |
| `paused` | Dừng theo yêu cầu | Mọi thứ xử lý ngay |
| `escalated` | Chờ người thật | Mọi thứ vào hàng đợi |

---

## 4. `resume_stack`

### Push khi nào

> **Chỉ push khi rời `presenting` để đi `navigating`.**

Hỏi đáp tại chỗ **không push** — trả lời xong là nói tiếp, không có gì để "quay lại".
Push nhầm ở đây thì robot nói *"quay lại chỗ mình đang dở"* sau mỗi câu hỏi, nghe rất ngớ ngẩn.

### Trần độ sâu = 2

Khán giả nhảy 7 → 12 → 3 → 18 thì **đừng cố nhớ hết**. Giữ điểm gốc và điểm gần nhất.

Stack sâu hơn dẫn tới robot nói *"quay lại chỗ mình đang dở"* ba lần liên tiếp — khán giả
không theo được, và bản thân robot nghe như đang lạc.

### Ba chi tiết của resume

```
1. NÓI RA MIỆNG
   "Mình quay lại phần Hybrid search đang dở nhé."
   -> lấy TÊN SECTION từ DeckStructure, KHÔNG nói "quay lại trang 12"

2. Về đúng BUILD_STEP
   -> không chạy lại animation khán giả đã xem

3. Về đúng CÂU (sentence_id)
   -> không phát lại từ câu 1 của trang
```

**Vì sao phải nói ra miệng:** nhảy lặng lẽ về trang cũ thì khán giả mất dấu hoàn toàn — họ
vừa nhìn trang 5, giờ màn hình về trang 12 mà không ai giải thích. Một câu 8 chữ giải quyết.

**Vì sao nói tên section chứ không nói số trang:** khán giả không nghĩ theo số trang. Họ
nhớ "phần Hybrid search". Đây là chỗ `sections[].title` của
[S2](../offline/s2-deck-structure.md) trả cổ tức.

Cả ba chi tiết là lý do `sentence_id` và `build_step` phải nằm trong state, và là lý do
[S4](../offline/s4-scenario.md) chia kịch bản tới mức câu.

---

## 5. Hợp đồng renderer

```
orchestrator ──render(slide_id, build_step)──> renderer
             <──ack{slide_id, build_step, ts}──

không ack trong 500ms  ->  retry 1 lần
vẫn không ack          ->  KHÔNG cập nhật state, vào chế độ suy biến
```

### Thứ tự bất biến

> **lệnh hình → ack → lời nói.**

Nói trước khi ack là có ngày robot mô tả trang 8 trong lúc màn hình còn ở trang 7.

Thứ tự này cũng là một **lớp che latency**: hành động thị giác xảy ra trước, và não khán
giả tính đó là "đã phản hồi" ngay cả khi lời nói còn 800ms nữa mới tới.

### Ack phải mang theo nội dung, không chỉ là tín hiệu

`ack{slide_id, build_step}` — orchestrator **so khớp** với lệnh đã gửi. Ack rỗng kiểu
`{ok: true}` không phát hiện được trường hợp renderer vẽ nhầm trang.

### Chế độ suy biến (renderer chết)

```
robot NÓI TIẾP bằng lời
KHÔNG cập nhật slide_id
báo lỗi ra màn hình vận hành
```

**Im lặng là lựa chọn tệ nhất.** Khán giả không biết chuyện gì xảy ra, và người vận hành
cũng không.

Không cập nhật `slide_id` là quan trọng: state phải phản ánh **thứ đang hiện trên màn
hình**, không phải thứ ta muốn hiện. Cập nhật lạc quan thì khi renderer sống lại, hai bên
lệch nhau vĩnh viễn.

---

## 6. Vòng thuyết trình

```
for slide in deck:
    for step in slide.steps:
        render(slide, step) -> chờ ack
        for sentence in step.sentences:
            phát audio (precomputed)
            ── sau MỖI câu: hỏi R7 "có được ngắt không?"
                 └─(có)─> xử lý, rồi resume về đúng câu này
```

Kiểm tra ngắt **sau mỗi câu**, không phải sau mỗi trang và không phải liên tục. Đây là
điểm dừng sạch duy nhất, và là lý do S4/S6 làm việc ở mức câu.

`elapsed_sec` cập nhật theo `duration_ms` **thật** của file audio (S6 đã đo), không theo
ước lượng âm tiết của S4. Nhờ vậy câu *"còn khoảng 18 phút"* mới đúng.

---

## 7. State object

```json
{
  "deck_id": "rag-intro",
  "slide_id": 7, "build_step": 2, "sentence_id": "s7.2.1",
  "phase": "presenting",

  "resume_stack": [{"slide_id": 7, "build_step": 2, "sentence_id": "s7.2.1"}],
  "visited": [1,2,3,4,5,6,7],
  "elapsed_sec": 640,
  "section_id": "sec3",

  "queue": [...],
  "history": [...],

  "renderer_ack": {"slide_id": 7, "build_step": 2, "at": 1699000000}
}
```

`renderer_ack` giữ riêng để **so khớp được** với `slide_id`. Hai trường này lệch nhau
quá 1 giây → đó là một `desync event`, phải log.

---

## 8. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| Renderer chết giữa buổi | Không ack sau 2 lần | §5 chế độ suy biến |
| Renderer sống lại sau khi chết | ack tới muộn cho lệnh cũ | Bỏ qua ack có `ts` cũ hơn lệnh hiện tại; gửi lại lệnh hiện tại |
| Ack về đúng nhưng vẽ sai trang | `ack.slide_id` khác lệnh | Retry; lặp lại 2 lần → suy biến |
| `resume_stack` đầy | Khán giả nhảy liên tục | Trần 2, đẩy cái cũ nhất ra |
| Resume vào trang đã bị sửa (incremental build giữa buổi) | `sentence_id` không tồn tại | Rơi về đầu `build_step` đó, vẫn nói ra miệng |
| `elapsed_sec` trôi so với thực tế | Câu "còn 18 phút" sai | Dùng `duration_ms` thật, không dùng ước lượng |

---

## 9. Chỉ số

| Chỉ số | Ngưỡng | Vì sao |
|---|---|---|
| **desync events** | **0** | State ≠ ack quá 1s. Lỗi nghiêm trọng nhất của runtime |
| ack p95 | < 200ms | Vượt 500ms là vào đường retry, cảm nhận được ngay |
| Số lần vào chế độ suy biến | 0 | Mỗi lần là một sự cố cần điều tra |
| Độ chính xác của `elapsed_sec` | lệch < 30s cuối buổi | Ảnh hưởng câu báo tiến độ |

---

## 10. Cấm

- Renderer giữ state riêng
- Renderer tự chạy animation theo timer
- Renderer tự quyết trang tiếp theo
- Nói trước khi nhận ack
- Cập nhật `slide_id` khi chưa có ack
- Resume lặng lẽ, không nói ra miệng
- Resume về đầu trang thay vì về đúng `build_step` + câu
- Ack rỗng kiểu `{ok: true}`
