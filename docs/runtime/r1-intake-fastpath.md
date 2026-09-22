# R1 — Intake & fast-path

**Vào:** text từ form web (QR)
**Ra:** hoặc một action dispatch thẳng xuống [R6](./r6-state-sync.md), hoặc một `Question` vào hàng đợi
**Model:** không có. Regex + một phép embed rẻ.

---

## 1. Vì sao có lớp này

R1 tồn tại vì **hai đặc điểm cấu trúc** của hệ thống mà kiến trúc chatbot thông thường
không có.

### 1.1 Kênh hỏi là nhiều-tới-một, bất đồng bộ

Chatbot là 1:1 và đồng bộ: một người gõ, hệ thống trả lời, người đó đọc rồi gõ tiếp.
Không cần hàng đợi vì bản thân con người **tự điều tiết nhịp**.

Ở đây khán giả gửi câu hỏi qua QR → form web. 30 người có thể bấm gửi trong cùng 2 giây,
và họ **không thấy nhau**. Không ai tự điều tiết. Đây không phải edge case — đây là chế độ
hoạt động bình thường ngay sau một slide gây tranh cãi.

Không có tầng nhận riêng thì:

```
30 câu vào  ->  30 lần gọi LLM  ->  robot trả lời 30 lượt liên tiếp
            ->  buổi thuyết trình chết đứng
```

### 1.2 ~40% lệnh là tầm thường nhưng vẫn tốn 600ms

"trang 12", "tiếp", "quay lại" — không cần model nào để hiểu. Nhưng nếu để chúng đi qua
lần gọi LLM thì mỗi lệnh tốn **400–700ms** thay vì **5ms**.

Đây không phải tối ưu vặt. Nó là khác biệt giữa **robot phản xạ** và **robot suy nghĩ**.
Khán giả nói "tiếp" mà robot đứng hình nửa giây thì cảm giác rất khác so với chuyển ngay.

R1 là một **cache có cấu trúc**: bắt phần traffic tầm thường bằng phương tiện tầm thường,
để dành ngân sách LLM cho phần thực sự cần.

---

## 2. Công dụng cụ thể

| Không có R1 | Có R1 |
|---|---|
| 30 câu hỏi = 30 lượt trả lời | Khử trùng còn ~8, xếp ưu tiên theo số người hỏi |
| "tiếp" tốn 600ms | 5ms |
| Một người spam phá được cả buổi | Rate limit theo session |
| Câu hỏi resolve theo trang **lúc xử lý** | Resolve theo trang **lúc gửi** (xem §3.1) |
| Robot trả lời câu troll rồi mới từ chối | Bỏ qua im lặng |

---

## 3. Việc 1 — Admission

### 3.1 `Question` object

```json
{
  "qid": "q_0142",
  "text": "cái mũi tên đỏ kia để làm gì",
  "text_norm": "cai mui ten do kia de lam gi",
  "session_token": "tok_9f2a",
  "at_slide": 7,
  "at_step": 2,
  "received_at": 1699000000,
  "dup_of": null,
  "dup_count": 1
}
```

**`at_slide` phải chụp lúc NHẬN, không phải lúc xử lý.**

Đây là chi tiết dễ bỏ sót nhất và hậu quả rất khó debug. Khán giả hỏi ở trang 7; robot
xử lý xong thì đã sang trang 8. "Cái mũi tên đỏ kia" phải resolve theo **trang 7** — thứ
người đó đang nhìn lúc gõ.

Không lưu `at_slide` thì [R3](./r3-context-rewriting.md) giải sai tiền ngữ, và lỗi chỉ
xuất hiện khi có độ trễ — nghĩa là **không tái hiện được trên máy dev**.

### 3.2 Khử trùng — hai tầng

| Tầng | Cách | Chi phí | Bắt được |
|---|---|---|---|
| Rẻ | normalize (lowercase, bỏ dấu câu, bỏ dấu thanh) → so chuỗi | ~0 | câu gõ giống hệt |
| Đủ | embed `bge-m3` (đã nạp sẵn cho KB) → cosine > **0.9** với các câu đang chờ | ~10ms | cùng ý, khác chữ |

Ngưỡng 0.9 cố tình **cao hơn** ngưỡng `qa_cache` (0.88). Gộp nhầm hai câu hỏi khác nhau
thì một người không được trả lời và **không hiểu vì sao**.

**Câu trùng không vứt — đếm.** `dup_count` có hai công dụng:

1. **Xếp ưu tiên hàng đợi:** 5 người cùng hỏi thì câu đó lên đầu
2. **Robot nói được:** *"Có mấy bạn cùng hỏi ý này nên mình trả lời luôn"* — nghe rất tự
   nhiên, và là sự thật

### 3.3 Rate limit

`1 câu / 30s / session_token`. `session_token` sinh từ link QR, ẩn danh nhưng phân biệt
được người gửi.

Không có thì một người phá được cả buổi, và không có cách nào chặn vì kênh là ẩn danh.

---

## 4. Việc 2 — Fast-path

### 4.1 Bảng mẫu

| Mẫu | Action |
|---|---|
| `trang 12` · `slide 12` · `sang trang 12` · `trang mười hai` | `goto_slide(12)` |
| `tiếp` · `next` · `trang sau` · `tiếp tục` | `advance()` |
| `quay lại` · `back` · `trang trước` | `back()` |
| `về đầu` · `trang cuối` | `goto_slide(1)` / `goto_slide(N)` |
| `dừng` · `tạm dừng` · `im lặng` | `pause()` |

### 4.2 Ba chi tiết tiếng Việt bắt buộc phải xử

**a. Người ta gõ không dấu.** `quay lai trang 12`, `tiep tuc`, `trang truoc`.
Khớp regex trên bản **đã bỏ dấu thanh** (`text_norm`), giữ `text` gốc để log và để
hiển thị lên màn hình.

**b. Số viết bằng chữ.** `trang mười hai`, `trang bảy`, `trang hai mươi`.
Cần bảng số 1–99. Không nhiều, và không có thì hụt một mảng lệnh tự nhiên.

**c. Typo và pha tiếng Anh.** `tiếp đi`, `next slide`, `qua trang sau`, `back lại`.

> **Đừng cố bắt hết.** Bắt trượt thì rơi xuống LLM — vẫn đúng, chỉ chậm hơn 600ms.
> **Bắt nhầm mới là thảm hoạ.**

Đây là nguyên tắc thiết kế của cả lớp: R1 tối ưu cho **precision**, không phải recall.

### 4.3 Hai bẫy logic

**`goto_slide(12)` là số trang KHÁN GIẢ NHÌN THẤY, không phải index mảng.**

Nếu S0 lọc hidden slide đúng thì hai con số này trùng nhau. S0 làm sai thì lỗi không hiện
ra ở S0 — nó hiện ra **ở đây, giữa buổi thuyết trình**, khi khán giả nói "trang 15" và
robot nhảy sang trang khác. Đây là lý do luật "lọc hidden slide" ở
[S0](../offline/s0-ingest.md#L46) thực chất là luật của runtime.

**`tiếp` khi đang ở giữa trang nghĩa là build_step tiếp theo, không phải trang tiếp theo.**

```
đang ở slide 7, step 2/3   ->  "tiếp"  ->  slide 7, step 3      ĐÚNG
                           ->  "tiếp"  ->  slide 8, step 1      SAI, bỏ qua 1/3 nội dung
```

Rất dễ code sai vì `advance()` nghe như "sang trang".

### 4.4 Cấm

**Fast-path chỉ được bắt điều hướng tường minh. Cấm bắt câu hỏi nội dung.**

Ham một chút là có ngày `"quay lại chỗ nói về việc train lại"` khớp mẫu `quay lại` và
nhảy về trang trước — trong khi đó là một câu hỏi điều hướng ngữ nghĩa thuộc
[R2](./r2-navigation.md).

Quy tắc an toàn: mẫu regex phải **neo vào đầu chuỗi** và **giới hạn độ dài** (lệnh điều
hướng thật hầu như luôn dưới 5 từ). Câu dài hơn → đẩy xuống LLM.

---

## 5. Luồng

```
text vào
  │
  ├─> normalize -> text_norm
  │
  ├─> rate limit check ──(vượt)──> bỏ im lặng, không báo lỗi ra màn hình chính
  │
  ├─> fast-path regex ──(khớp)──> action ──> R6 ngay lập tức      [~5ms]
  │
  └─(không khớp)
      ├─> khử trùng ──(trùng)──> dup_count++ trên câu đã có, dừng
      │
      └─> push vào queue ──> R7 quyết định khi nào lấy ra
```

Lưu ý: **fast-path không đi qua hàng đợi.** Lệnh điều hướng tường minh được thực thi ngay,
vì nó là yêu cầu thay đổi thứ khán giả đang nhìn — đợi là vô nghĩa.

---

## 6. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| Regex bắt nhầm câu hỏi nội dung | Robot nhảy trang khi được hỏi | Neo đầu chuỗi + giới hạn độ dài; đo false positive rate |
| Khử trùng gộp nhầm 2 câu khác nhau | Có người không được trả lời | Nâng ngưỡng lên 0.92; log cặp bị gộp để review sau buổi |
| Hàng đợi phình không giới hạn | Câu hỏi chờ > 5 phút | Trần hàng đợi (20), câu cũ nhất bị drop và **báo lên màn hình vận hành** |
| Người dùng gửi lại vì tưởng trượt | `dup_count` cao bất thường từ cùng một `session_token` | Thiếu phản hồi thị giác — xem [R7 §5](./r7-interrupt-turntaking.md) |
| Số trang vượt phạm vi (`trang 99`) | — | Không dispatch; coi như câu hỏi, đẩy xuống LLM để nó nói "deck chỉ có 20 trang" |

---

## 7. Chỉ số

| Chỉ số | Ngưỡng | Vì sao |
|---|---|---|
| fast-path hit rate | ~40% | Đo phần tiết kiệm được |
| **fast-path false positive rate** | **≈ 0** | **Đây mới là con số cần canh.** Hit rate chỉ là tiền thưởng |
| tỉ lệ khử trùng | báo cáo | Cao bất thường → thiếu phản hồi thị giác cho người gửi |
| thời gian chờ p95 của câu trong hàng đợi | < 90s | Dài hơn thì khán giả quên mất mình đã hỏi gì |

Đo false positive bằng chính **bộ eval 50 câu điều hướng** của R2: chạy toàn bộ qua R1
trước, đếm số câu đáng lẽ phải xuống LLM mà bị regex chặn.

---

## 8. Cấm

- Fast-path bắt câu hỏi nội dung
- Bỏ `at_slide` lúc nhận, để R3 tự suy từ state hiện tại
- Vứt câu trùng thay vì đếm
- Đọc to câu hỏi troll rồi mới từ chối
- Cho lệnh điều hướng tường minh đi qua hàng đợi
