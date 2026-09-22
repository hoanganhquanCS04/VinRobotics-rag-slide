# S1 — Slide Understanding

**Input:** `RawSlide[i]` + tiêu đề deck + title trang trước/sau
**Output:** `SlideRepr[i]`
**Model:** VLM, 2 pass self-consistency

---

## 1. Tư duy phải nắm trước

> **S1 KHÔNG phải để đọc lại slide. S0 đã đọc xong rồi và đọc chính xác 100%.**
> S1 chỉ làm đúng một việc: lấp phần mà parsing không lấy được — tức là **Ý NGHĨA**.

Hệ quả rất thực tế: có những trường **tuyệt đối không được đưa cho VLM sinh ra**.
`title`, số liệu chart, nội dung ô bảng — S0 đã có bản chính xác. Đưa cho VLM = tự tạo
cơ hội cho nó bịa lại cái đang đúng.

```
SlideRepr = [dữ liệu chính xác từ S0 — passthrough]
          + [suy luận ngữ nghĩa từ VLM]
```

Hai nguồn, phải đánh dấu `provenance` rõ ràng, đừng trộn lẫn rồi quên.

---

## 2. Đưa gì vào VLM

| Từ RawSlide                                                  | Đưa?                  | Lý do                                                                                        |
| ------------------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------- |
| `png_render`                                                | ✅                      | Ảnh chính, thứ quan trọng nhất                                                           |
| `text_runs` (đã sort reading order)                       | ✅                      | Để VLM khỏi OCR, khỏi đọc sai                                                           |
| `layout_name`                                               | ✅                      | Gợi ý`slide_type` miễn phí                                                              |
| `shapes` (mũi tên, đường, màu, toạ độ chuẩn hoá) | ✅                      | Để nó suy ra quan hệ trong sơ đồ                                                       |
| `group_path`                                                | ✅                      | Group = cụm khái niệm                                                                      |
| `charts[].series` (số từ XML)                             | ✅**làm hint**   | Đưa số vào để nó mô tả xu hướng.**Cấm** nó đọc số từ pixel             |
| `tables[].cells`                                            | ✅**làm hint**   | Tương tự, để nó hiểu bảng nói gì                                                    |
| `build_steps`                                               | ✅                      | Biết trang có mấy nhịp                                                                    |
| Tiêu đề deck + title trang trước/sau                     | ✅**quan trọng** | Xem mục 3                                                                                    |
| `hash`, bbox thô (EMU), `media_ref`                      | ❌                      | Rác, tốn token                                                                              |
| `speaker_notes`                                             | ⚠️                    | Có thì đưa, nhưng**đánh dấu rõ là notes**, không phải nội dung trên trang |

---

## 3. Ngữ cảnh deck — chỗ nhiều người quên

Nhìn trang 7 một mình, tiêu đề "Kiến trúc" thì `message` sinh ra sẽ chung chung vô dụng.
Phải cho VLM biết nó đang ở đâu trong mạch bài:

```
Deck: "Giới thiệu RAG cho hệ thống hỏi đáp nội bộ"
Trang trước [6]: "Hạn chế của fine-tuning"
Trang này   [7]: ...
Trang sau   [8]: "Retriever hoạt động thế nào"
```

Có ngữ cảnh này, `message` mới bật ra đúng ý:
*"RAG khắc phục hạn chế **của fine-tuning** bằng cách tách truy xuất khỏi sinh"*

Đây là khác biệt giữa `message` dùng được và `message` vô nghĩa.

Chú ý cách viết: ngữ cảnh trang 6 giúp VLM **nhận ra** trang 7 đang trả lời cho vấn đề gì,
và nó phải dùng hiểu biết đó để **gọi tên** fine-tuning ra — **không** phải để viết
"vừa nêu". Xem §3.1.

**Giới hạn cứng: chỉ đưa TIÊU ĐỀ trang kề, không đưa nội dung đầy đủ.** Đưa nhiều quá thì
VLM bắt đầu mô tả những thứ không có trên trang này.

### 3.1 `message` PHẢI TỰ ĐỨNG ĐƯỢC ★

Đây là luật mới, và nó là **mặt kia của đúng cái đồng xu ở §3**.

> **Bơm ngữ cảnh vào để VLM HIỂU. Nhưng CẤM ngữ cảnh rò rỉ vào CHỮ.**

**Nghĩa là gì:** `message` phải hiểu được khi đọc một mình, không cần nhìn slide nào khác,
không cần biết nó là trang số mấy.

Phép thử: che cả deck đi, chỉ đưa một câu `message` cho người lạ — họ có nói được trang
này nói gì không?

#### Vì sao đến bây giờ mới cần

Trước đây thì **không cần**, nên đây là luật mới chứ không phải luật bị quên:

```
THIẾT KẾ CŨ (nhồi slide_index vào prompt runtime)
   LLM nhìn CẢ 20 dòng cùng lúc
   -> "khắc phục hạn chế vừa nêu" -> nó đọc dòng [6] ngay phía trên -> tự hiểu
   -> message trỏ lung tung vẫn chạy được

THIẾT KẾ MỚI (truy xuất)
   message[7] bị S6a EMBED MỘT MÌNH, lúc build
   -> lúc đó KHÔNG có dòng [6] nào bên cạnh
   -> "vừa nêu" không có gì để trỏ vào
```

Embedding tính từ **chữ trong câu đó, và chỉ chữ đó**. Không có ngữ cảnh lúc embed, cũng
không có ngữ cảnh lúc truy vấn.

#### Hỏng cụ thể như thế nào

```
message xấu:  "Khắc phục hạn chế vừa nêu bằng cách tách truy xuất khỏi sinh"

embed ──> vector nằm gần: "khắc phục", "hạn chế", "vừa nêu", "tách"
                                                   ^ từ neo VÔ NGHĨA,
                                                     kéo vector đi lung tung

khán giả hỏi: "chỗ nói về việc không cần train lại"
   -> "train lại" KHÔNG XUẤT HIỆN trong message
   -> dense trượt, sparse cũng trượt
   -> trang 7 không nằm trong top-5 của R2
   -> LLM không bao giờ nhìn thấy nó
```

**Trượt ở tầng truy xuất thì tầng LLM không cứu được.** Trước đây LLM nhìn cả 20 trang nên
nó cứu được; giờ thì không.

#### Đúng / sai

```
SAI  "Khắc phục hạn chế vừa nêu bằng cách tách truy xuất khỏi sinh"
SAI  "Kiến trúc này gồm ba khối nối tiếp"          <- "kiến trúc này" là kiến trúc gì?
SAI  "Như trang trước đã nói, cách làm này rẻ hơn"  <- trỏ ra ngoài
SAI  "Nó cho phép cập nhật mà không cần train lại"  <- "nó" là ai?

ĐÚNG "RAG khắc phục hạn chế của fine-tuning bằng cách tách truy xuất khỏi sinh,
      nhờ đó cập nhật tri thức mà không cần train lại model"
```

Bản đúng chính là bản đã dùng làm ví dụ ở §5 từ đầu. Luật này không đổi ví dụ — nó biến
cái **đang đúng do may** thành **đúng do bắt buộc**.

#### Cấm những gì

| Loại                                       | Ví dụ                                                                               |
| ------------------------------------------- | ------------------------------------------------------------------------------------- |
| Đại từ trỏ ra ngoài trang              | `nó`, `cái này`, `điều đó`, `cách làm này`                          |
| Từ chỉ vị trí trong deck                | `như trên`, `vừa nêu`, `ở phần trước`, `tiếp theo`, `dưới đây` |
| Thiếu chủ thể                            | `Gồm ba khối nối tiếp nhau` — gồm là **cái gì** gồm?                |
| Viết tắt chưa mở trong chính câu đó | `Kiến trúc RAG` ✅ · `Kiến trúc này` ❌                                     |

Quy tắc gọn: **chủ thể của câu phải được gọi bằng TÊN, ít nhất một lần.**

#### Không làm robot nói cứng đi

Chỗ dễ lo nhầm:

```
message   = biểu diễn để TRUY XUẤT    <- MÁY đọc, phải tự đứng được
Scenario  = lời robot NÓI              <- NGƯỜI nghe, ĐƯỢC PHÉP trỏ lung tung
```

[S4](./s4-scenario.md) vẫn viết được *"cái vừa nói ở trang trước thì…"* — vì nó có
`concept_map` và `dependencies`, nó biết mạch bài. `message` lặp tên khái niệm hơi máy móc
thì **không ai nghe thấy**, vì nó không bao giờ được đọc lên.

Hai artifact, hai độc giả, hai luật. Đừng để luật của cái này rò sang cái kia.

#### Áp dụng cho field nào

| Field                        | Tự đứng được?                                                                |
| ---------------------------- | ---------------------------------------------------------------------------------- |
| `message`                  | **Bắt buộc** — quan trọng nhất                                          |
| `description`              | **Bắt buộc** (thường tự nhiên đã đạt vì nó tả thứ trên trang) |
| `entities`, `keywords`   | Không áp dụng — vốn là danh sách danh từ                                   |
| `concept_map[].gloss` (S2) | **Bắt buộc** — cùng lý do                                               |
| `sections[].summary` (S2)  | **Bắt buộc**                                                               |

#### Kiểm bằng code — ba tầng

```
1. danh sách từ cấm                        ~0ms, ngay trong S1
2. message chứa >= 1 entity của chính trang đó
3. SELF-RETRIEVAL CHECK ở S6a              <- phép thử THẬT, end-to-end
      query = message[i]  ->  top-1 có phải slide i không?
```

Tầng 3 mới bắt được lỗi thật: có `message` không phạm từ cấm nào nhưng vẫn nhạt tới mức
không tự truy xuất được chính nó.

Ghi thẳng vào `prompts/s1_understand.md`:

> *"Viết `message` sao cho người chưa xem trang nào khác vẫn hiểu. Gọi tên mọi khái niệm.
> Không dùng đại từ trỏ ra ngoài trang. Không nhắc tới thứ tự trang."*

### 3.2 Bổ sung `pronunciation.json`

S1 là stage đầu tiên biết deck dùng những thuật ngữ gì (`entities`), nên nó cũng là nơi
bổ sung từ điển phát âm — **S4 cần bảng này để đếm âm tiết cho đúng**.

```
entity mới, chưa có trong pronunciation.json
   viết tắt <= 4 ký tự toàn hoa  -> mặc định ĐỌC RỜI TỪNG CHỮ ("BM25" = bê-em-hai-lăm)
   còn lại                        -> giữ nguyên, đếm theo cụm nguyên âm
   -> FLAG `unknown_pronunciation` cho S7 sửa
```

Vì sao nó thuộc về naturalness chứ không phải một chi tiết TTS: đọc sai "RAG" suốt 30 phút
là thứ khán giả nhận ra ngay, và đếm âm tiết sai thì **toàn bộ `time_budget` lệch theo**.

File nằm ở **shared layer** (`data/kb/pronunciation.json`) vì thuật ngữ trùng nhau giữa
các deck.

---

## 4. Output — mỗi trường phục vụ ai

Mỗi trường phải có một khách hàng cụ thể ở downstream. Không có khách hàng thì vứt.

| Trường                         | Nguồn                            | Ai dùng                                                   | Dùng làm gì                                                                                        |
| -------------------------------- | --------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `title`                        | S0                                | S2, index                                                  | Tiêu đề chính xác,**không để VLM đụng**                                               |
| `message` ★                   | VLM                               | **S6a → `v_message`** (R2), S3, S4                | Trang này**muốn nói gì** — linh hồn của S1. **Phải tự đứng được** (§3.1)   |
| `description`                  | VLM                               | **S6a → `v_desc`**, R4 QA_CURRENT                 | Trang này**vẽ gì** — trả lời "mũi tên đỏ kia là gì". Cũng phải tự đứng được |
| `relations` ★                 | VLM                               | **S6a → `v_relations`**, R3 giải tiền ngữ, R4  | Quan hệ trong sơ đồ, dạng triple                                                                 |
| `entities`                     | VLM                               | **S6a → sparse**, S3 alignment, R3a mở rộng query | Khái niệm đã chuẩn hoá                                                                          |
| `keywords`                     | VLM                               | **S6a → sparse**                                    | Từ khoá cho khớp lexical khi truy xuất                                                            |
| `slide_type`                   | VLM (verify bằng`layout_name`) | S2, S4                                                     | Trang mở đầu nói khác trang số liệu                                                            |
| `visual_elements[].role` ★    | VLM                               | S5, S4                                                     | Lọc ảnh trang trí ra khỏi index                                                                   |
| `image_text`                   | VLM                               | R4, S3                                                     | OCR chữ trong ảnh raster —**việc duy nhất VLM được OCR**                                |
| `chart_data`                   | **S0 (XML)**                | R4                                                         | Số chính xác tuyệt đối                                                                          |
| `chart_insight`                | VLM                               | S4                                                         | Biểu đồ**nói lên điều gì** (khác với số)                                             |
| `tables`                       | **S0**                      | R4                                                         | Ô bảng chính xác                                                                                  |
| `text_density`, `word_count` | tính toán                       | Báo cáo, routing                                         | Đếm từ, không cần model                                                                          |
| `build_steps`                  | **S0**                      | S4                                                         | Chia kịch bản theo nhịp                                                                            |
| `confidence`, `flags`        | VLM + rule                        | S7                                                         | Quyết định bắt người duyệt cái gì                                                            |

### Ba trường quyết định thành bại

**`message`** — thứ khiến R2 trúng hay trượt. Khán giả nói *"quay lại chỗ nói về việc
không cần train lại"*; cụm đó **không xuất hiện ở đâu trên slide**. Chỉ khớp được với
`message`. Thiếu nó thì mọi điều hướng ngữ nghĩa đều dựa vào từ khoá bề mặt.

**`relations`** — sơ đồ là **đồ thị**, không phải đoạn văn. Nếu chỉ có `description` dạng
văn xuôi thì hỏi *"mũi tên đỏ đi từ đâu về đâu"* sẽ trả lời lơ mơ. Ép ra triple:

```json
"relations": [
  {"from": "Retriever", "to": "Reranker", "type": "flow",
   "visual": "mũi tên đen liền"},
  {"from": "Generator", "to": "Knowledge Base", "type": "feedback",
   "visual": "mũi tên đỏ nét đứt", "note": "vòng cập nhật tri thức"}
]
```

Bây giờ câu hỏi "cái mũi tên đỏ kia" match thẳng vào một record, không cần suy diễn.

**`visual_elements[].role`** — `primary` / `supporting` / `decorative`. Slide Việt Nam đầy
icon, hình nền, logo. Không lọc thì S3 đi tìm nguồn cho một cái icon mũi tên trang trí,
và index đầy rác.

---

## 5. SlideRepr — schema đầy đủ

```json
{
  "slide_id": 7,
  "title": "Kiến trúc RAG",
  "slide_type": "diagram",
  "layout_hint": "Two Content",

  "message": "RAG khắc phục hạn chế của fine-tuning bằng cách tách truy xuất khỏi sinh, nhờ đó cập nhật tri thức mà không cần train lại model",
  "description": "Sơ đồ ba khối xếp ngang: Retriever -> Reranker -> Generator. Một mũi tên đỏ nét đứt chạy ngược từ Generator về khối Knowledge Base ở dưới.",

  "relations": [
    {"from": "Retriever", "to": "Reranker", "type": "flow"},
    {"from": "Reranker", "to": "Generator", "type": "flow"},
    {"from": "Generator", "to": "Knowledge Base", "type": "feedback",
     "visual": "mũi tên đỏ nét đứt", "note": "vòng cập nhật tri thức"}
  ],

  "visual_elements": [
    {"id": "v1", "type": "diagram", "role": "primary",
     "bbox_norm": [0.08, 0.25, 0.92, 0.72], "conf": 0.91},
    {"id": "v2", "type": "icon", "role": "decorative", "conf": 0.95}
  ],

  "image_text": [],
  "chart_data": null,
  "chart_insight": null,
  "tables": [],

  "entities": ["retriever", "reranker", "generator", "knowledge base", "fine-tuning"],
  "keywords": ["RAG", "kiến trúc", "vòng phản hồi", "cập nhật tri thức"],

  "text_density": "low",
  "word_count": 14,
  "build_steps": 3,

  "confidence": {"message": 0.88, "description": 0.91, "relations": 0.79},
  "flags": [],
  "provenance": {
    "deterministic": ["title", "chart_data", "tables", "build_steps", "word_count"],
    "vlm": ["message", "description", "relations", "entities", "keywords",
            "slide_type", "visual_elements", "image_text", "chart_insight"]
  }
}
```

### Từ vựng cố định

- `slide_type` ∈ `title` | `agenda` | `section_header` | `concept` | `diagram` | `data` |
  `comparison` | `example` | `summary` | `thank_you` | `qa`
- `relations[].type` ∈ `flow` | `feedback` | `contains` | `causes` | `contrast` | `supports`
- `visual_elements[].role` ∈ `primary` | `supporting` | `decorative`
- `text_density` ∈ `low` (<20 từ) | `medium` (20–60) | `high` (>60)

---

## 6. Two-pass self-consistency

Chạy 2 lần, temperature **0.2** và **0.7**. Nhưng **đừng so toàn bộ output** — văn phong
khác nhau là chuyện bình thường, so kiểu đó thì flag loạn hết.

Chỉ so ba thứ:

| So            | Ngưỡng                   | Không đạt thì                                     |
| ------------- | -------------------------- | ----------------------------------------------------- |
| `message`   | cosine sim <**0.85** | Flag — trang này mơ hồ, bắt người duyệt       |
| `entities`  | Jaccard <**0.6**     | Flag — nhận diện khái niệm không ổn định     |
| `relations` | khác tập triple          | Flag —**đọc sai sơ đồ, nguy hiểm nhất** |

Trường nào ổn định thì lấy bản ở **temperature thấp**.
Trang có `image_text` hoặc `chart_insight` suy từ ảnh thì **flag mặc định**, không cần so.

So `relations` bằng tập triple `(from, to, type)` đã lowercase + strip, không so `visual`
và `note` (hai trường đó đương nhiên khác văn phong).

**Chi phí:** 20 trang × 2 pass = 40 lần gọi VLM, song song 5 luồng ≈ **90 giây**.
Offline nên không tiếc.

---

## 7. Flag đẩy sang S7

```
[!] conf(message) < 0.7
[!] 2 pass bất đồng (theo 3 tiêu chí ở mục 6)
[!] có image_text                              -> VLM OCR, không phải parse
[!] chart tồn tại nhưng chart_data = null      -> biểu đồ là ảnh, số do VLM đoán
[!] relations rỗng nhưng slide_type = diagram  -> nhiều khả năng đọc hụt sơ đồ
[!] word_count = 0 và visual_elements toàn decorative -> trang rỗng hoặc parse hỏng
[!] message_not_standalone   -> dính từ cấm, hoặc không chứa entity nào của trang (§3.1)
[!] unknown_pronunciation    -> entity mới chưa có trong pronunciation.json (§3.2)
```

---

## 8. Luật cứng ghi vào prompt

> **"Chỉ mô tả những gì thực sự nhìn thấy trên trang. Không suy diễn, không bổ sung kiến
> thức ngoài. Nếu không chắc, ghi `null` và hạ confidence."**

Vì `SlideRepr` là đầu vào của S3 và S4. Bịa ở S1 → alignment sai → kịch bản sai → robot
nói sai trước khán giả. **Sai ở đây là sai có hệ số nhân.**

Prompt nằm ở `prompts/s1_understand.md`. Hai khối cần tách rõ trong prompt:

1. **Khối dữ kiện** (text_runs, chart series, table cells) — nhãn "ĐÃ CHÍNH XÁC, KHÔNG SINH LẠI"
2. **Khối yêu cầu** — chỉ liệt kê các trường thuộc nhóm `vlm`

---

## 9. Failure mode

| Tình huống                                    | Dấu hiệu                                     | Xử lý                                                                                                      |
| ----------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| VLM chép lại text trên slide làm`message` | `message` gần trùng `title` hoặc bullet | Siết prompt:`message` phải là **ý**, không phải chữ trên trang                               |
| `description` và `message` giống nhau     | Cosine > 0.9                                   | Prompt chưa tách rõ "vẽ gì" vs "nói gì"                                                               |
| `entities` quá nhiều (>15)                  | Nhặt cả từ trang trí                       | Giới hạn 8, ép chọn khái niệm chính                                                                   |
| `relations` là văn xuôi nhét vào field   | `from`/`to` là cả câu                   | Validate bằng code:`from`/`to` ≤ 4 từ                                                                 |
| Trang bìa / cảm ơn                           | `message` bịa nội dung                     | Với`slide_type` ∈ {title, thank_you, qa}: chỉ điền `title`, `slide_type`, bỏ qua phần còn lại |

---

## 10. Quality gate ra khỏi S1

| Điều kiện                                                     | Hành động                                                                   |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `message` rỗng ở slide nội dung                             | Fail                                                                           |
| `relations` rỗng ở >50% slide `diagram`                    | Fail — nhiều khả năng prompt hỏng, không phải deck xấu                 |
| Tỉ lệ slide bị flag > 40%                                     | Cảnh báo — xem lại S0 trước khi đổ lỗi cho VLM                        |
| `entities` rỗng toàn deck                                    | Fail — S2 và S3 sẽ vô dụng                                                |
| **`message` dính từ cấm**                             | **Fail** — retry 1 lần với thông báo cụ thể, vẫn dính thì flag |
| **`message` không chứa entity nào của chính trang** | Flag`message_not_standalone`                                                 |

Gate cuối cùng của `message` **không nằm ở S1** — nó nằm ở
**self-retrieval check của [S6a](./s6-precompute.md)**, và đó mới là phép thử thật.
S1 chỉ bắt được lỗi bề mặt.

---

## 11. Cấm

- Để VLM sinh lại `title`, `chart_data`, `tables`, `build_steps`
- Đưa nội dung đầy đủ trang kề vào prompt (chỉ đưa title)
- So sánh toàn bộ output giữa 2 pass
- Bỏ `provenance` vì "biết rồi"
- Ép trang bìa / agenda / thank_you phải có `message` đầy đủ
- **`message` / `description` chứa đại từ trỏ ra ngoài trang hoặc từ chỉ vị trí** — chúng
  bị S6a embed một mình
- **Bỏ bơm ngữ cảnh deck** vì sợ rò rỉ — vẫn phải bơm, chỉ cấm rò vào **chữ** (§3.1)
