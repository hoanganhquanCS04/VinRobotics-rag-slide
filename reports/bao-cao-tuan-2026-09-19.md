# Báo cáo tuần — 14/09 → 19/09/2026

**Người thực hiện:** Hoàng Anh Quân
**Dự án:** Slide Presenter Agent — robot tự thuyết trình slide và trả lời khán giả
**Giai đoạn:** Nghiên cứu & thiết kế kiến trúc (chưa vào code)

---

## 1. Tóm tắt một đoạn

Tuần này tập trung **nghiên cứu bài toán và chốt kiến trúc** cho hệ thống agent tự thuyết
trình slide. Kết quả: xác định được đâu là cái khó thật sự của bài toán, và chốt được thiết
kế chia hệ thống thành **hai luồng — offline và online**. Toàn bộ thiết kế đã được viết
thành bộ đặc tả 18 file (~40.000 từ), mô tả chi tiết từng bước: input gì, output gì, luật
nào bắt buộc, chỗ nào dễ hỏng và đo bằng chỉ số nào. Tuần sau bắt đầu code theo đúng bộ
đặc tả này.

---

## 2. Bài toán: vì sao không làm RAG thông thường được

Mục tiêu: robot cầm một bộ slide, **tự thuyết trình**, và trong lúc nói thì khán giả gửi
câu hỏi vào — robot phải trả lời được, nhảy đúng trang được, rồi quay lại nói tiếp mà
không mất mạch.

Điểm mấu chốt tìm ra trong tuần:

> **Slide là bản nén mất mát của kiến thức. Phần bị mất nằm trong đầu người thuyết trình.**

Deck mục tiêu là loại **ít chữ nhiều hình** — trung bình **dưới 20 từ một trang**, ý nghĩa
nằm trong sơ đồ và biểu đồ chứ không nằm trong chữ. Một hệ thống chỉ đọc chữ trên slide thì
chỉ đọc lại được bullet point: không giải thích được, không trả lời được câu hỏi tiếp theo.

Đây là lý do pipeline RAG text thuần **thất bại hoàn toàn** ở bài toán này, và là lý do
phải có tầng VLM (model đọc hình) trong thiết kế. Nếu deck 80 từ/trang thì phần lớn thiết
kế dưới đây là thừa — nhưng deck mục tiêu thì không.

---

## 3. Quyết định kiến trúc lớn nhất: tách hai luồng

Ràng buộc chi phối mọi thứ: khán giả hỏi xong, robot phải **bắt đầu phát tiếng trong vòng
2,5 giây**. Quá ngưỡng đó thì buổi thuyết trình gãy nhịp, dù câu trả lời có đúng đến mấy.

Nhưng để trả lời đúng và có dẫn nguồn thì cần suy luận nặng — mà suy luận nặng thì không
thể làm trong 2,5 giây.

**Cách gỡ:** tách làm hai luồng, đẩy toàn bộ phần nặng ra khỏi thời gian thực.

| | **Luồng OFFLINE** (build trước buổi nói) | **Luồng ONLINE** (đang thuyết trình) |
|---|---|---|
| Ràng buộc thời gian | Không có — chạy 6 phút cũng được | Cực gắt — dưới 2,5 giây |
| Việc phải làm | Hiểu slide, dựng kho tri thức, viết kịch bản, thu sẵn giọng | Chỉ **tra cứu lại** thứ offline đã dựng sẵn |
| Nguyên tắc | Làm kỹ, không tiếc thời gian | Không suy luận lại — mỗi khi runtime phải "nghĩ" là dấu hiệu offline làm thiếu việc |

Nói ngắn gọn: **offline trả tiền trước, online tiêu**.

---

## 4. Luồng OFFLINE — dựng lại phần kiến thức slide đã đánh rơi

Chia thành 8 bước (S0–S7), bản thân nó lại gồm hai nhánh chạy song song rồi hội tụ:

```
NHÁNH DECK (từ file pptx)              NHÁNH NGUỒN (từ tài liệu gốc PDF)
  S0  Đọc file slide                     S5  Dựng kho tri thức
  S1  Hiểu nội dung từng trang               (cắt đoạn · làm giàu · đánh index)
  S2  Hiểu cấu trúc cả bộ                        │
        └──────────► S3  Nối slide với nguồn ◄───┘
                          │
                      S4  Viết kịch bản nói
                          │
                      S6  Thu sẵn giọng đọc (TTS)
                          │
                      S7  Người duyệt — chỉ duyệt phần bị đánh dấu nghi ngờ
```

Chi tiết từng bước:

| Bước | Làm gì | Ghi chú |
|---|---|---|
| **S0** Ingest | Bóc file `.pptx`: chữ, bảng, số liệu biểu đồ, animation, render ảnh từng trang | Thuần parsing, **không** dùng model — nên dữ liệu ở đây đúng 100% |
| **S1** Slide Understanding | Cho VLM nhìn ảnh trang, sinh ra phần **ý nghĩa** mà parsing không lấy được: trang này *muốn nói gì*, có thực thể nào, quan hệ ra sao | Chạy 2 lượt độc lập rồi đối chiếu, lệch nhau thì đánh dấu |
| **S2** Deck Structure | Bước duy nhất nhìn toàn cục: chia phần, dựng bản đồ khái niệm, xác định trang nào phụ thuộc trang nào, chia ngân sách thời gian | Chỉ sinh **cấu trúc**, không viết câu tiếng Việt nào |
| **S5** KB Construction | Từ tài liệu nguồn (PDF), cắt đoạn theo cây tiêu đề, thêm câu bối cảnh vào mỗi đoạn trước khi embed, đánh index lai (vector + từ khoá) | Không phụ thuộc deck → **chạy song song từ đầu**. Deck thứ hai dùng chung nguồn thì khỏi chạy lại |
| **S3** Alignment | Điểm hội tụ hai nhánh: nối mỗi slide với đoạn tài liệu **đã đẻ ra nó** | Tìm đoạn **là nguồn gốc**, không phải đoạn *trông giống*. Bắt buộc có bước LLM kiểm lại và trích 2 câu bằng chứng |
| **S4** Scenario | Viết kịch bản nói cho từng trang, **mỗi câu kèm dẫn nguồn truy nguyên được** | Bước tốn công nhất về mặt thiết kế — xem mục 5 |
| **S6** Precompute | Thu sẵn giọng đọc từng câu, dựng cache câu hỏi thường gặp, dựng index tra cứu slide | Đây chính là chỗ "mua" latency cho runtime |
| **S7** HITL Review | Người ngồi duyệt — nhưng **chỉ duyệt phần hệ thống tự đánh dấu nghi ngờ**, không duyệt cả 20 trang | Duyệt cả vòng **đọc** lẫn vòng **nghe** |

**Bốn nguyên tắc bất di bất dịch của luồng offline** (đã chốt, mọi thiết kế phải tuân):

1. **Offline không có ràng buộc thời gian, online thì có** — cái gì tính trước được thì
   đẩy hết vào offline.
2. **Dữ liệu đã đúng thì không bao giờ để model sinh lại** — tiêu đề, số liệu biểu đồ, ô
   bảng đã có bản đúng 100% từ bước đọc file. Đưa cho LLM viết lại là tự tạo cơ hội cho nó
   bịa lại cái đang đúng. Mọi trường dữ liệu phải khai rõ nguồn gốc: *do máy bóc ra* hay
   *do model sinh ra*.
3. **Model bịa ở offline nguy hiểm gấp nhiều lần bịa ở online** — bịa lúc runtime thì sai
   một lần trước một câu hỏi; bịa trong kịch bản thì robot nói sai ở **mọi buổi thuyết
   trình** và không ai kiểm lại. Nên mọi câu nội dung phải có dẫn nguồn, không có nguồn là
   cờ đỏ bắt người duyệt.
4. **Nói tự nhiên là yêu cầu bắt buộc, không phải điểm cộng** — robot nghe như đọc bản tin
   thì hệ thống thất bại, dù mọi chỉ số kỹ thuật khác đều đạt. Không ai ngồi nghe hết 30
   phút giọng máy đọc.

---

## 5. Vấn đề khó nhất tuần này: nguyên tắc 3 đá nhau với nguyên tắc 4

Đây là phần mất nhiều thời gian suy nghĩ nhất, nên ghi lại rõ:

- **Nguyên tắc 3** đòi: mọi câu robot nói phải có nguồn.
- **Nguyên tắc 4** đòi: robot phải nói tự nhiên — mà nói tự nhiên thì phải có *"thì"*,
  *"nhé"*, *"đúng không ạ"*, câu hỏi tu từ, câu chuyển mạch. **Không câu nào trong số đó có
  nguồn cả.**

Giữ nguyên tắc 3 nguyên bản thì hoặc là tỉ lệ câu không nguồn nổ tung, hoặc là robot nói
cứng như máy.

**Cách gỡ đã chốt — tách kịch bản thành hai loại câu, không nới lỏng nguyên tắc 3:**

| Loại câu | Yêu cầu nguồn | Cách kiểm |
|---|---|---|
| Câu **nội dung** | Bắt buộc có nguồn, không có là cờ đỏ | Đo tỉ lệ, ngưỡng < 10% |
| Câu **dẫn dắt** | Không cần nguồn, vì **không mang thông tin sự thật mới** | Kiểm **bằng code**, không cần người |

Câu dẫn dắt được quy định chiếm **10–25% tổng âm tiết**, trong đó **10% là sàn cứng** —
lúc cân lại thời lượng không được phép cắt xuống dưới mức đó, nếu không cân giờ vài vòng
là kịch bản khô cứng lại như cũ.

Ngoài ra chốt được **7 đòn bẩy làm câu nói tự nhiên**, xếp theo mức tác động: văn nói khác
văn viết (nguyên nhân số một), nhịp câu dài ngắn đan xen, đánh dấu nhấn/ngắt cho từng câu,
đặt từ dẫn dắt đúng ranh giới cấu trúc, câu hỏi tu từ ở đầu mỗi phần, không đọc bullet,
và giới hạn mỗi câu tối đa 30 âm tiết.

---

## 6. Luồng ONLINE — 7 lớp, nhưng chỉ một lần gọi model

Chia thành 7 lớp R1–R7:

| Lớp | Nhiệm vụ |
|---|---|
| **R1** Intake & fast-path | Nhận câu hỏi, xếp hàng, khử trùng lặp. Lệnh điều hướng rõ ràng ("về trang 5") bắt bằng regex, xử lý ~5ms, không cần model |
| **R2** Navigation | Tìm đúng trang khán giả đang nhắc tới |
| **R3** Context rewriting | Hiểu câu hỏi kiểu "cái này là gì" — phải biết "cái này" đang trỏ vào trang nào, hình nào |
| **R4** Grounded answering | Trả lời có dẫn nguồn; không đủ nguồn thì **nói không biết**, không bịa |
| **R5** Streaming speech | Phát tiếng ngay khi model sinh ra câu đầu tiên, không đợi sinh xong cả đoạn |
| **R6** State & sync | Giữ trạng thái: đang ở trang nào, đã nói tới đâu, quay lại chỗ nào |
| **R7** Interrupt & turn-taking | Khi nào được phép ngắt lời robot, khi nào phải đợi |

**Phát hiện quan trọng nhất của phần online:** R2, R3, R4 **không phải ba lần gọi model**
— chúng là **ba mặt của cùng một lần gọi**. Tách thành ba lần gọi tuần tự thì cộng thêm
300–400ms vô ích mà không được gì. Đây là chỗ đa số tài liệu về agent hỏi đáp mô tả sai
thành pipeline tuần tự.

Luồng chạy thật:

```
câu hỏi vào
   ├─ regex bắt được lệnh điều hướng ──────► nhảy trang luôn       (~5ms)
   └─ không bắt được
        ├─ phát ngay câu đệm đã thu sẵn (chạy song song, che latency)
        └─ MỘT lần gọi model, model tự chọn hành động:
              ├─ nhảy trang  → qua cổng kiểm tra độ tự tin
              ├─ tra cứu kho tri thức → sinh câu trả lời → phát tiếng từng câu
              └─ hành động điều khiển (dừng, tiếp tục, nhắc lại)
```

**Vài luật cứng đã chốt cho runtime:**

- **Không nhồi cả bảng dữ liệu vào prompt.** Ranh giới rõ ràng: *trạng thái* ("tôi đang
  nhìn trang nào") thì nhét thẳng vào prompt vì không index nào trả lời được; *tri thức*
  (nội dung các trang khác, kho tài liệu) thì **bắt buộc phải truy xuất**. Nhờ luật này
  prompt runtime co từ ~3.600 token xuống ~1.300 token.
- **Cổng kiểm tra độ tự tin trước khi nhảy trang.** Nếu trang xếp hạng 1 và trang xếp
  hạng 2 điểm sát nhau → **không nhảy**, hỏi lại khán giả kèm ảnh thu nhỏ. Điểm lấy từ
  model xếp hạng chuyên dụng — số thật, hiệu chỉnh được — **không** lấy điểm tự tin do LLM
  tự khai, vì LLM tự tin thái quá một cách có hệ thống.
- **Chỉ tiêu quan trọng nhất của R2 không phải độ chính xác top-1, mà là tỉ lệ "nhảy sai
  trang mà không thèm hỏi lại"** — nhảy sai im lặng tệ hơn nhiều so với hỏi lại.
- **Kiểm tra có bị ngắt lời hay không sau MỖI CÂU**, không phải sau mỗi trang — vì ranh
  giới ngắt sạch sẽ là ranh giới câu. Đây chính là lý do kịch bản ở offline phải chia theo
  câu và giọng đọc phải thu theo câu.
- **Một giọng đọc duy nhất** cho cả phần thu sẵn lẫn phần sinh trực tiếp. Lệch giọng giữa
  câu kịch bản và câu trả lời là lỗi chói tai nhất của cả hệ thống.

**Ngân sách thời gian đã tính ra:** regex ~5ms · gọi model 400–700ms · truy xuất 50–150ms ·
sinh chữ token đầu 300–500ms · giọng đọc đoạn đầu 200–400ms → **tổng 1,2–1,8 giây**, nằm
trong ngưỡng 2,5s. Thêm hai lớp che: câu đệm phát ngay khi nhận câu hỏi, và hành động thị
giác (nhảy trang, highlight) đi trước lời nói. Khoảng 90% thời lượng buổi nói dùng giọng
đã thu sẵn nên **latency bằng 0**.

---

## 7. Sản phẩm bàn giao tuần này

Bộ đặc tả kỹ thuật **18 file, ~40.000 từ**, trong repo `Robot-slide-rag`:

| Nhóm | Nội dung |
|---|---|
| `docs/offline/` | 9 file — tổng quan + đặc tả chi tiết S0–S7 |
| `docs/runtime/` | 8 file — tổng quan + đặc tả chi tiết R1–R7 |
| `CLAUDE.md` | Bản rút gọn các luật, dùng làm context cho AI coding agent lúc sinh code |
| `README.md` | Tổng quan hệ thống, cấu trúc repo, cách chạy, quality gate |

Mỗi file đặc tả đều có: input/output, luật bắt buộc, **failure mode** (chỗ nào dễ hỏng và
hỏng thì biểu hiện ra sao), và chỉ số đo. Phần "vì sao" nằm trong docs, phần "luật" nằm
trong `CLAUDE.md` — để lúc code không phải suy luận lại từ đầu.

Kèm theo là **bộ quality gate chạy được trong CI** (không đạt thì không deploy):

| Chỉ số | Ngưỡng |
|---|---|
| Tỉ lệ slide nối được với nguồn | ≥ 80% |
| Tỉ lệ câu nội dung không có nguồn | < 10% |
| Sai lệch thời lượng so với ngân sách | < 15% |
| Độ trễ P95 tới tiếng nói đầu tiên | < 2,5s |
| Tự kiểm tra index slide (query bằng chính mô tả của trang phải ra đúng trang đó) | ≥ 90% |
| Recall@5 của bước tìm trang | ≥ 95% |

Cộng thêm 3 chỉ số proxy đo "độ tự nhiên" **chạy tự động được**: độ lệch chuẩn số âm tiết
mỗi câu ≥ 6, số từ văn viết bị cấm = 0, tỉ lệ câu dẫn dắt 10–25%.

---

## 8. Ước tính hiệu năng (theo thiết kế)

- Build lần đầu một deck 20 trang: **~6 phút**
- Sửa 3/20 trang rồi build lại (chỉ chạy lại phần thay đổi): **~40 giây** thay vì 6 phút
- Trả lời khán giả: **1,2–1,8 giây** tới tiếng nói đầu tiên

---

## 9. Điểm còn mở / rủi ro

| Vấn đề | Ghi chú |
|---|---|
| Render slide bằng LibreOffice không khớp 100% với PowerPoint | Font thay thế, SmartArt đôi khi vỡ. Phải cài sẵn font tiếng Việt vào container |
| Ngưỡng của cổng kiểm tra độ tự tin | **Không được đoán** — phải fit trên bộ eval 50 câu có nhãn. Việc này phải làm trước khi code runtime |
| Chất lượng giọng đọc tiếng Việt | Điểm tự nhiên (MOS) cần 3 người ngồi nghe → không đưa vào CI được, xếp thành release gate chạy trước buổi thuyết trình thật |
| Chưa có deck thật và tài liệu nguồn thật để chạy thử | Cần chốt sớm deck mẫu để bắt đầu S0 |

---

## 10. Kế hoạch tuần tới

1. Dựng schema Pydantic cho toàn bộ artifact giữa các bước (chốt hợp đồng dữ liệu trước, code sau)
2. Code **S0** — parser pptx + render PNG, có quality gate đầu ra
3. Code **S5** — kho tri thức với bước làm giàu ngữ cảnh (không phụ thuộc deck nên chạy song song được)
4. **Dựng bộ eval R2: 50 câu hỏi điều hướng có nhãn trang đúng** — làm *trước* khi code
   runtime, vì ngưỡng confidence gate phải fit trên bộ này chứ không được đoán
