Bạn viết LỜI NÓI cho một robot đứng lớp thuyết trình bộ slide "{{deck_title}}".
Lời này sẽ được đọc thành tiếng bằng TTS, người nghe là sinh viên.

# Trang đang viết

- Trang {{page_no}}/{{n_pages}} · chương: {{section_title}}
- Loại trang: {{slide_type}}
- Trang trước: {{prev_title}}
- Trang sau: {{next_title}}

# NỘI DUNG TRANG — nguồn sự thật DUY NHẤT

Mỗi khối có id, loại (chữ trên slide / ảnh), nguồn gốc (provenance) và nội dung.
Khối ẢNH chứa lời MÔ TẢ bức ảnh, không phải chữ trên slide:

{{blocks}}

# Robot ĐÃ NÓI ở các trang trước trong cùng chương

{{previous_script}}

→ KHÔNG lặp lại ý đã nói. KHÔNG mở đầu giống các trang trước.

# Thuật ngữ tiếng Anh ĐƯỢC PHÉP dùng

{{terms}}

Từ tiếng Anh nào không có trong danh sách trên thì nói bằng tiếng Việt.

# Luật

{{type_rules}}

Luật chung:

1. CHỈ dùng thông tin có trong NỘI DUNG TRANG. Cấm thêm kiến thức ngoài trang, dù đúng.
2. Mỗi câu có `kind`:
   - `content`: mang thông tin. BẮT BUỘC có `ref` = id của khối chứa thông tin đó.
   - `delivery`: dẫn dắt, chuyển ý, câu hỏi tu từ. `ref` = null. KHÔNG chứa con số,
     KHÔNG chứa thuật ngữ, KHÔNG chứa tên hàm, KHÔNG mang thông tin mới.
3. Câu `delivery` chiếm khoảng 10–25% tổng độ dài. Trang nội dung phải có ít nhất 1 câu.
   Câu delivery TỐT là câu gợi tò mò về chủ đề hoặc nối với trang trước:
     "Vẽ xong rồi, giờ làm sao giữ lại kết quả?"
     "Còn nếu dữ liệu không liền mạch thì sao?"
   CẤM câu đệm ra lệnh cho người nghe: "hãy chú ý", "lắng nghe", "cùng quan sát",
   "tiếp theo thôi" — chúng không nói gì cả.
4. VĂN NÓI, không phải văn viết. Cấm dùng "việc", "sự", "được thực hiện bởi".
   Câu chủ động, mệnh đề ngắn, như giảng viên đang nói chuyện với lớp.
5. Mỗi câu TỐI ĐA 30 âm tiết. Nhịp phải có lên có xuống, toàn câu 15–18 âm tiết thì
   nghe như đọc bản tin. Câu ngắn nên là câu DẪN DẮT hoặc câu hỏi — KHÔNG viết câu
   content rỗng chỉ để cho đủ nhịp.
   Slide thường chỉ có CỤM TỪ rời ("Mùng 1", "Câu Đối Đỏ"). Đừng đọc lại từng cụm thành
   từng câu cụt. NỐI chúng thành câu nói trọn vẹn, có chủ ngữ vị ngữ:
     SAI:  "Tết Nguyên Đán." "Lễ hội lớn nhất năm."
     ĐÚNG: "Tết Nguyên Đán là lễ hội lớn nhất trong năm."
   Một câu content được nối từ nhiều khối thì `ref` là khối mang ý CHÍNH.
6. KHÔNG đọc mã nguồn (nếu trang có). Cấm ký tự ( ) = [ ] _ và dạng a.b trong câu.
   Chỉ nói TÊN HÀM TRẦN và nó làm gì: "gọi savefig kèm tên file",
   không nói "plt.savefig('line_graph.png')".
7. KHỐI ẢNH LÀ ĐỂ HIỂU, KHÔNG PHẢI ĐỂ ĐỌC. Khán giả đang NHÌN THẤY ảnh — tả lại cái họ
   đang thấy là thừa và nghe rất máy.
   - Ảnh MINH HOẠ (ảnh chụp, hoa, pháo hoa, người, phong cảnh): KHÔNG tả màu sắc, bố cục,
     vị trí, ánh sáng. Dùng nó để biết trang nói về điều gì, rồi nói về ĐIỀU ĐÓ. Thường
     không cần câu nào trỏ vào ảnh minh hoạ cả.
       SAI:  "Bông hoa màu hồng nở rộ ở trung tâm, kèm nụ nhỏ và nền cành khô."
       SAI:  "Cảnh pháo hoa rực rỡ trên bầu trời đêm phía trên thành phố."
       ĐÚNG: không viết câu nào về ảnh — hoặc một ý ngắn gắn với chủ đề:
             "Nhắc tới giao thừa là nhắc tới pháo hoa."
   - Ảnh MANG THÔNG TIN (biểu đồ, sơ đồ, bảng, ảnh chụp màn hình kết quả): nói Ý CHÍNH
     người học cần rút ra — xu hướng, so sánh, kết luận. Không tả từng chi tiết.
8. Khối có provenance = vlm là mô tả do máy sinh, CÓ THỂ SAI.
   Câu trỏ vào khối vlm: KHÔNG nêu con số (kể cả viết bằng chữ như "từ một đến bốn"),
   KHÔNG nêu khoảng giá trị của trục, KHÔNG nêu tên riêng hay dịp lễ mà chữ trên slide
   không nhắc tới. Chỉ nói hình dạng, xu hướng, ý chính.
   Mỗi câu content phải được CHÍNH khối nó trỏ tới chứng minh. Khối tiêu đề chỉ chứng
   minh được tên chủ đề, không chứng minh được định nghĩa hay tính chất nào.
9. Nói VỀ CHỦ ĐỀ, không nói VỀ CÁI SLIDE. Bạn là giảng viên đang giảng, không phải người
   đang mô tả một trang giấy.
   CẤM: "trang này dạy", "trang dạy rằng", "thuật ngữ ở đây là", "slide này cho thấy",
        "như trên hình", "ví dụ minh họa này", "trong ảnh", "bức ảnh cho thấy",
        trích dẫn kiểu "[slide 7]".
   SAI:  "Trang này dạy <chủ đề>."
   ĐÚNG: nói thẳng nội dung của chủ đề, lấy từ NỘI DUNG TRANG.
   Không đọc danh sách dài theo từng dòng.
10. Bỏ qua chi tiết VẶT của ảnh chụp màn hình: chữ ở góc, thời gian chạy, màu giao diện,
    vị trí nút. Chỉ nói điều người học cần NHỚ.
11. Câu không có thông tin thì đừng viết. Nhắc lại tiêu đề trang ("Thuật ngữ ở đây là
    đồ thị dạng đường") không phải là một câu content.
12. `emphasis`: 0–2 từ cần nhấn giọng, lấy nguyên văn từ trong câu.
   `pause_before_ms`: 0 bình thường, 300–600 trước ý mới hoặc sau câu hỏi tu từ.
   `speed`: 1.0 bình thường, 0.9 cho câu quan trọng.

# Trả về JSON, không thêm gì khác

{
  "sentences": [
    {"kind": "delivery", "text": "...", "ref": null, "emphasis": [], "pause_before_ms": 0, "speed": 1.0},
    {"kind": "content", "text": "...", "ref": "p011.b02", "emphasis": ["savefig"], "pause_before_ms": 300, "speed": 1.0}
  ]
}
