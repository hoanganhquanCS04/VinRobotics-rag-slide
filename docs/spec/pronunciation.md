# pronunciation.json — robot đọc thuật ngữ thế nào

**Vào:** `out/kb/*.chunks.json` · **Ra:** `out/deck/<doc_id>/pronunciation.json` · **Code:** *(chưa viết)*

---

## 1. Để làm gì — hai việc, không phải một

Ai cũng nghĩ bảng phát âm chỉ để TTS đọc cho đúng. Nó còn một việc thứ hai, và việc đó
mới là lý do nó phải làm **trước** S4:

```
1. TTS đọc đúng          "plt.savefig" -> không đọc thành "pi-eo-ti chấm sa-vê-phích-gờ"
2. S4 ĐẾM ÂM TIẾT        cùng một chữ, đọc khác nhau thì SỐ ÂM TIẾT khác nhau
```

CLAUDE.md §5 S4:

> Tiếng Việt: **190–210 âm tiết/phút**. Đếm âm tiết, KHÔNG đếm từ, và đếm
> **theo `pronunciation.json`** (viết tắt đọc thế nào thì đếm thế ấy).

Ví dụ thật trên deck này:

```
"plt.savefig"   đọc "pi-eo-ti chấm sếp-phích"   ->  6 âm tiết   ->  ~1.8 giây
                đọc "plot sếp-phai"              ->  3 âm tiết   ->  ~0.9 giây
```

Một chữ, chênh nhau gấp đôi. Nhân lên vài chục lần trong một buổi thì kịch bản tưởng
5 phút hoá ra 7 phút — **mà không ai phát hiện cho tới lúc nghe thật**.

Đó là lý do §5 S6b bắt so hash:

> Hash `pronunciation.json` ghi vào `Scenario`; S6b **so hash trước khi synth**.
> Lệch bảng = S4 đếm một đằng, TTS đọc một nẻo, timing sai mà không ai thấy.

---

## 2. Vì sao máy không tự làm được

Đã thử trích tự động trên 52 chunk. Kết quả chia làm ba nhóm, chất lượng khác hẳn nhau:

| nhóm | số từ | máy tự tin? | ví dụ |
|---|---|---|---|
| **Gọi hàm / module** (có dấu chấm) | 41 | ✅ chắc chắn | `plt.savefig` · `np.linspace` · `matplotlib.pyplot` · `ax.plot3D` |
| **Viết tắt** (toàn hoa) | 18 | ⚠️ lẫn rác | `CSV` `API` `MNIST` `MATLAB` `USD` — nhưng lẫn `FFFF` `A2BE2` (mã màu) |
| **Từ tiếng Anh thường** | 276 | ❌ không tách nổi | `plot` `sin` `petal` `iris` `alpha` — **lẫn** `quan` `theo` `hoa` `xanh` `sai` `nhau` |

**Nhóm ba là chỗ luật ký tự bó tay.** Tiếng Việt **không dấu** trông y hệt tiếng Anh:

```
quan  theo  hoa  trong  xanh  ba  cho  hai  sai  dao  nhau  khi  ra  gian
```

Toàn chữ cái ASCII, không cách nào phân biệt với `plot`, `sin`, `color` bằng regex.
Muốn tách phải có từ điển tiếng Việt — thêm phụ thuộc, mà vẫn sai ở tên riêng.

→ **Máy đề xuất, NGƯỜI chốt.** Không có đường tự động hoàn toàn.

---

## 3. Schema

```json
{
  "version": 1,
  "doc_id": "3_datavisualization",
  "hash": "sha1 của phần terms — S4 ghi vào Scenario, S6b so trước khi synth",
  "terms": {
    "plt.savefig": {
      "say": "pi eo ti chấm sếp phích",
      "syllables": 6,
      "mode": "spell_prefix",
      "by": "nguoi"
    },
    "matplotlib": {
      "say": "mát plót líp",
      "syllables": 3,
      "mode": "phonetic_vi",
      "by": "nguoi"
    },
    "CSV": {
      "say": "xê ét vê",
      "syllables": 3,
      "mode": "spell",
      "by": "auto"
    }
  },
  "skip": ["#F0F8FF", "#A9A9A9", "https://..."]
}
```

| field | nghĩa |
|---|---|
| `say` | cách đọc, viết bằng chữ Việt. **Dùng cho CẢ đếm âm tiết LẪN đưa vào TTS** |
| `syllables` | **tính tự động** từ `say` (đếm cụm cách nhau bởi khoảng trắng). Người không phải gõ |
| `mode` | `spell` đọc từng chữ cái · `phonetic_vi` phiên âm Việt · `as_english` đọc nguyên · `spell_prefix` tách phần viết tắt rồi đọc phần sau |
| `by` | `auto` máy đề xuất chưa ai duyệt · `nguoi` người đã chốt |

**`syllables` tính từ `say`, không gõ tay.** Gõ tay là mở cửa cho lệch: sửa `say` mà quên
sửa số thì S4 đếm sai mà không báo lỗi.

**`skip`**: thứ robot **không được đọc**. Trang 15 đã vá tay chứa ~200 mã màu hex
(`#F0F8FF`, `#FAEBD7`...). Robot đọc hết chỗ đó là mất 10 phút và vô nghĩa. Phải chặn ở
đây, đừng trông vào LLM tự biết.

---

## 4. Bốn cách đọc — chọn cái nào

```
spell          CSV        -> "xê ét vê"               từng chữ cái
phonetic_vi    matplotlib -> "mát plót líp"           phiên âm ra tiếng Việt
as_english     Python     -> "Python"                 để TTS tự đọc giọng Anh
spell_prefix   plt.plot   -> "pi eo ti chấm plót"     viết tắt đọc chữ, phần sau phiên âm
```

**Đề xuất mặc định cho deck này** (giảng bài CNTT tiếng Việt, người nghe là sinh viên):

| loại | mặc định | vì sao |
|---|---|---|
| tên thư viện quen (`Python`, `NumPy`, `Matplotlib`) | `as_english` | giảng viên Việt đọc gần như nguyên gốc, sinh viên quen tai |
| viết tắt 2–4 chữ (`CSV`, `API`, `USD`) | `spell` | đọc từng chữ là cách nói tự nhiên |
| gọi hàm (`plt.savefig`) | **cân nhắc BỎ HẲN** | xem §5 |
| mã màu hex, URL | `skip` | không đọc |

---

## 5. Điều quan trọng nhất: phần lớn tên hàm KHÔNG NÊN đọc ra miệng

41 tên hàm trong deck. Nhưng người thuyết trình thật **không đọc code thành tiếng**.
Không ai đứng lớp nói:

> *"Ta gọi pi-eo-ti chấm ép-rờ-bo mở ngoặc ích phẩy i phẩy y-ê-rờ bằng đi-oai..."*

Họ nói:

> *"Ở đây mình gọi errorbar, truyền thêm sai số theo trục y."*

Và CLAUDE.md §5 S4 đã có luật gần giống:

> Không đọc bullet, không đọc bảng theo hàng

**Đề xuất: thêm luật tương tự cho code.** S4 không đọc nguyên đoạn mã, chỉ nói **tên hàm
và nó làm gì**. Vậy thì bảng phát âm chỉ cần chứa:

```
tên hàm TRẦN, bỏ tiền tố module:   savefig · errorbar · linspace · scatter · hist
tên thư viện:                       Matplotlib · NumPy · Cartopy · Python
viết tắt:                           CSV · API · MNIST · USD
```

**~25 mục thay vì 335.** Vừa sức ngồi duyệt một lần.

---

## 6. Quy trình đề xuất

```
1. scripts/extract_terms.py  quét chunks.json
                             -> nhóm chắc chắn (có dấu chấm, toàn hoa)
                             -> điền "say" mặc định theo bảng §4
                             -> ghi by:"auto", KHÔNG tự coi là xong

2. NGƯỜI mở file, làm 3 việc:
                             -> sửa "say" chỗ máy đoán sai
                             -> xoá mục không bao giờ nói ra miệng
                             -> thêm từ máy bỏ sót (nhóm ba máy không tách được)
                             -> đổi by:"auto" thành "nguoi"

3. tính lại syllables + hash tự động

4. S4 đếm âm tiết theo bảng · S6b so hash trước khi synth
```

**Vì sao `by: "auto"` phải khác `by: "nguoi"`:** nhìn file là biết ngay chỗ nào người đã
duyệt, chỗ nào máy đoán. Không có nó thì vài tuần sau không ai nhớ mục nào đáng tin —
cùng một lý do `provenance` tồn tại ở `ParsedDocument` (NT2).

Bổ sung thêm deck mới thì **giữ nguyên mục `by: "nguoi"`**, chỉ thêm mục mới với
`by: "auto"`. Người duyệt không phải làm lại từ đầu.

---

## 7. Đo gì

```
số mục by:"nguoi" / tổng số mục     tỉ lệ đã duyệt, dưới 100% thì S4 đang đoán
từ xuất hiện trong Scenario mà KHÔNG có trong bảng   -> cờ unknown_pronunciation
hash trong Scenario != hash bảng hiện tại            -> S6b DỪNG, không synth
```

Cờ `unknown_pronunciation` là cái chặn thật: S4 viết ra một thuật ngữ chưa ai quyết cách
đọc thì **phải báo**, không được lặng lẽ đếm bừa.
