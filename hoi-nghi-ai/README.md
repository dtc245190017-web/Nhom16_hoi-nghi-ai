# Hệ thống quản lý hội nghị khoa học có tích hợp AI

Dự án môn **Ứng dụng Trí tuệ nhân tạo** — nhóm 05.

Hệ thống hỗ trợ ban tổ chức hội nghị khoa học quản lý hội nghị, bài báo nộp, phản biện, phiên trình
bày và đăng ký tham dự; đồng thời tích hợp ba chức năng AI: **tóm tắt bài báo**, **gợi ý phản biện**
và **sinh nháp email thông báo**.

## 1. Kiến trúc

Hệ thống theo kiến trúc bốn lớp:

| Lớp | Thành phần | Công nghệ |
|---|---|---|
| Giao diện (client) | Trang đăng nhập, trang nghiệp vụ, trang quản trị | HTML, CSS, JavaScript thuần |
| Ứng dụng (application) | REST API, xác thực, phân quyền, quy tắc nghiệp vụ | FastAPI, Pydantic, python-jose |
| Dữ liệu (data) | 22 bảng, truy vấn qua ORM | SQLAlchemy, SQLite (kiểm thử) / MySQL (triển khai) |
| AI (integration) | Adapter nhà cung cấp, dựng prompt, điều phối, kiểm tra kết quả | Gemini / OpenAI / Ollama / mock |

## 2. Cấu trúc thư mục

```
hoi_nghi_ai/
├── main.py                     # API chính, xác thực, phân quyền, nghiệp vụ
├── models.py                   # 22 bảng dữ liệu
├── database.py                 # Kết nối cơ sở dữ liệu
├── requirements.txt
├── .env.example
├── migrations/001_init.sql     # Script tạo bảng cho MySQL/PostgreSQL
├── prompts/                    # Prompt tách riêng khỏi mã nguồn
│   ├── summarize_paper.txt
│   ├── suggest_reviewers.txt
│   └── email_notification.txt
├── services/
│   ├── ai_service.py           # Adapter nhà cung cấp AI, thử lại, phân loại lỗi
│   ├── prompt_builder.py       # Ghép template prompt + quy tắc chung
│   ├── response_validator.py   # Phân tích JSON, chặn dữ liệu AI bịa
│   └── ai_orchestrator.py      # Điều phối, ghi nhật ký, kết quả dự phòng
├── static/                     # Giao diện
├── tests/test_api.py           # Bộ test tự động (chức năng, AI, bảo mật)
└── docs/
    ├── prompt_experiments.md   # Nhật ký tối ưu prompt (3 vòng)
    └── ai_code_review.md       # Biên bản review mã nguồn bằng AI
```

## 3. Ba chức năng AI

| Mã | Chức năng | Đầu vào | Đầu ra | Dự phòng khi AI lỗi |
|---|---|---|---|---|
| AI01 | Tóm tắt bài báo | Tiêu đề, abstract, từ khóa, lĩnh vực | JSON: summary, contributions, method, normalized_keywords | Tóm tắt trích dẫn nội bộ từ abstract |
| AI02 | Gợi ý phản biện | Bài báo + danh sách ứng viên kèm điểm khớp do hệ thống tính | JSON: recommendations (chỉ số), bias_note, disclaimer | Xếp hạng theo điểm khớp chuyên môn |
| AI03 | Sinh nháp email | Loại thông báo, mẫu email, dữ liệu hội nghị | JSON: subject, body, missing_fields | Điền mẫu email có sẵn trong CSDL |

Nguyên tắc chung:

1. AI chỉ **đề xuất**, không quyết định học thuật cuối cùng; mọi kết quả đều gắn nhãn gợi ý tham khảo.
2. Kết quả AI lưu vào bảng riêng `ai_generations`, không trộn với dữ liệu do con người xác nhận.
3. Dữ liệu gửi ra ngoài đã được loại bỏ trường định danh cá nhân (`anonymize()`).
4. Mọi lần gọi AI đều ghi `ai_logs` (loại tác vụ, provider, thời gian xử lý, loại lỗi).
5. Khi AI lỗi hoặc trả về dữ liệu không đọc được, hệ thống tự chuyển sang kết quả nội bộ (fallback).

## 4. Cấu hình nhà cung cấp AI

Đổi nhà cung cấp chỉ cần sửa `.env`, không phải sửa mã nghiệp vụ:

```
AI_PROVIDER=mock          # mock | gemini | openai | ollama
AI_API_KEY=...
AI_MODEL=gemini-2.0-flash
```

`AI_PROVIDER=mock` là mặc định: hệ thống chạy đầy đủ chức năng mà không cần API Key, dùng cho
kiểm thử tự động và chạy thử.

## 5. Kiểm thử

```bash
pip install -r requirements.txt
pytest -v
```

Bộ test gồm ba nhóm: nghiệp vụ (đúng/sai/biên), chức năng AI (đúng/sai/biên, có mô phỏng lỗi
provider), và bảo mật (truy cập chéo dữ liệu, endpoint thiếu token, không lộ API Key trong mã nguồn).

## 6. Chạy hệ thống

```bash
uvicorn main:app --reload --port 8000
```

Mở `http://localhost:8000`. Tài khoản ban tổ chức mặc định lấy từ `.env`
(`ADMIN_EMAIL` / `ADMIN_PASSWORD`, mặc định `organizer@hoinghi.vn` / `organizer123`).
