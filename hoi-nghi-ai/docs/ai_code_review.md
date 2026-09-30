# BIÊN BẢN REVIEW MÃ NGUỒN BẰNG AI (MINH CHỨNG TIÊU CHÍ 9)

Tài liệu ghi lại các phát hiện thực tế khi dùng AI (ChatGPT, Google Gemini, GitHub Copilot) để review
mã nguồn, cùng thay đổi đã áp dụng và kết quả kiểm thử lại.

Nguyên tắc: AI chỉ đề xuất; nhóm tự đọc lại mã nguồn, xác minh bằng test và chịu trách nhiệm về thay đổi cuối cùng.

---

## Phát hiện 1 — Thiếu kiểm soát quyền sở hữu ở endpoint xem chi tiết bài báo

**Mức độ:** Cao

**Prompt review đã dùng:**

```
Review endpoint GET /api/papers/{paper_id} trong FastAPI. Người dùng có vai trò author.
Hãy kiểm tra xem có lỗ hổng truy cập chéo dữ liệu (một tác giả xem được bài của tác giả khác) không
và chỉ ra cách sửa tối thiểu.
```

**Kết quả AI chỉ ra:** endpoint chỉ xác thực JWT (`Depends(get_current_user)`) mà không kiểm tra
`paper.submitted_by` có khớp với người gọi, cũng không kiểm tra phản biện có được phân công hay không.
Đây là lỗi IDOR (truy cập đối tượng trực tiếp không kiểm tra quyền).

**Thay đổi đã áp dụng:** bổ sung hàm `check_paper_access(db, paper, user)` được gọi trong mọi endpoint
đọc/ghi bài báo, áp dụng quy tắc:

- organizer: truy cập toàn bộ.
- author: chỉ bài có `submitted_by == user.id`.
- reviewer: chỉ bài có phân công thuộc hồ sơ phản biện của chính mình.

**Kiểm chứng:** thêm test `test_TC10_cross_author_access_forbidden`. Trước khi sửa, test Fail
(trả 200); sau khi sửa, test Pass (trả 403).

---

## Phát hiện 2 — Phản biện có thể gửi nhận xét cho phân công không thuộc về mình

**Mức độ:** Cao

**Prompt review đã dùng:**

```
Endpoint POST /api/assignments/{assignment_id}/review. Phản biện đã đăng nhập có thể gửi nhận xét cho
phân công của phản biện khác không? Nếu có, hãy viết điều kiện kiểm tra bổ sung.
```

**Kết quả AI chỉ ra:** chỉ kiểm tra `user.role == reviewer` mà chưa đối chiếu
`assignment.reviewer_profile_id` với hồ sơ phản biện của người gọi.

**Thay đổi đã áp dụng:** thêm truy vấn lấy hồ sơ phản biện của người gọi và so sánh với
`assignment.reviewer_profile_id`; nếu không khớp thì trả HTTP 403, đồng thời ghi `system_logs` để
phục vụ truy vết.

**Kiểm chứng:** thêm test `test_reviewer_cannot_review_others_assignment` → Pass (403).

---

## Phát hiện 3 — Kết quả AI ghi thẳng vào dữ liệu nghiệp vụ

**Mức độ:** Trung bình

**Kết quả AI chỉ ra:** việc lưu kết quả AI vào chính bảng nghiệp vụ khiến dữ liệu do máy sinh trộn lẫn
với dữ liệu do con người xác nhận, gây rủi ro về trách nhiệm học thuật.

**Thay đổi đã áp dụng:** tách hoàn toàn hai luồng dữ liệu. Kết quả AI lưu vào bảng `ai_generations`
(chỉ để tra cứu); muốn đưa vào dữ liệu nghiệp vụ phải qua endpoint xác nhận riêng do ban tổ chức bấm nút.
Kết quả AI luôn hiển thị nhãn "Gợi ý tham khảo từ AI".

---

## Phát hiện 4 — Prompt và dữ liệu nối chuỗi trực tiếp trong mã nguồn

**Mức độ:** Trung bình

**Kết quả AI chỉ ra:** prompt nằm rải rác trong mã khiến việc thay đổi tốn công và dễ vô tình gửi cả
trường định danh ra ngoài.

**Thay đổi đã áp dụng:** tách toàn bộ prompt ra thư mục `prompts/` dạng template với placeholder `{{...}}`;
thêm hàm `anonymize()` trong `services/ai_orchestrator.py` chạy trước khi ghép dữ liệu vào prompt.
Thêm test `test_TC_AI12_payload_has_no_pii` để chặn hồi quy.

---

## Phát hiện 5 — Không có giới hạn tần suất gọi AI

**Mức độ:** Trung bình

**Kết quả AI chỉ ra:** không có bộ đếm số lần gọi AI, có nguy cơ phát sinh chi phí và bị nhà cung cấp
chặn do vượt hạn mức.

**Thay đổi đã áp dụng:** cấu hình `AI_MAX_RETRIES`, `AI_TIMEOUT_SECONDS`, `AI_MAX_INPUT_CHARS` trong `.env`;
giới hạn số lần gọi AI theo người dùng trong khoảng thời gian và trả thông báo "vui lòng thử lại sau"
khi vượt ngưỡng. Mọi lần gọi đều được ghi vào `ai_logs` kèm thời gian xử lý và loại lỗi.

---

## Phát hiện 6 — Lỗi gọi AI chỉ in ra console

**Mức độ:** Thấp

**Kết quả AI chỉ ra:** lỗi AI không được lưu lại nên không thể đối chiếu khi cần kiểm tra chất lượng gợi ý.

**Thay đổi đã áp dụng:** ghi log lỗi vào bảng `ai_logs` với trường `error_type`
(`timeout` | `rate_limit` | `empty` | `bad_format` | `too_long` | `model_error`) và bổ sung màn hình
Nhật ký AI cho ban tổ chức.

---

## Phát hiện 7 — Giá trị mặc định cứng cho SECRET_KEY và chuỗi kết nối CSDL

**Mức độ:** Cao

**Kết quả AI chỉ ra:** `SECRET_KEY` có giá trị mặc định trong mã nguồn, dễ bị dùng nhầm khi triển khai.

**Thay đổi đã áp dụng:** chuyển toàn bộ sang đọc từ `.env`; thêm cảnh báo khi khởi động nếu
`SECRET_KEY` còn là giá trị mẫu; `.env` được đưa vào `.gitignore` và `.env.example` chỉ chứa tên biến.

---

## Phát hiện 8 — Hàm kiểm tra mốc thời gian hội nghị lặp lại ở nhiều endpoint

**Mức độ:** Thấp

**Kết quả AI chỉ ra:** cùng một logic kiểm tra thứ tự mốc thời gian xuất hiện ở ba nơi, dễ sửa sót.

**Thay đổi đã áp dụng:** gom về một điều kiện kiểm tra dùng chung trong `create_conference` và bổ sung
test `test_TC04_create_conference_invalid_timeline` để bảo vệ.

---

## Tổng hợp

| # | Vấn đề | Mức độ | Đã sửa | Test bảo vệ |
|---|---|---|---|---|
| 1 | Thiếu kiểm soát quyền sở hữu bài báo | Cao | Có | `test_TC10_cross_author_access_forbidden` |
| 2 | Phản biện gửi nhận xét trái phép | Cao | Có | `test_reviewer_cannot_review_others_assignment` |
| 3 | Kết quả AI ghi thẳng vào nghiệp vụ | Trung bình | Có | Kiểm tra qua `ai_generations` |
| 4 | Prompt nối chuỗi trong mã nguồn | Trung bình | Có | `test_TC_AI12_payload_has_no_pii` |
| 5 | Không giới hạn tần suất gọi AI | Trung bình | Có | Cấu hình `.env` + `ai_logs` |
| 6 | Lỗi AI không được lưu | Thấp | Có | Bảng `ai_logs` + màn hình nhật ký |
| 7 | Giá trị mặc định cứng cho SECRET_KEY | Cao | Có | `test_no_api_key_in_source` |
| 8 | Logic kiểm tra mốc thời gian lặp lại | Thấp | Có | `test_TC04_create_conference_invalid_timeline` |

Tổng cộng 8 phát hiện, trong đó 3 ở mức Cao, 3 ở mức Trung bình và 2 ở mức Thấp — tất cả đã được khắc
phục và có test hoặc cấu hình bảo vệ.
