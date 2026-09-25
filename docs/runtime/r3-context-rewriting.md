# R3 — Context-aware rewriting

**Vào:** câu hỏi thô + state trình chiếu
**Ra:** `query_expanded` (cho truy xuất) + `query_rewritten` (tham số tool)
**Tách đôi:** R3a deterministic ~5ms · R3b sống trong lần gọi LLM duy nhất

---

## 1. Vì sao có lớp này

### 1.1 Câu hỏi ở đây thiếu thông tin một cách CÓ HỆ THỐNG

RAG thông thường giả định câu hỏi **tự đứng được**: "RAG là gì?", "chi phí bao nhiêu?".
Người dùng gõ vào một ô trống, không có bối cảnh nào ngoài lịch sử chat, nên họ **tự viết
đủ ý**.

Ở đây thì ngược lại. Khán giả đang **nhìn màn hình** và gõ trên điện thoại:

```
"cái mũi tên đỏ kia để làm gì"
"cái này khác gì cách cũ?"
"chỗ vừa nãy anh nói lại được không"
"con số kia lấy ở đâu ra"
```

Mọi câu đều thiếu. Nhưng chúng **không hề mơ hồ với người hỏi** — với họ, tiền ngữ đang
hiện ngay trước mắt. Sự thiếu hụt này là **đặc trưng của setting**, không phải người dùng
cẩu thả.

### 1.2 Tiền ngữ không nằm trong văn bản nào cả

Đây là điểm làm bài toán này khác với coreference resolution kinh điển:

```
Coreference thông thường:  tiền ngữ nằm ở câu trước TRONG VĂN BẢN
                           "RAG có ba khối. Nó hoạt động thế nào?"
                                              ^^ giải bằng chính văn bản

Ở đây:                     tiền ngữ nằm trong TRẠNG THÁI PHI NGÔN NGỮ
                           "cái mũi tên đỏ kia để làm gì"
                            ^^^^^^^^^^^^^^^ không có trong bất kỳ văn bản nào
                                            nó nằm trong thứ khán giả ĐANG NHÌN
```

Không lớp nào khác giải được việc này. Retrieval không giải được (query vô nghĩa với
index). Generation không giải được (không biết hỏi gì). **Phải giải trước khi truy xuất.**

### 1.3 Đây là chỗ nối offline–online chặt nhất

> Lý do S1 ép `relations` ra **triple** thay vì
> văn xuôi chính là để "cái mũi tên đỏ kia" **bind được vào một record cụ thể**.

```json
{"from": "Generator", "to": "Knowledge Base", "type": "feedback",
 "visual": "mũi tên đỏ nét đứt", "note": "vòng cập nhật tri thức"}
```

"mũi tên đỏ" → khớp trường `visual` → có ngay `from` / `to` / `note` → rewrite xong.

Nếu `relations` là đoạn văn *"có một mũi tên đỏ chạy ngược từ Generator về Knowledge
Base"* thì R3 **không có gì để trỏ vào** — model phải đọc hiểu lại đoạn văn đó, và nó sẽ
làm được trong đa số trường hợp rồi thỉnh thoảng sai. Triple thì không có chỗ cho sai.

Đây là ví dụ rõ nhất trong cả hệ thống về việc **một quyết định schema ở offline quyết định
một năng lực ở runtime**.

---

## 2. Công dụng cụ thể

| Không có R3 | Có R3 |
|---|---|
| "cái đấy để làm gì?" → search KB với chính chuỗi đó → rác | → "mục đích của vòng phản hồi từ generator về knowledge base" |
| Khán giả phải gõ câu đầy đủ | Gõ như đang nói chuyện |
| Câu hỏi chỉ trỏ thị giác **không trả lời được** | Trả lời được |

---

## 3. Ba loại tham chiếu, ba nguồn giải

| Loại | Ví dụ | Tiền ngữ nằm ở | Cần gì trong prompt |
|---|---|---|---|
| **Chỉ trỏ thị giác** | "cái mũi tên đỏ kia", "biểu đồ đó", "khối bên phải", "con số kia" | `SlideRepr[at_slide]` | `relations` (có `visual`), `visual_elements`, `chart_data`, `tables` |
| **Thời gian** | "chỗ vừa nãy", "cái anh nói lúc đầu", "phần trước" | `visited[]` + `history` | danh sách trang đã qua + 3 lượt gần nhất |
| **Đại từ** | "nó", "cái này", "cái đấy" | trang hiện tại **hoặc** lượt trước | cả hai — model phải tự phân biệt |

Loại 3 là loại khó nhất vì **hai nguồn cạnh tranh nhau**:

```
Robot vừa trả lời về "reranker"
Khán giả: "nó chạy nhanh không?"
   -> "nó" = reranker (từ lịch sử hội thoại)

Robot đang thuyết trình trang 7 (kiến trúc RAG), chưa ai hỏi gì
Khán giả: "nó chạy nhanh không?"
   -> "nó" = kiến trúc RAG (từ trang hiện tại)
```

Quy tắc ưu tiên nên ghi thẳng vào prompt: **lượt hội thoại gần nhất thắng, trừ khi câu hỏi
có từ chỉ trỏ thị giác** ("kia", "đó", "bên phải", "màu đỏ") — lúc đó trang hiện tại thắng.

---

## 4. Rewrite để TRUY XUẤT, trả lời câu GỐC ★

Đây là chỗ tinh tế nhất của R3 và rất dễ làm sai.

```
Hỏi:       "cái đấy để làm gì?"

Rewrite:   "mục đích của vòng phản hồi từ generator về knowledge base trong RAG"
            └─> dùng cái này cho search_kb()

Trả lời:   phải trả lời "cái đấy để làm gì" theo văn phong người hỏi
            └─> KHÔNG phải trả lời cái câu dài kia
```

**Vì sao quan trọng:** rewrite quá tay thì model tự thêm chi tiết khán giả không hỏi, rồi
trả lời một câu **không ai đặt ra**. Khán giả hỏi 4 chữ, nhận về một bài giảng về kiến trúc
— đúng nội dung, sai câu hỏi.

Giải pháp: giữ **cả hai** trong state.

```json
{
  "text": "cái đấy để làm gì?",
  "query_expanded": "cái đấy để làm gì Generator Knowledge Base vòng cập nhật tri thức retriever reranker",
  "query_rewritten": "mục đích của vòng phản hồi từ generator về knowledge base trong RAG",
  "resolved_refs": [{"surface": "cái đấy", "refers_to": "slide7.relations[2]"}]
}
```

`text` đi vào phần sinh câu trả lời. `query_expanded` đi vào **truy xuất** (R2 và tầng
retrieve của R4). `query_rewritten` là **tham số tool**.
`resolved_refs` để log và để đánh giá — không dùng lúc chạy.

`query_expanded` trông xấu và đó là bình thường — nó là **đầu vào của máy**, không phải
câu tiếng Việt. Cùng tinh thần với `message` phải tự đứng được ở
S1: artifact nào máy đọc thì viết cho máy.

---

## 5. Vòng tròn R3 ↔ R2, và cách gỡ ★

Từ khi R2 chuyển sang truy xuất, xuất hiện một vòng tròn:

```
muốn TRUY XUẤT   -> cần query đã rewrite
muốn REWRITE     -> cần LLM
LLM chạy         -> SAU truy xuất (vì prompt phải chứa ứng viên đã rerank)
                    ^^^ KẸT
```

Gỡ bằng cách tách R3 làm hai, và **phần trước không dùng model**:

### R3a — mở rộng query, DETERMINISTIC, ~5ms

```
1. khớp CHUỖI từ chỉ trỏ vào relations[].visual / visual_elements[]
      "mũi tên đỏ" -> relations[2]{Generator -> Knowledge Base, vòng cập nhật tri thức}
      -> bơm thêm: "Generator", "Knowledge Base", "vòng cập nhật tri thức"

2. nối thêm entities của trang hiện tại vào query
      -> "retriever", "reranker", "generator"

-> query_expanded   (CHỈ dùng để TRUY XUẤT, không bao giờ hiển thị)
```

Không gọi model. Chỉ khớp chuỗi + nối từ. Đây là **query expansion** — mẫu chuẩn của RAG,
không phải giải pháp chống chế.

Vì sao nó đủ: truy xuất chỉ cần **đúng vùng ngữ nghĩa** để top-5 chứa trang đúng. Nó không
cần một câu hỏi đẹp. Bơm thừa vài entity làm giảm precision một chút nhưng **tăng recall**,
và recall mới là thứ tầng sau không cứu được.

### R3b — rewrite thật, trong lần gọi LLM duy nhất

```
ĐÚNG:  1 lần gọi, LLM nhả thẳng:
       search_kb(query="mục đích của vòng phản hồi từ generator về knowledge base trong RAG")

SAI:   gọi LLM lần 1: rewrite
       gọi LLM lần 2: chọn tool                              [+400ms vô ích]
```

Lý do cấu trúc: **rewrite cần đúng cùng một ngữ cảnh với việc chọn tool** — state trình
chiếu, `SlideRepr` trang hiện tại, lịch sử. Tách ra thì phải gửi cùng khối ngữ cảnh đó
**hai lần**, để nhận về một chuỗi mà lần gọi thứ hai vẫn phải tự suy ra lần nữa.

> **Query đã rewrite CHÍNH LÀ tham số của tool call.** Không có bước trung gian nào.

### Luật "đúng 1 lần gọi LLM" vẫn nguyên

R3a **không phải lần gọi model thứ hai** — nó là khớp chuỗi và nối từ, cùng lớp với regex
fast-path của [R1](./r1-intake-fastpath.md).

```
R3a  ~5ms    khớp chuỗi + nối entity      -> query_expanded  -> TRUY XUẤT
R3b  trong   lần gọi LLM duy nhất         -> query_rewritten -> tham số tool
```

### Ba query, đừng lẫn

| | Dùng để | Ai thấy |
|---|---|---|
| `text` (gốc) | **sinh câu trả lời** | khán giả |
| `query_expanded` (R3a) | truy xuất | không ai |
| `query_rewritten` (R3b) | tham số `search_kb` | không ai |

---

## 6. Điều kiện cần: state phải nằm trong prompt

R3 không có code riêng nhiều — nó gần như hoàn toàn là **thiết kế prompt**. Cụ thể phần
`[TRANG HIỆN TẠI]` phải đủ:

```
[TRANG HIỆN TẠI]  (theo at_slide LÚC GỬI, không phải lúc xử lý)
  message:     RAG khắc phục hạn chế của fine-tuning bằng cách tách truy xuất khỏi sinh
  description: Sơ đồ ba khối xếp ngang: Retriever -> Reranker -> Generator.
               Một mũi tên đỏ nét đứt chạy ngược từ Generator về Knowledge Base ở dưới.
  relations:
    - Retriever -> Reranker (flow)
    - Reranker -> Generator (flow)
    - Generator -> Knowledge Base (feedback) [mũi tên đỏ nét đứt] vòng cập nhật tri thức
  entities:    retriever, reranker, generator, knowledge base, fine-tuning
  chart_data:  null
```

`at_slide` lấy từ `Question` do [R1](./r1-intake-fastpath.md) chụp **lúc nhận**. Dùng
`state.slide_id` hiện tại là sai — robot có thể đã sang trang khác khi xử lý tới câu này.

---

## 7. Đánh giá — đây là đóng góp nghiên cứu rõ nhất của nhánh runtime

Dựng bộ test riêng: **câu hỏi không giải được nếu không có state trình chiếu**.

```
Cùng một câu "cái này khác gì cách cũ?" đặt ở trang 7, 12, 16
   -> ba tiền ngữ khác nhau
   -> ba query đúng khác nhau
   -> một hệ thống không dùng state sẽ trả lời giống hệt nhau ở cả ba chỗ
```

### Ba baseline để so

| Baseline | Nhận được gì | Chứng minh điều gì |
|---|---|---|
| Không bơm gì | chỉ câu hỏi thô | mức sàn |
| **Chỉ bơm lịch sử hội thoại** | 3 lượt gần nhất | **baseline quan trọng nhất** |
| Bơm đầy đủ state | + `SlideRepr` trang hiện tại | đề xuất |

Baseline thứ hai là cái ăn tiền: nó chứng minh **trạng thái phi ngôn ngữ mới là thứ giải
được**, chứ không phải lịch sử hội thoại. Nếu bơm lịch sử đã đủ thì R3 không có gì mới —
đó chỉ là coreference thông thường. Con số cần cho báo cáo chính là **khoảng cách giữa
baseline 2 và đề xuất**.

### Chỉ số

- **Coreference resolution accuracy** — chấm tay trên bộ test, so `resolved_refs` với nhãn
- **Retrieval quality sau rewrite** — Recall@5 của chunk đúng, so giữa các baseline
- **Over-rewriting rate** — tỉ lệ query rewrite thêm ràng buộc mà câu gốc không có

---

## 8. Failure mode

| Tình huống | Dấu hiệu | Xử lý |
|---|---|---|
| **Over-rewriting** | Query rewrite dài gấp 4 lần câu gốc, thêm ràng buộc không ai hỏi | Ghi vào prompt: "chỉ thay thế từ chỉ trỏ, không thêm ràng buộc mới" |
| Trả lời câu đã rewrite thay vì câu gốc | Câu trả lời dài dòng, lạc văn phong | Giữ `text` gốc, đưa nó vào phần sinh, không đưa `query_rewritten` |
| Resolve theo trang sai | Sai chỉ khi có độ trễ, không tái hiện được trên máy dev | Dùng `at_slide` từ `Question`, không dùng `state.slide_id` |
| Tiền ngữ không tồn tại | "cái biểu đồ kia" nhưng trang không có biểu đồ | Không đoán → hỏi lại: *"Bạn đang nói tới phần nào trên trang ạ?"* |
| **R3a bơm quá rộng** | `query_expanded` dài gấp 5 lần, truy xuất trả rác | Giới hạn: tối đa 8 entity + 1 record `relations` khớp được |
| **R3a không khớp được gì** | Câu chỉ trỏ nhưng `relations[].visual` không có màu/hình dạng tương ứng | Vẫn bơm `entities` trang hiện tại — đủ để top-5 chứa trang đó |
| `relations` rỗng ở trang đó | S1 đọc hụt sơ đồ | Không cứu được ở runtime — đây là lỗi offline, xem flag `empty_relations_on_diagram` |
| Hai người hỏi "cái này" ở hai trang khác nhau | — | `at_slide` riêng cho từng `Question` nên vẫn đúng |

---

## 9. Cấm

- Rewrite bằng một lần gọi LLM riêng
- **Gọi model ở R3a** — nó phải là khớp chuỗi, deterministic, ~5ms
- **Dùng `query_expanded` để sinh câu trả lời** — nó chỉ để truy xuất
- Trả lời câu đã rewrite thay vì câu gốc
- Dùng `state.slide_id` hiện tại thay vì `at_slide` lúc nhận
- Đoán tiền ngữ khi trang không có phần tử tương ứng
- Thêm ràng buộc mới vào query khi rewrite (R3b) — R3a thì được phép bơm rộng
