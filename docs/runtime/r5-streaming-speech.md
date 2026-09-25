# R5 — Streaming speech

**Vào:** token stream từ generate (hoặc câu đã có sẵn từ `qa_cache` / kịch bản)
**Ra:** audio
**Model:** TTS

---

## 1. Vì sao có lớp này

### 1.1 Lớp này tồn tại thuần tuý để đổi latency lấy pipelining

Không có gì "thông minh" trong R5. Nó tồn tại vì một phép tính:

```
KHÔNG streaming:
  generate xong toàn bộ (2–3s)  ->  TTS toàn bộ (1s)  ->  phát
  = 3–4s tới byte audio đầu tiên      THỦNG ngân sách 2.5s

CÓ streaming:
  generate câu 1 (0.3s) -> TTS câu 1 (0.3s) -> phát
                            └ trong lúc đó câu 2 đang sinh và synth
  = 0.6s tới byte audio đầu tiên
```

Tổng thời gian xử lý **không đổi**. Chỉ có thứ tự thay đổi. Nhưng khán giả không đo tổng
thời gian — họ đo **khoảng im lặng đầu tiên**.

Đây là đòn bẩy latency lớn nhất trong toàn bộ runtime: **+2–3 giây nếu làm sai**, nhiều
hơn cả chi phí của lần gọi LLM.

### 1.2 Và nó là điều kiện cần của barge-in

Phát audio theo câu cũng chính là thứ cho phép **dừng giữa chừng sạch sẽ**. Synth cả khối
rồi phát thì muốn dừng phải cắt giữa file audio — nghe như mất điện.

Nói cách khác R5 phục vụ hai lớp: ngân sách latency (mục 1.1) và
[R7](./r7-interrupt-turntaking.md) (ngắt lời).

---

## 2. Công dụng cụ thể

| Không có R5 | Có R5 |
|---|---|
| 3–4s im lặng trước mỗi câu trả lời | 0.6s |
| Không ngắt lời được giữa chừng | Dừng sạch ở ranh giới câu |
| Cache TTS theo cả đoạn → sửa 1 câu synth lại hết | Cache theo câu, reuse tối đa |

---

## 3. Đường ống

```
token stream ──> buffer ──> cắt câu ──> hàng TTS (trần 2 câu) ──> phát
                               │
                    câu 1 đang PHÁT
                    câu 2 đang SYNTH
                    câu 3 đang SINH
```

Ba giai đoạn chạy chồng nhau. Hàng TTS **có trần 2 câu lookahead**: synth trước 5 câu rồi
bị huỷ vì barge-in là đốt tiền vô ích.

---

## 4. Cắt câu — bẫy dấu chấm

Cắt ở `. ? !` là đúng 95% trường hợp. 5% còn lại vấp:

```
0.88          ->  cắt thành "không" / "88"
Fig. 3        ->  cắt sau "Fig"
v.v.          ->  cắt hai lần
TS. Nguyễn    ->  cắt sau "TS"
1.5 giây      ->  cắt giữa số
```

Hai lớp phòng thủ:

**Lớp 1 — luật cắt:**
- Bảng abbreviation: `TS.` `PGS.` `GS.` `Fig.` `v.v.` `vd.` `tr.` `et al.`
- **Dấu chấm giữa hai chữ số không phải kết câu**
- Dấu chấm phải theo sau bởi khoảng trắng + chữ hoa (hoặc hết stream)

**Lớp 2 — ép ở nguồn, quan trọng hơn:**

> Ghi vào prompt: **"Không viết số thập phân trong lời nói. Viết 'không phẩy tám tám',
> không viết '0.88'."**

Lợi kép: vừa tránh cắt sai, vừa để TTS đọc đúng. TTS đọc "0.88" ra "không chấm tám tám"
hoặc "zero point eight eight" tuỳ engine — cả hai đều sai tiếng Việt.

---

## 5. Thủ thuật: ép câu đầu ngắn ★

Byte audio đầu tiên đến khi **câu đầu tiên đủ chữ để cắt**. Câu đầu 30 âm tiết thì phải
chờ sinh hết 30 âm tiết mới bắt đầu synth được.

```
Thêm vào prompt: "Câu đầu tiên phải ngắn, dưới 12 âm tiết."
```

Rẻ, không tốn gì, ăn thẳng **200–300ms**. Và tự nhiên nữa — người thật cũng mở đầu ngắn:

```
"Câu này thì thế này."      -> rồi mới vào nội dung
"Đúng rồi, ý bạn chính xác." -> rồi mới giải thích
```

Đây cũng là lý do filler prerecorded hoạt động tốt: bộ não khán giả tính tiếng nói đầu tiên
là "đã phản hồi", không quan tâm nó chứa bao nhiêu thông tin.

---

## 6. Huỷ được ở mọi tầng

Barge-in đòi hỏi **generate huỷ được, TTS huỷ được, phát huỷ được**. Nghĩa là:

> Không `await` tới hết ở bất kỳ tầng nào. Mọi thứ chạy dưới một **cancel token**.

```python
async def speak(stream, cancel: CancelToken):
    async for sentence in split_sentences(stream, cancel):
        if cancel.is_set(): break
        audio = await tts(sentence, cancel)
        if cancel.is_set(): break
        await play(audio, cancel)          # play cũng phải huỷ được giữa file
```

Chi tiết dễ quên: **`play` cũng phải huỷ được giữa file**, không chỉ giữa các câu. Câu
12 giây mà chỉ dừng được ở cuối câu thì barge-in vô nghĩa.

Khi huỷ: **fade out ~80ms**, đừng cắt cụp. Cắt đột ngột nghe như lỗi kỹ thuật; fade ngắn
nghe như người ta ngừng lời.

---

## 7. Hai nguồn audio, một đường phát

| Nguồn | Khi nào | Latency |
|---|---|---|
| **Precomputed** (`precomputed/tts/{hash}.mp3`) | Kịch bản chính + `qa_cache` hit | ~0 |
| **Streaming TTS** | Câu trả lời sinh tại chỗ | 200–400ms/câu |

Cả hai đi qua **cùng một hàng phát** để trạng thái "đang nói câu nào" là một. Hai đường
phát riêng thì barge-in phải xử lý hai chỗ, và sớm muộn quên một chỗ.

`tts_hash` của [S4](../offline/s4-scenario.md)/S6 và hash
dùng lúc runtime phải **cùng một hàm** — lệch thì cache không bao giờ hit và không ai
nhận ra, chỉ thấy hoá đơn TTS cao.

---

## 8. Khoảng nghỉ giữa các câu

Nhỏ nhưng ảnh hưởng lớn tới cảm giác tự nhiên:

```
giữa hai câu trong cùng ý:   ~150ms
giữa hai ý / sang trang:     ~400ms
sau câu hỏi lại:             ~600ms  (chờ khán giả phản ứng)
```

Nghỉ 0ms nghe như máy đọc. Nghỉ đều nhau cũng nghe như máy đọc. Khoảng nghỉ nên **lấy từ
cấu trúc** — hết `build_step` thì nghỉ dài hơn hết câu.

---

## 9. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| **Underrun** (hụt tiếng giữa chừng) | Audio đứt quãng | TTS chậm hơn tốc độ phát → tăng lookahead lên 3, hoặc đổi engine |
| TTS provider timeout | Im lặng | Fallback giọng local kém hơn. **Tuyệt đối không im lặng** |
| Cắt câu sai ở số thập phân | TTS đọc kỳ quặc | Lớp 2 ở §4 — ép ở nguồn |
| Cache không bao giờ hit | Hoá đơn TTS cao bất thường | Hàm hash runtime lệch với S6 |
| Huỷ xong vẫn phát nốt 1 câu | `play` không nhận cancel | §6 |
| Câu quá dài (>40 âm tiết) | Không ngắt lời được trong 12s | Đây là lỗi [S4](../offline/s4-scenario.md) — siết `max_syllables` xuống 30 |

---

## 10. Chỉ số

| Chỉ số | Ngưỡng | Vì sao |
|---|---|---|
| **TTFB** (time to first byte audio) | P95 < 2.5s | Gate của cả hệ thống |
| **Underrun count** | **0** | **Quan trọng hơn TTFB.** Hụt tiếng giữa câu nghe tệ hơn chờ thêm 0.5s |
| Cache hit rate | > 85% trong buổi | Dưới ngưỡng → hash lệch hoặc kịch bản sinh lại quá nhiều |
| Thời gian từ lệnh huỷ tới im lặng | < 150ms | Barge-in có phản hồi hay không |

Underrun được xếp trên TTFB vì lý do tâm lý: khán giả tha thứ cho **chờ**, nhưng
**đứt quãng** thì bị đọc là hỏng hóc.

---

## 11. Cấm

- Đợi generate xong mới TTS
- `await` không huỷ được ở bất kỳ tầng nào
- Cắt audio đột ngột khi huỷ (phải fade ~80ms)
- Hai đường phát riêng cho precomputed và streaming
- Để TTS timeout thành im lặng
- Sinh số thập phân dạng `0.88` trong lời nói
