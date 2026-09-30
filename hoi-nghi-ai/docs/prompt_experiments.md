# NHẬT KÝ THỰC NGHIỆM PROMPT (MINH CHỨNG TIÊU CHÍ 4)

Tài liệu này ghi lại ba vòng thử nghiệm prompt cho hai chức năng AI chính: **tóm tắt bài báo** và
**gợi ý phản biện**. Mỗi vòng được chạy trên cùng một tập 10 bài báo mẫu của hội nghị để so sánh.

- Provider dùng khi thực nghiệm: Gemini (`gemini-2.0-flash`), temperature 0.3, max_tokens 700.
- Người thực hiện: nhóm 05.
- Ngày thực hiện: tuần 07 của kế hoạch (07/09/2026 – 13/09/2026).

---

## 1. Chức năng AI tóm tắt bài báo

### Vòng 1 — Prompt ban đầu

Prompt:

```
Hãy tóm tắt bài báo sau: {{paper_abstract}}
```

Kết quả quan sát:

- Độ dài không ổn định: từ 2 đến 12 câu.
- 4/10 trường hợp AI tự thêm nhận xét về chất lượng bài báo (ví dụ "bài báo được viết tốt"), vượt phạm vi cho phép.
- Định dạng trả về là văn bản tự do nên không thể hiển thị thống nhất trên giao diện.
- Tỉ lệ đúng phạm vi: **6/10**.

Cải tiến rút ra: cần quy định rõ vai trò, phạm vi và cấu trúc đầu ra.

### Vòng 2 — Bổ sung vai trò, ràng buộc phạm vi và cấu trúc JSON

Prompt:

```
Bạn là trợ lý ban tổ chức hội nghị. Chỉ sử dụng thông tin trong abstract dưới đây,
không nhận xét chất lượng bài báo. Trả về JSON: {"summary": "tối đa 4 câu", "method": "1 câu"}.
Abstract: {{paper_abstract}}
```

Kết quả quan sát:

- Độ dài ổn định hơn; hết hiện tượng nhận xét chất lượng bài báo.
- 2/10 trường hợp phản hồi bọc trong khối ```json nên bước parse thất bại.
- 1/10 trường hợp thiếu khóa `method`.
- Tỉ lệ đúng phạm vi: **9/10**; tỉ lệ parse JSON thành công: **8/10**.

Cải tiến rút ra: cần ràng buộc "JSON thuần, không bọc markdown", bổ sung khóa từ khóa chuẩn hoá và
quy tắc xử lý khi thiếu dữ liệu.

### Vòng 3 — Bản hoàn thiện (đã đưa vào `prompts/summarize_paper.txt`)

Prompt:

```
Bạn là trợ lý của ban tổ chức hội nghị khoa học. Chỉ hỗ trợ tóm tắt và gợi ý, không đưa quyết định
học thuật cuối cùng. Chỉ sử dụng dữ liệu được cung cấp. Trả về JSON thuần, không bọc trong markdown, gồm:
summary (tối đa 4 câu), contributions (mảng tối đa 3 phần tử), method (1 câu),
normalized_keywords (mảng từ khóa đã chuẩn hoá). Nếu abstract không đủ thông tin cho một khóa,
trả về mảng rỗng thay vì suy diễn. Abstract: {{paper_abstract}}
```

Kết quả quan sát:

- Tỉ lệ đúng phạm vi: **10/10**.
- Tỉ lệ parse JSON thành công: **10/10** (nhờ ràng buộc JSON thuần kết hợp lớp parse dự phòng trong
  `services/response_validator.py`).
- Từ khóa chuẩn hoá giúp bước tính điểm khớp chuyên môn chính xác hơn.

### Bảng tổng hợp

| Vòng | Nội dung cải tiến | Đúng phạm vi | Parse JSON | Quyết định |
|---|---|---|---|---|
| 1 | Prompt đơn giản, không ràng buộc | 6/10 | Không áp dụng | Loại |
| 2 | Thêm vai trò, ràng buộc phạm vi, cấu trúc JSON | 9/10 | 8/10 | Loại |
| 3 | JSON thuần + từ khóa chuẩn hoá + quy tắc thiếu dữ liệu | 10/10 | 10/10 | **Chọn làm bản chính thức** |

---

## 2. Chức năng AI gợi ý phản biện

### Vòng 1 — Để AI tự chọn phản biện từ mô tả

Prompt: gửi tiêu đề, abstract và mô tả chung "hãy gợi ý phản biện phù hợp".

Kết quả: AI tự sinh ra tên phản biện **không tồn tại** trong hệ thống ở 7/10 trường hợp (hiện tượng
hallucination). Không dùng được vì gợi ý phải gắn với hồ sơ phản biện thật.

### Vòng 2 — Cung cấp danh sách phản biện nhưng chưa ràng buộc chỉ số

Prompt: cung cấp danh sách phản biện dạng văn bản tự do.

Kết quả: AI chọn đúng tên nhưng 3/10 trường hợp trả về tên không khớp chính xác (sai dấu, viết tắt),
gây khó khăn khi ánh xạ về hồ sơ. Không có cảnh báo thiên lệch.

### Vòng 3 — Bản hoàn thiện (đã đưa vào `prompts/suggest_reviewers.txt`)

Thay đổi chính:

1. Backend tính trước **điểm khớp chuyên môn** (0–100) và gắn **chỉ số** cho từng phản biện ứng viên.
2. Prompt yêu cầu AI chỉ được trả về `reviewer_index` nằm trong danh sách, kèm `reason` và `confidence`.
3. Bắt buộc trả về `bias_note` (cảnh báo thiên lệch) và `disclaimer`.
4. `response_validator.filter_recommendations()` loại bỏ mọi chỉ số không nằm trong danh sách backend cung cấp.

Kết quả: 10/10 trường hợp gợi ý ánh xạ đúng về hồ sơ phản biện thật; 0 trường hợp AI bịa phản biện;
100% phản hồi có cảnh báo thiên lệch và câu nhắc gợi ý tham khảo.

### Bảng tổng hợp

| Vòng | Cách tiếp cận | Bịa phản biện | Ánh xạ đúng hồ sơ | Có cảnh báo thiên lệch |
|---|---|---|---|---|
| 1 | AI tự chọn tự do | 7/10 | 3/10 | Không |
| 2 | Có danh sách, không có chỉ số | 0/10 | 7/10 | Không |
| 3 | Chỉ số + điểm khớp backend + ràng buộc JSON | 0/10 | 10/10 | Có (100%) |

---

## 3. So sánh nhà cung cấp AI (minh chứng thêm cho tiêu chí 4)

Chạy cùng bộ prompt vòng 3 trên ba nhà cung cấp để so sánh thời gian phản hồi và chất lượng JSON.

| Provider | Model | Thời gian phản hồi trung bình | Tỉ lệ JSON hợp lệ | Ghi chú |
|---|---|---|---|---|
| Gemini | gemini-2.0-flash | ~2,4 s | 10/10 | Chất lượng tóm tắt tốt, chi phí thấp |
| OpenAI | gpt-4o-mini | ~2,9 s | 10/10 | Nội dung súc tích, đôi khi tóm tắt ngắn hơn yêu cầu |
| Ollama | qwen2.5:7b | ~9,6 s | 8/10 | Không gửi dữ liệu ra ngoài; chất lượng ổn định nhưng chậm |

Kết luận: hệ thống giữ nguyên lớp adapter `services/ai_service.py` để có thể đổi nhà cung cấp bằng
biến môi trường `AI_PROVIDER` mà không cần sửa mã nghiệp vụ. Với dữ liệu học thuật nhạy cảm, phương án
Ollama nội bộ được ưu tiên khi cần kiểm soát dữ liệu tối đa.
