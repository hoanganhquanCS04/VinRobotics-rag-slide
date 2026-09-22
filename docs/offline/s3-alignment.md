# S3 — Alignment

**Input:** `SlideRepr[]` + `KBIndex`
**Output:** `AlignmentMap[]` + backfill ngược vào `KBChunk`
**Model:** retrieval (hybrid) + LLM verify

S3 là **điểm hội tụ duy nhất** của hai nhánh, và là phần có giá trị nghiên cứu rõ nhất
trong cả hệ thống.

---

## 1. Bài toán thật sự là gì

Đây là chỗ dễ hiểu sai nhất, nên nói rõ:

> **S3 không đi tìm chunk GIỐNG slide. S3 đi tìm chunk là NGUỒN GỐC của slide.**

Giống nhau ≠ là nguồn. Một chunk nói về reranker rất "giống" trang 9, nhưng có thể nó nói
về **một loại reranker khác hẳn**. Similarity search sẽ trả về nó với điểm cao. Nhận bừa
→ S4 viết kịch bản sai → robot nói sai trước khán giả.

```
S3 = retrieval (thu hẹp)  +  verification (quyết định)
```

**Retrieval một mình không đủ.** Bước verify không phải trang trí.

---

## 2. S3.1 — Dựng truy vấn

Một truy vấn duy nhất là không đủ. Dùng **4 truy vấn** cho mỗi slide rồi hợp kết quả:

```
Slide 7:
  q1 (tiêu đề)    = "Kiến trúc RAG"
  q2 (thông điệp) = "RAG tách truy xuất khỏi sinh, cập nhật tri thức không cần train lại"
  q3 (khái niệm)  = "retriever reranker generator knowledge base"
  q4 (quan hệ)    = "vòng phản hồi từ generator về knowledge base"
```

| Truy vấn | Bắt được cái gì |
|---|---|
| q1 — `title` | chunk có heading tương ứng |
| q2 — `message` | chunk nói cùng luận điểm dù dùng từ khác |
| q3 — `entities` | sparse/BM25 bắt thuật ngữ, viết tắt, tên riêng |
| q4 — `relations` | chi tiết trong sơ đồ mà không có ở đâu khác |

Mỗi truy vấn lấy **top-10** → hợp lại, khử trùng → khoảng **20–25 ứng viên**.

Luôn kèm filter `deck_ids` nếu corpus có phân vùng theo deck; giai đoạn build đầu tiên thì
chưa có, quét toàn corpus.

---

## 3. S3.2 — Verify bằng LLM

**Đây là bước quyết định.** Với từng cặp `(slide, chunk)`:

```
Slide nói: <message + description + entities>
Chunk nói: <text_enriched>

1. Chunk này có THỰC SỰ chống lưng cho nội dung slide không,
   hay chỉ trùng từ khoá?
2. Nếu có, quan hệ là gì:
   source_of     - slide được rút ra trực tiếp từ đây
   elaborates    - giải thích sâu hơn nội dung slide
   evidence_for  - cung cấp số liệu/dẫn chứng cho slide
   contrast      - quan điểm ngược, hữu ích khi có người phản biện
   none          - không liên quan thực chất
3. Confidence 0-1.
4. Trích ra TỐI ĐA 2 CÂU trong chunk thể hiện sự liên quan.
```

**Yêu cầu trích câu là cơ chế chống tự tin giả.** LLM nào không trích ra được câu cụ thể
thì confidence **phải bị hạ** — nó đang đoán bừa. Validate bằng code: câu trích phải là
substring của `text_raw` (sau khi normalize whitespace); không phải → hạ conf về ≤ 0.5.

**Batch 5 cặp một lần gọi** để tiết kiệm.

Prompt ở `prompts/s3_verify.md`.

---

## 4. S3.3 — Backfill hai chiều

```
CHIỀU XUÔI (slide -> chunk)          CHIỀU NGƯỢC (chunk -> slide)

slide 7 --+--> c118  source_of       c118 --> related_slides: [7]
          +--> c121  elaborates      c121 --> related_slides: [7, 11]
          +--> c045  evidence_for    c045 --> related_slides: [7]

                                     c203 --> related_slides: []
                                              align_role: "background"
                                              ^ KHÔNG thuộc slide nào
```

`c203` không map được vào slide nào. **Đừng vứt.** Đó chính là phần kiến thức nền mà slide
đã lược bỏ — **là lý do tồn tại của KB**. Khi khán giả hỏi sâu hơn nội dung slide, robot
lấy từ đây.

Đánh dấu `align_role: "background"` và vẫn `deck_ids: [deck_id]` nếu tài liệu đó thuộc
phạm vi deck.

`align_role` ∈ `primary` (có ≥1 link `source_of`) | `supporting` (chỉ có elaborates /
evidence_for / contrast) | `background` (không map được).

---

## 5. Output — `AlignmentMap[7]`

```json
{
  "slide_id": 7,
  "links": [
    {"chunk_id": "doc2#c118", "relation": "source_of", "conf": 0.94,
     "evidence": "Việc tách retriever khỏi generator cho phép..."},
    {"chunk_id": "doc2#c121", "relation": "elaborates", "conf": 0.87,
     "evidence": "Cơ chế cập nhật không yêu cầu huấn luyện lại..."},
    {"chunk_id": "doc1#c045", "relation": "evidence_for", "conf": 0.71,
     "evidence": "Thí nghiệm cho thấy độ chính xác tăng 12%..."}
  ],
  "primary_source": "doc2#c118",
  "coverage": "good"
}
```

`coverage` ∈ `good` (≥1 link conf > 0.6) | `weak` (có link nhưng conf ≤ 0.6) | `none`.

---

## 6. Coverage report

```
Slide 1  (bìa)        -> skip                  -
Slide 3               -> 4 links, avg 0.88     OK
Slide 7               -> 3 links, avg 0.84     OK
Slide 11              -> 0 links               [!] không có nguồn
Slide 14              -> 1 link,  avg 0.41     [!] yếu
Slide 20 (kết luận)   -> skip                  -

Coverage: 17/20 (85%)
Background chunks: 340
```

**Slide 11 = 0 links nghĩa là gì? Ba khả năng, và người phải phân biệt:**

1. Đó là **ý riêng của tác giả**, không có trong tài liệu → hợp lệ, nhưng runtime phải
   đánh dấu để không trả lời sâu về trang này
2. **Corpus thiếu tài liệu** → phải bổ sung nguồn
3. **S3 chạy sai** → phải sửa

Đây là lý do S3 **bắt buộc phải đẩy sang S7**, không tự quyết được.

---

## 7. Trang nào bỏ qua

Đừng ép align mọi trang. Bỏ qua `slide_type` ∈ `{title, agenda, section_header, thank_you, qa}`.

Ép align mấy trang này chỉ sinh ra link rác confidence 0.3, và làm hỏng luôn con số
coverage (mẫu số phải là số slide **đáng align**, không phải tổng số slide).

---

## 8. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| **Over-linking** | Mọi slide đều link tới cùng vài chunk | Corpus quá hẹp, mọi thứ giống nhau. Nâng ngưỡng, ép `source_of` tối đa **1 chunk/slide** |
| Slide trừu tượng | Slide chỉ có 1 câu khẩu hiệu | Confidence thấp là **đúng**, đừng ép |
| Nguồn khác ngôn ngữ | Slide tiếng Việt, paper tiếng Anh | `bge-m3` xử lý cross-lingual được, nhưng nên **thêm truy vấn bằng `entities` gốc tiếng Anh** |
| Slide tổng hợp nhiều nguồn | 1 slide gộp ý từ 3 paper | Bình thường, **cho phép nhiều `source_of`** |
| Chunk quá dài | Verify trả về "có liên quan" nhưng phần liên quan chỉ 1 câu | Quay lại S5 giảm kích thước chunk |

---

## 9. Chi phí

| Bước | Số lần gọi | Thời gian |
|---|---|---|
| Retrieve (20 slide × 4 query) | 80 truy vấn | ~15s |
| Verify (~17 slide × 22 cặp, batch 5) | ~75 LLM | ~90s |

S3 chạy lại **mỗi khi có deck mới**, kể cả khi KB không đổi.

---

## 10. Quality gate ra khỏi S3

| Chỉ số | Ngưỡng |
|---|---|
| **Alignment coverage** | **≥ 80% slide (đáng align) có ≥1 nguồn conf > 0.6** |
| Tỉ lệ slide `coverage: none` | ≤ 20%, mỗi slide như vậy sinh 1 flag |
| Over-linking: chunk xuất hiện ở > 40% slide | Flag toàn deck |
| Evidence không phải substring của `text_raw` | Tỉ lệ > 10% → nghi prompt hỏng |

---

## 11. Đây là chỗ nghiên cứu rõ nhất

S3 hội đủ ba điều kiện của một đóng góp đo được:

1. **Không có nhãn sẵn** → bài toán thật, không phải áp dụng lại
2. **Cross-modal** → slide (ảnh + text thưa) đối chiếu với văn bản dài
3. **Tự dựng ground truth được** → annotate tay 20 slide × ~20 ứng viên = **400 cặp**,
   một buổi là xong

Rồi đo:

- **Precision / Recall / F1** của link
- **Ablation 1:** chỉ dense · hybrid · hybrid + verify → chứng minh **bước verify đáng giá**
- **Ablation 2:** chunk thô vs chunk enriched → chứng minh **S5.3 đáng giá**
- **Downstream:** alignment tốt hơn có làm **giảm tỉ lệ câu ungrounded ở S4** không

Cái cuối cùng là luận điểm mạnh nhất: **nối chất lượng offline với chất lượng đầu ra cuối
cùng**. Hội đồng sẽ thích con số đó hơn mọi thứ khác trong đồ án.

---

## 12. Cấm

- Nhận link chỉ dựa trên similarity score, **bỏ qua bước verify**
- **Vứt chunk `background`** (không map được vào slide nào)
- Ép align trang bìa / agenda / cảm ơn
- Tính coverage trên mẫu số là tổng số slide thay vì số slide đáng align
- Nhận `evidence` mà không kiểm nó có thật nằm trong chunk không
