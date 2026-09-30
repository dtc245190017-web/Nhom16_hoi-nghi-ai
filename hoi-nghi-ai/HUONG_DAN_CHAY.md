# HƯỚNG DẪN CHẠY — Hệ thống quản lý hội nghị khoa học có tích hợp AI

## Bước 1. Chuẩn bị môi trường

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Bước 2. Cấu hình

Sao chép `.env.example` thành `.env`:

```bash
cp .env.example .env
```

Giá trị quan trọng:

| Biến | Ý nghĩa | Giá trị mặc định |
|---|---|---|
| `DATABASE_URL` | Chuỗi kết nối CSDL | `sqlite:///./hoi_nghi_ai.db` |
| `SECRET_KEY` | Khoá ký JWT, phải đổi khi triển khai | giá trị mẫu |
| `AI_PROVIDER` | Nhà cung cấp AI | `mock` |
| `AI_API_KEY` | Khoá API của nhà cung cấp | để trống |
| `AI_MAX_INPUT_CHARS` | Giới hạn độ dài dữ liệu gửi AI | `6000` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Tài khoản ban tổ chức khởi tạo | `organizer@hoinghi.vn` / `organizer123` |

> Không đưa `.env` lên Git. Khi triển khai thật, bắt buộc đổi `SECRET_KEY` và đặt
> `AI_PROVIDER` khác `mock`.

## Bước 3. Chạy hệ thống

```bash
uvicorn main:app --reload --port 8000
```

- Trang chính: `http://localhost:8000`
- Trang đăng nhập: `http://localhost:8000/login`
- Trang quản trị: `http://localhost:8000/admin`
- Tài liệu API tự sinh: `http://localhost:8000/docs`

Cơ sở dữ liệu SQLite được tạo tự động trong lần chạy đầu, kèm dữ liệu khởi tạo
(lĩnh vực chuyên môn, tài khoản ban tổ chức, hai hồ sơ phản biện mẫu, mẫu email).

## Bước 4. Chạy kiểm thử

```bash
pytest -v
```

Bộ test dùng CSDL riêng `test_hoi_nghi_ai.db` và provider `mock`, không tiêu tốn hạn mức AI.

## Bước 5. Dùng với nhà cung cấp AI thật

```env
AI_PROVIDER=gemini
AI_API_KEY=<khoá API của bạn>
AI_MODEL=gemini-2.0-flash
```

Với phương án chạy AI nội bộ (không gửi dữ liệu ra ngoài):

```env
AI_PROVIDER=ollama
AI_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
```

## Bước 6. Triển khai với MySQL

1. Tạo CSDL `hoi_nghi_ai` trên MySQL.
2. Chạy `migrations/001_init.sql` để tạo bảng.
3. Đặt `DATABASE_URL=mysql+pymysql://user:password@localhost:3306/hoi_nghi_ai`.
4. Chạy lại `uvicorn main:app --host 0.0.0.0 --port 8000`.

## Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: fastapi` | Chưa cài phụ thuộc | `pip install -r requirements.txt` |
| Chức năng AI trả về `source: fallback` | Sai API Key, hết hạn mức hoặc AI trả JSON không đọc được | Kiểm tra `ai_logs`, xem trường `error_type` |
| `Phiên đăng nhập không hợp lệ` | Token hết hạn | Đăng nhập lại |
| Không tạo được phiên trình bày | Bài báo chưa ở trạng thái `accepted` | Chuyển trạng thái bài báo trước |
| Cảnh báo `SECRET_KEY` còn là giá trị mẫu | Chưa đổi `.env` | Đặt chuỗi ngẫu nhiên ≥ 32 ký tự |
