# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok (`data/eval/judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | **Có** (`{'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}`, fail rate observed `0.280` → corrected `0.300`) | **dùng** (theo dõi/chấm văn phong) |
| helpful (`data/eval/judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | 0.300 | **Không** (`{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}`, fail rate observed `0.090` → corrected `0.300`) | **loại** (cấm dùng làm gate) |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa Rubric |
|---|---|---|---|---|---|
| 1 | `H-008` ("Em đã hoàn tiền cho anh rồi nha, anh check giúp em.") | PASS | FAIL | **Người đúng** (FN) | Xưng "em" + "nha" quá suồng sã trong CSKH LogiX. **Sửa rubric `tone_ok`**: quy định bắt buộc đại từ xưng hô chuẩn ("LogiX" – "anh/chị") và cấm khẩu ngữ suồng sã ("nha", "nhé"). |
| 2 | `H-029` ("Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm.") | PASS | FAIL | **Người đúng** (FN) | Giọng điệu mệnh lệnh/đuổi khách ("không cần nhắn thêm"), nhưng judge bị đánh lừa bởi từ mở đầu "Dạ, vui lòng". **Sửa rubric `tone_ok`**: cấm các cụm từ chặn tương tác của khách dù có kính ngữ đầu câu. |
| 3 | `H-042` ("Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ.") | FAIL | PASS | **Người đúng** (FP) | Câu trả lời lịch sự, ngắn gọn, đủ thông tin nhưng judge bắt lỗi vì thiếu câu xin lỗi dài dòng. **Sửa rubric `tone_ok`**: không bắt buộc xin lỗi khi thông báo hoàn tiền thành công, tránh thiên vị độ dài (verbosity bias). |
| 4 | `H-051` ("Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ.") | FAIL | PASS | **Người đúng** (FP) | Thuật ngữ "refund" nằm trong danh mục từ vựng CSKH cho phép, nhưng judge phạt vì xen tiếng Anh. **Sửa rubric `tone_ok`**: bổ sung danh sách thuật ngữ chuyên ngành được phép dùng (`refund`, `order`, `voucher`). |
| 5 | `H-070` ("Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂") | PASS | FAIL | **Người đúng** (FN) | Dùng emoji cười cợt (`😂😂`) trong ngữ cảnh xử lý khiếu nại. **Sửa rubric `tone_ok`**: cấm hoàn toàn emoji biểu cảm cợt nhả trong phản hồi giải quyết khiếu nại. |
| 6 | `H-081` ("Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ.") | FAIL | PASS | **Judge đúng** (Lỗi gán nhãn người) | Câu từ chối thiếu câu mở đường hỗ trợ thêm chuẩn mực (hoặc người gán nhãn đọc nhầm). **Hành động**: rà soát lại hướng dẫn gán nhãn cho annotator con người và đồng bộ mẫu câu từ chối chuẩn. |
| 7 | `HL-016` ("Dạ, LogiX thành thật xin lỗi... LogiX đã hoàn 55.000đ cho đơn O-404...") | PASS | FAIL | **Người đúng** (FN của `helpful`) | Ledger thực tế chỉ ghi `35.000đ` nhưng reply báo `55.000đ` (`FM-08`). Judge `helpful` thấy lời xin lỗi dài dòng, lịch sự nên chấm PASS. **Hành động**: loại bỏ hoàn toàn `helpful` judge, chuyển kiểm tra khớp tiền sang code grader (`ReplyAmountMatchesLedger`). |

## Kết luận
- **Tiêu chí bị loại và lý do**:
  - Loại bỏ hoàn toàn **`helpful`** khỏi hệ thống đánh giá và CI Gate vì **Recall chỉ đạt `0.300`** (thấp hơn rất nhiều so với sàn `0.70`) và **$\kappa = 0.375 < 0.60$**.
  - Ma trận nhầm lẫn của `helpful` (`{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}`) cho thấy trong 30 trường hợp thực sự lỗi (`human=FAIL`), judge bỏ lọt tới **21 trường hợp (`FN = 21`)**, kéo tỉ lệ lỗi quan sát được xuống chỉ còn `9.0%` trong khi tỉ lệ lỗi thực sau hiệu chỉnh Rogan-Gladen là `30.0%`.
  - Nguyên nhân gốc rễ: `helpful` gộp chung đánh giá văn phong với độ đúng nghiệp vụ (số tiền hoàn), khiến LLM Judge mắc **thiên kiến ưa văn phong dài dòng/nịnh khách (sycophancy & verbosity bias)** — cứ thấy câu trả lời xin lỗi tha thiết (`HL-016`, `HL-028`, `HL-035`, `HL-041`) là chấm `PASS` dù Agent nói sai số tiền so với sổ cái (`ledger`). Theo nguyên tắc thiết kế eval: **tiền bạc và phê duyệt bắt buộc chấm bằng code grader, không bao giờ dùng LLM Judge**.
- **Rủi ro còn lại**:
  - Trọng tài `tone_ok` dù đạt chuẩn ($\kappa = 0.757, P = 0.857, R = 0.800$) nhưng hiện mới chỉ được kiểm định trên tập dữ liệu replay công khai (`n = 100`). Nếu sửa prompt/rubric của judge theo 6 điểm audit ở trên, bắt buộc phải thu thập và gán nhãn một **tập held-out mới hoàn toàn** để kiểm định lại trước khi đưa vào vận hành thực tế.
