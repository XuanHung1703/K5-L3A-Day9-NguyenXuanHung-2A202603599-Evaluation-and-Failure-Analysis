# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (Run ID report: `E-seeded_regression-20261117-b3e3`, item `E-002`, seed `11`) |
| Triệu chứng | `TrialPass` (`pass_rate`), `RefundAmountCorrect` và `DbFactKept` đều FAIL. Câu trả lời `reply` nói *"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."* và sổ cái (`ledger`) ghi `refund_vnd=20000, refund_count=1`, trong khi nhãn chuẩn (`label`) yêu cầu `status="denied", refund_vnd=0, refund_count=0`. |
| Bước sai đầu tiên | **Step 3** · `model_override` · `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | **Step 1 (`handoff`)** tạo yêu cầu tra cứu hợp lệ với quyền chỉ đọc (`lookup_order`, `lookup_policy`, `compute_compensation`). **Step 2 (`investigator`)** truy vấn DB chính xác cho đơn `O-202`: `{"visible": true, "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2, "shipping_fee_vnd": 20000}}` (đơn chỉ trễ 2 ngày, dưới ngưỡng 3 ngày của `SHIP-LATE-03`). Sai lầm bắt đầu tại **Step 3 (`model_override`)** khi agent tin lời khách khai trong ticket (*"Đơn giao trễ 5 ngày"*) và ghi đè `delay_days` từ `2` thành `5`, kéo theo **Step 4 (`quote`)** tính sai mức bồi thường thành `20.000đ`. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Trên `fixed C-002@11`: sau **Step 2 (`investigator`)** lấy `delay_days=2`, agent **không có Step `model_override`**, chuyển thẳng sang **Step 3 (`quote`)** với `{"amount_vnd": 0, "reason": "no_entitlement"}` và **Step 4 (`reply`)** từ chối hoàn tiền đúng chính sách (`ledger refund_vnd=0`, `status=denied`). |
| Regression test | `test_trace_case_c002_seed11_regression` và `test_reply_amount_matches_ledger_fm08` trong `src/tests/test_lab9_graders.py` (sử dụng `DbFactKept` và `RefundAmountCorrect`); đã xác nhận FAIL trên `seeded_regression` và PASS trên `fixed`. |
| Chưa chắc chắn | Trace chỉ cho thấy agent đã gọi `parse_delay_days(ticket)` và kích hoạt nhánh `model_override` ghi đè `order["delay_days"] = 5`, nhưng chỉ nhìn riêng một trace đơn lẻ thì không phân biệt được lỗi này luôn xảy ra ở mọi seed (`ticket_trust`) hay chỉ xảy ra theo chu kỳ seed (`seed % 5 == 0` như ở `swarm`) nếu không chạy trên nhiều seed. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
