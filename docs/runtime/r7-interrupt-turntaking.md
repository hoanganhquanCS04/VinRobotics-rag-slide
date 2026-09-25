# R7 — Interrupt & turn-taking

**Vào:** hàng đợi câu hỏi + `phase` hiện tại
**Ra:** quyết định *khi nào* lấy câu nào ra xử lý
**Model:** không có. Chính sách thuần.

Đây là lớp duy nhất **không nằm trên đường đi của một lượt** — nó quyết định *khi nào*
đường đi được kích hoạt.

---

## 1. Vì sao có lớp này

### 1.1 Không có chính sách tường minh thì chính sách ngầm là "ai đến trước phục vụ trước"

Và chính sách ngầm đó phá buổi thuyết trình:

```
Trang 7 còn 2 câu nữa là hết ý
  -> câu hỏi vào
  -> trả lời ngay
  -> mạch trình bày vỡ, quay lại nói nốt 2 câu thì khán giả đã quên đang nói gì
```

Ngắt là hành vi **có chi phí**, và chi phí đó khác nhau tuỳ thời điểm và tuỳ loại việc.
Phải quyết định tường minh, không để mặc thứ tự tới.

### 1.2 Kênh text không có backchannel

Đây là điểm mà **phạm vi v1 (text qua QR form, không ASR)** làm bài toán *khác* chứ không
*dễ hơn*:

| | Voice | Text qua form |
|---|---|---|
| Người hỏi biết mình đã được nghe | Robot dừng lại → biết ngay | **Không biết gì cả** |
| Overlapping speech | Có, phải xử lý | Không có |
| Endpointing | Có | Không có |
| Nhiều người hỏi cùng lúc | Hiếm (họ nghe thấy nhau) | **Thường xuyên (họ không thấy nhau)** |

Nửa nội dung kinh điển của turn-taking (endpointing, overlap) **bốc hơi**. Nửa còn lại
(ai được nói, khi nào) **nặng hơn**, vì không ai tự điều tiết.

Và xuất hiện một bài toán mới không có trong voice: **người gửi không biết câu hỏi có tới
không** — xem §5.

> Nếu về sau mở ASR thì R7 phình lại đúng nghĩa gốc của turn-taking. Cứ giữ slot.

---

## 2. Công dụng cụ thể

| Không có R7 | Có R7 |
|---|---|
| Trả lời rời rạc giữa trang, mạch vỡ | Gom về cuối trang |
| 8 câu hỏi = 8 lượt trả lời liên tiếp | Gom, khử trùng, xếp ưu tiên |
| Khán giả gửi lại 3 lần vì tưởng trượt | Phản hồi thị giác ngay |
| Câu hỏi chờ 5 phút rồi mới được trả lời | Trần chờ + báo cho người vận hành |

---

## 3. Ma trận ngắt ★

> **Quyết định đã chốt.**

| Robot đang | Việc đến | Xử lý |
|---|---|---|
| `presenting` | **điều hướng** | **Ngắt ngay** ở ranh giới câu |
| `presenting` | **hỏi nội dung** | **Đợi hết trang** — trừ khi hàng đợi > 3 |
| `presenting` | meta ("nói chậm lại", "to lên") | Áp dụng ngay, **không ngắt lời** |
| `answering` | câu hỏi mới | Vào hàng đợi, **không** ngắt |
| `answering` | **điều hướng** | **Ngắt ngay** |
| `navigating` | bất cứ gì | Đợi ack xong đã |
| `paused` | mọi thứ | Xử lý ngay |
| `escalated` | mọi thứ | Vào hàng đợi |

### Vì sao điều hướng ngắt ngay, hỏi nội dung thì không

**Điều hướng là yêu cầu thay đổi thứ khán giả ĐANG NHÌN.** Đợi là vô nghĩa — họ muốn xem
lại trang kia *bây giờ*, không phải sau 40 giây nữa.

**Hỏi nội dung thì khác:** câu trả lời vẫn đúng sau 40 giây, còn mạch trình bày thì vỡ
ngay lập tức nếu ngắt. Và trang chỉ còn vài câu nữa là hết.

Ngoại lệ `hàng đợi > 3`: khi đã có 4 câu chờ thì việc "giữ mạch" thua việc "đừng để khán
giả chờ quá lâu". Ngưỡng này để trong config.

### Meta áp dụng ngay nhưng không ngắt lời

"Nói chậm lại" → đổi tốc độ TTS **từ câu tiếp theo**, không dừng câu đang nói. Ngắt lời để
nói "vâng em nói chậm lại ạ" rồi nói tiếp là buồn cười.

---

## 4. Điểm kiểm tra ngắt

```
vòng thuyết trình:
   phát câu ──> hết câu ──> HỎI R7 ──> tiếp câu sau / ngắt
```

**Sau mỗi câu, không phải liên tục và không phải sau mỗi trang.**

- Liên tục → phải cắt giữa câu, nghe như mất điện
- Sau mỗi trang → chờ quá lâu, có trang dài 90 giây

Đây là điểm dừng sạch duy nhất, và là lý do [S4](../offline/s4-scenario.md) chia kịch bản
tới mức câu và S6 cache TTS theo câu.

Ở cuối `build_step` và cuối trang có thêm hai điểm kiểm tra "mạnh hơn" — đây là chỗ câu
hỏi nội dung đang chờ được lấy ra.

---

## 5. Phản hồi thị giác — bù cho kênh thiếu backchannel ★

Khán giả gửi câu hỏi qua form rồi **không biết nó có tới không**. Không bù thì họ gửi lại
3 lần, và hàng đợi đầy câu trùng.

Ba chỗ phải có phản hồi:

```
Trên điện thoại người gửi (ngay lập tức):
    "Đã nhận câu hỏi của bạn · đang có 3 câu trước bạn"

Trên màn hình trình chiếu (góc nhỏ, không che nội dung):
    💬 3 câu hỏi đang chờ

Khi bắt đầu trả lời (trên màn hình):
    "Đang trả lời: cái mũi tên đỏ kia để làm gì..."
```

Dòng thứ ba có công dụng phụ quan trọng: **khán giả biết câu của mình đang được trả lời**,
nên không hỏi lại. Và cả hội trường biết robot đang trả lời ai, thay vì bỗng dưng nói về
một chủ đề không ai thấy có người hỏi.

`dup_count` từ [R1](./r1-intake-fastpath.md) cũng nói ra được:
*"Có mấy bạn cùng hỏi ý này nên mình trả lời luôn."*

---

## 6. Xếp thứ tự hàng đợi

Không phải FIFO thuần:

```
điểm ưu tiên = dup_count * w1  +  độ_cũ * w2  +  (câu hỏi về trang hiện tại ? w3 : 0)
```

| Thành phần | Vì sao |
|---|---|
| `dup_count` | 5 người cùng hỏi thì đáng trả lời trước 1 người |
| Độ cũ | Chống đói: câu cũ phải lên dần, không bị chôn mãi |
| Về trang hiện tại | Trả lời khi trang còn trên màn hình thì khán giả theo được; sang trang khác rồi thì mất ngữ cảnh |

**Trần hàng đợi = 20.** Vượt thì câu cũ nhất bị drop và **báo lên màn hình vận hành** —
không im lặng vứt.

**Trần thời gian chờ = 90 giây.** Lâu hơn thì chính người hỏi cũng quên mình hỏi gì.
Quá hạn → hoặc trả lời ngay, hoặc gửi lời xin lỗi về điện thoại người đó.

---

## 7. Barge-in

Khán giả gửi câu thứ hai khi robot đang trả lời câu thứ nhất.

```
câu hỏi mới       ->  vào hàng đợi, KHÔNG ngắt
điều hướng        ->  ngắt ngay: cancel token -> fade 80ms -> xử lý
```

Yêu cầu kỹ thuật nằm ở [R5](./r5-streaming-speech.md): mọi tầng phải huỷ được, và `play`
phải huỷ được **giữa file**, không chỉ giữa các câu.

Sau khi bị ngắt giữa câu trả lời: **không** quay lại nói nốt câu trả lời dở. Câu hỏi đó
quay lại hàng đợi với `dup_count` giữ nguyên, hoặc bỏ nếu người hỏi chính là người vừa
điều hướng.

---

## 8. Chống phá

```
rate limit 1 câu / 30s / session_token                    <- R1
câu vô nghĩa (score thấp ở MỌI tool) -> meta_action("skip")
```

> **Robot KHÔNG được đọc to câu hỏi troll rồi mới từ chối. Đọc lên là troll thành công.**

Bỏ qua im lặng. Không hiện lên màn hình, không phản hồi. Người gửi thấy "đã nhận" trên
điện thoại là đủ — không cần biết nó bị bỏ.

---

## 9. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| Hàng đợi không bao giờ vơi | Trang dài, ngưỡng `>3` không kích hoạt | Hạ ngưỡng hoặc chèn điểm kiểm tra giữa trang dài |
| Câu hỏi hay bị bỏ vì quá hạn | Nhiều câu chạm trần 90s | Tăng tần suất điểm kiểm tra, hoặc dành hẳn slot Q&A cuối phần |
| Khán giả spam gửi lại | `dup_count` cao từ cùng `session_token` | Thiếu phản hồi thị giác — §5 |
| Ngắt liên tục, không thuyết trình được | Nhiều lệnh điều hướng dồn dập | Gộp: nhiều lệnh điều hướng trong 2s → chỉ thực hiện cái cuối |
| Trả lời câu hỏi về trang đã qua từ lâu | Ngữ cảnh mất | Nói rõ: *"Câu này hỏi về trang 5 nhé"* + nhảy về nếu cần |

---

## 10. Chỉ số

| Chỉ số | Ngưỡng | Vì sao |
|---|---|---|
| Thời gian chờ p95 của câu hỏi | < 90s | Lâu hơn thì người hỏi quên |
| Tỉ lệ câu bị drop | < 5% | Cao hơn là hàng đợi thiết kế sai |
| Số lần ngắt / buổi | báo cáo | Quá nhiều → mạch vỡ; quá ít → khán giả nản |
| Tỉ lệ gửi lại (cùng người, cùng ý) | < 10% | Đo hiệu quả của phản hồi thị giác §5 |

Chỉ số cuối là cách duy nhất biết §5 có hoạt động không — nó đo **cảm giác của người gửi**,
thứ không log trực tiếp được.

---

## 11. Cấm

- Để chính sách ngắt là ngầm định "ai đến trước phục vụ trước"
- Ngắt giữa câu (trừ khi là điều hướng, và phải fade)
- Đọc to câu hỏi troll rồi mới từ chối
- Vứt câu hỏi quá hạn mà không báo cho ai
- Ngắt lời để xác nhận một lệnh meta
- FIFO thuần, bỏ qua `dup_count`
