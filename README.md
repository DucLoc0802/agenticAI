# BTVN#3 - Flight Booking Agent bằng LangChain + LangGraph

Project mô phỏng **Agent đặt vé máy bay** trong một file `app.py`.

Agent có 3 chiến lược:

- `react` - ReAct: quan sát kết quả rồi quyết định bước tiếp theo.
- `plan` - Plan-then-Execute: chạy theo kế hoạch cố định, lỗi thì handoff.
- `hybrid` - Hybrid: có kế hoạch nhưng có thể replan khi gặp lỗi.

Project cũng cài đặt 4 lớp Harness theo yêu cầu bài tập:

1. Data constraints
2. Completion check bằng code
3. Permission check
4. Handoff

---

## 1. Cài đặt thư viện

Mở Terminal tại thư mục chứa `app.py`, sau đó chạy:

```bash
pip install langchain langgraph pydantic
```

---

## 2. Chạy Agent

### ReAct

```bash
python app.py --strategy react --approve
```

### Plan-then-Execute

```bash
python app.py --strategy plan --approve
```

### Hybrid

```bash
python app.py --strategy hybrid --approve
```

Tham số `--approve` có nghĩa là người dùng cho phép Agent thực hiện hành động `book_flight`.

Nếu không có `--approve`:

```bash
python app.py --strategy react
```

Harness sẽ chặn hành động đặt vé và chuyển sang **HANDOFF** vì `book_flight` là hành động WRITE cần quyền của người dùng.

---

## 3. Test tình huống chuyến bay thay đổi

Dùng `--fault` để giả lập lần đặt vé đầu tiên gặp lỗi `FLIGHT_CHANGED`.

### ReAct

```bash
python app.py --strategy react --approve --fault
```

ReAct sẽ quan sát lỗi, tìm lại chuyến và thử phương án khác.

### Plan-then-Execute

```bash
python app.py --strategy plan --approve --fault
```

Plan-then-Execute không replan nên khi kế hoạch thất bại sẽ chuyển sang handoff.

### Hybrid

```bash
python app.py --strategy hybrid --approve --fault
```

Hybrid sẽ replan rồi tiếp tục thực hiện kế hoạch mới.

---

## 4. Đánh giá 3 chiến lược

Chạy:

```bash
python app.py --evaluate
```

Chương trình sẽ chạy 4 tình huống kiểm thử:

- `normal` - đặt vé bình thường
- `flight_changed` - chuyến đã chọn bị thay đổi
- `low_budget` - không có chuyến phù hợp ngân sách
- `not_approved` - người dùng chưa cho phép đặt vé

Kết quả sẽ hiển thị dạng:

```text
Strategy  Book    Safe    Avg calls   Avg sec
react     ...     ...     ...         ...
plan      ...     ...     ...         ...
hybrid    ...     ...     ...         ...
```

Các chỉ số dùng để so sánh:

- `Book`: số trường hợp cần đặt vé và Agent đặt thành công.
- `Safe`: số trường hợp không nên đặt vé và Agent dừng/handoff an toàn.
- `Avg calls`: số lần gọi tool trung bình.
- `Avg sec`: thời gian chạy trung bình.

---

## 5. Ý nghĩa các tham số

| Tham số | Ý nghĩa |
|---|---|
| `--strategy react` | Chạy Agent theo ReAct |
| `--strategy plan` | Chạy Plan-then-Execute |
| `--strategy hybrid` | Chạy Hybrid |
| `--approve` | Cho phép thực hiện `book_flight` |
| `--fault` | Giả lập lần book đầu bị `FLIGHT_CHANGED` |
| `--evaluate` | Chạy bộ đánh giá cả 3 chiến lược |

---

## 6. Ví dụ chạy nhanh

```bash
# ReAct bình thường
python app.py --strategy react --approve

# Hybrid khi chuyến bay thay đổi
python app.py --strategy hybrid --approve --fault

# Test permission: không cấp quyền đặt vé
python app.py --strategy react

# So sánh cả 3 mẫu thiết kế
python app.py --evaluate
```

---

## 7. Cấu trúc chương trình

Toàn bộ code chính nằm trong một file:

```text
app.py
```

Các phần quan trọng trong file:

```text
BookingRequest
    -> ràng buộc dữ liệu đầu vào

FlightHarness
    -> validate_data()
    -> complete()
    -> allowed()
    -> handoff()

make_tools()
    -> search_flights
    -> book_flight
    -> verify_booking
    -> handoff

run_react()
    -> ReAct

run_plan()
    -> Plan-then-Execute

run_hybrid()
    -> Hybrid

evaluate()
    -> đánh giá 3 chiến lược
```

---

## 8. Kết luận ngắn

- **ReAct** linh hoạt vì quyết định lại sau mỗi observation.
- **Plan-then-Execute** đơn giản, dễ theo dõi nhưng không thích nghi tốt khi kế hoạch ban đầu gặp lỗi.
- **Hybrid** kết hợp ưu điểm của planning và khả năng replan khi môi trường thay đổi.
