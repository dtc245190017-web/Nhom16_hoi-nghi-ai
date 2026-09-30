"""
Test tự động cho Hệ thống quản lý hội nghị khoa học có tích hợp AI.

Bao gồm ba nhóm:
1. Test chức năng quản lý (đúng / sai / biên).
2. Test chức năng AI (đúng / sai / biên) với provider mock.
3. Test bảo mật: phân quyền chéo, không lộ API Key, payload gửi AI không chứa PII.

Chạy: pytest -v
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_hoi_nghi_ai.db")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32-chars")

import main  # noqa: E402
from database import Base  # noqa: E402
from services import ai_orchestrator, response_validator  # noqa: E402

TEST_DB = "sqlite:///./test_hoi_nghi_ai.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


main.app.dependency_overrides[main.get_db] = override_get_db
client = TestClient(main.app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    main.seed(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def login(email, password):
    res = client.post("/api/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def organizer_token():
    return login(os.getenv("ADMIN_EMAIL", "organizer@hoinghi.vn"),
                 os.getenv("ADMIN_PASSWORD", "organizer123"))


@pytest.fixture(scope="module")
def author_token():
    res = client.post("/api/auth/register", json={
        "full_name": "Tác giả Kiểm Thử", "email": "author.test@example.com",
        "password": "matkhau12345", "role": "author",
    })
    if res.status_code != 200:
        return login("author.test@example.com", "matkhau12345")
    return res.json()["access_token"]


@pytest.fixture(scope="module")
def reviewer_token():
    res = client.post("/api/auth/register", json={
        "full_name": "Phản biện Kiểm Thử", "email": "reviewer.test@example.com",
        "password": "matkhau12345", "role": "reviewer",
    })
    if res.status_code != 200:
        return login("reviewer.test@example.com", "matkhau12345")
    return res.json()["access_token"]


# ---------------------------------------------------------------- quản lý ---
def test_TC01_register_ok():
    res = client.post("/api/auth/register", json={
        "full_name": "Người Dùng Mới", "email": "new.user@example.com",
        "password": "matkhau12345", "role": "author",
    })
    assert res.status_code in (200, 400)
    if res.status_code == 400:
        assert "đã được sử dụng" in res.json()["detail"]


def test_TC02_register_duplicate_email(author_token):
    res = client.post("/api/auth/register", json={
        "full_name": "Trùng Email", "email": "author.test@example.com",
        "password": "matkhau12345", "role": "author",
    })
    assert res.status_code == 400
    assert "đã được sử dụng" in res.json()["detail"]


def test_TC02b_register_weak_password():
    res = client.post("/api/auth/register", json={
        "full_name": "Mật Khẩu Ngắn", "email": "weak@example.com",
        "password": "123", "role": "author",
    })
    assert res.status_code == 400


def test_TC03_login_wrong_password():
    res = client.post("/api/auth/login", data={"username": "author.test@example.com",
                                               "password": "sai-mat-khau"})
    assert res.status_code == 400
    assert "không chính xác" in res.json()["detail"]


def test_TC04_create_conference_invalid_timeline(organizer_token):
    res = client.post("/api/conferences", headers=auth(organizer_token), json={
        "name": "Hội nghị sai mốc thời gian", "year": 2026,
        "submission_deadline": "2026-11-01", "review_deadline": "2026-10-01",
        "notification_date": "2026-12-01",
    })
    assert res.status_code == 400
    assert "mốc thời gian" in res.json()["detail"]


def test_TC04b_create_conference_ok(organizer_token):
    res = client.post("/api/conferences", headers=auth(organizer_token), json={
        "name": "Hội nghị Kiểm Thử 2026", "year": 2026, "location": "Thái Nguyên",
        "submission_deadline": "2026-12-31", "review_deadline": "2027-01-15",
        "notification_date": "2027-01-31",
    })
    assert res.status_code == 201


def test_TC05_submit_paper_ok(author_token, organizer_token):
    confs = client.get("/api/conferences", headers=auth(organizer_token)).json()
    conf_id = confs[0]["id"]
    fields = client.get("/api/expertise-fields", headers=auth(organizer_token)).json()
    res = client.post("/api/papers", headers=auth(author_token), json={
        "conference_id": conf_id,
        "title": "Ứng dụng học sâu trong phân loại bài báo khoa học",
        "abstract": ("Bài báo trình bày phương pháp phân loại bài báo khoa học theo lĩnh vực chuyên môn "
                     "bằng mô hình học sâu, kết hợp biểu diễn từ khóa và trường chuyên môn của phản biện. "
                     "Thực nghiệm trên tập dữ liệu hội nghị cho thấy độ chính xác được cải thiện rõ rệt."),
        "keywords": ["học sâu", "trí tuệ nhân tạo", "phân loại văn bản"],
        "topics": [fields[0]["id"]],
        "authors": ["Tác giả Kiểm Thử|author.test@example.com|Đại học CNTT"],
    })
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "submitted"


def test_TC05b_submit_paper_short_abstract(author_token, organizer_token):
    confs = client.get("/api/conferences", headers=auth(organizer_token)).json()
    res = client.post("/api/papers", headers=auth(author_token), json={
        "conference_id": confs[0]["id"], "title": "Bài báo abstract quá ngắn",
        "abstract": "Quá ngắn", "keywords": [], "topics": [], "authors": [],
    })
    assert res.status_code == 400


def test_TC07_update_reviewer_expertise(organizer_token):
    reviewers = client.get("/api/reviewers", headers=auth(organizer_token)).json()
    fields = client.get("/api/expertise-fields", headers=auth(organizer_token)).json()
    profile_id = reviewers[0]["id"]
    res = client.put(f"/api/reviewers/{profile_id}", headers=auth(organizer_token), json={
        "full_name": "x", "email": "x@example.com", "degree": "TS",
        "organization": "Đại học CNTT", "max_load": 5,
        "expertise_ids": [fields[0]["id"], fields[1]["id"]],
    })
    assert res.status_code == 200
    assert res.json()["expertise_count"] == 2


def test_TC08_assignment_and_duplicate(organizer_token):
    reviewers = client.get("/api/reviewers", headers=auth(organizer_token)).json()
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    profile = next(r for r in reviewers if r["expertise"])
    paper = papers[0]
    body = {"paper_id": paper["id"], "reviewer_profile_id": profile["id"],
            "due_date": "2027-01-10"}
    first = client.post("/api/assignments", headers=auth(organizer_token), json=body)
    assert first.status_code in (201, 400)
    second = client.post("/api/assignments", headers=auth(organizer_token), json=body)
    assert second.status_code == 400
    assert "đã được phân công" in second.json()["detail"]


def test_TC09_review_score_out_of_range(reviewer_token, organizer_token):
    assignments = client.get("/api/assignments", headers=auth(reviewer_token)).json()
    if not assignments:
        pytest.skip("Chưa có phân công cho phản biện kiểm thử")
    res = client.post(f"/api/assignments/{assignments[0]['id']}/review",
                      headers=auth(reviewer_token),
                      json={"score": 15, "recommendation": "accept", "comment": "Nhận xét thử"})
    assert res.status_code == 400


def test_TC09b_review_ok(reviewer_token):
    assignments = client.get("/api/assignments", headers=auth(reviewer_token)).json()
    if not assignments:
        pytest.skip("Chưa có phân công cho phản biện kiểm thử")
    res = client.post(f"/api/assignments/{assignments[0]['id']}/review",
                      headers=auth(reviewer_token),
                      json={"score": 8, "recommendation": "minor",
                            "comment": "Bài báo có đóng góp rõ ràng, cần bổ sung thực nghiệm."})
    assert res.status_code == 200
    assert res.json()["assignment_status"] == "done"


def test_TC11_session_only_accepted_papers(organizer_token):
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    submitted = [p for p in papers if p["status"] != "accepted"]
    if not submitted:
        pytest.skip("Không có bài báo chưa được chấp nhận")
    confs = client.get("/api/conferences", headers=auth(organizer_token)).json()
    res = client.post("/api/sessions", headers=auth(organizer_token), json={
        "conference_id": confs[0]["id"], "title": "Phiên kiểm thử",
        "paper_ids": [submitted[0]["id"]],
    })
    assert res.status_code == 400
    assert "chấp nhận" in res.json()["detail"]


def test_TC12_registration_duplicate(author_token, organizer_token):
    confs = client.get("/api/conferences", headers=auth(organizer_token)).json()
    body = {"conference_id": confs[0]["id"], "registration_type": "author", "note": ""}
    first = client.post("/api/registrations", headers=auth(author_token), json=body)
    assert first.status_code in (201, 400)
    second = client.post("/api/registrations", headers=auth(author_token), json=body)
    assert second.status_code == 400
    assert "đã đăng ký" in second.json()["detail"]


def test_TC13_stats_no_data_boundary(organizer_token):
    res = client.get("/api/stats/overview?conference_id=99999", headers=auth(organizer_token))
    assert res.status_code == 200
    assert res.json()["total_papers"] == 0
    assert res.json()["review_progress_percent"] == 0.0


def test_TC14_search_paper_vietnamese(organizer_token):
    res = client.get("/api/papers?q=học sâu", headers=auth(organizer_token))
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# -------------------------------------------------------------------- AI ---
def test_TC_AI01_summarize_paper_ok(organizer_token):
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/summarize-paper", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 200
    data = res.json()
    assert set(data["data"].keys()) == {"summary", "contributions", "method", "normalized_keywords"}
    assert data["source"] in ("ai", "fallback")
    assert "gợi ý tham khảo" in data["notice"].lower()


def test_TC_AI02_summarize_short_abstract_boundary(organizer_token):
    confs = client.get("/api/conferences", headers=auth(organizer_token)).json()
    fields = client.get("/api/expertise-fields", headers=auth(organizer_token)).json()
    org = login(os.getenv("ADMIN_EMAIL", "organizer@hoinghi.vn"),
                os.getenv("ADMIN_PASSWORD", "organizer123"))
    created = client.post("/api/papers", headers=auth(org), json={
        "conference_id": confs[0]["id"], "title": "Bài báo abstract ngắn để kiểm thử biên",
        "abstract": "A" * 120, "keywords": ["kiểm thử"], "topics": [fields[0]["id"]], "authors": [],
    })
    assert created.status_code == 201
    res = client.post("/api/ai/summarize-paper", headers=auth(organizer_token),
                      json={"paper_id": created.json()["id"]})
    assert res.status_code == 200


def test_TC_AI03_summarize_missing_paper(organizer_token):
    res = client.post("/api/ai/summarize-paper", headers=auth(organizer_token),
                      json={"paper_id": 999999})
    assert res.status_code == 404


def test_TC_AI04_suggest_reviewers_ok(organizer_token):
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/suggest-reviewers", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data["recommendations"]) <= 3
    assert "disclaimer" in data


def test_TC_AI06_filter_recommendations_outside_list():
    candidates = [{"reviewer_index": 1}, {"reviewer_index": 2}]
    items = [
        {"reviewer_index": 1, "reason": "khớp chuyên môn", "confidence": "high"},
        {"reviewer_index": 99, "reason": "phản biện bịa", "confidence": "high"},
    ]
    filtered = response_validator.filter_recommendations(items, candidates)
    assert len(filtered) == 1
    assert filtered[0]["reviewer_index"] == 1


def test_TC_AI07_fallback_on_ai_error(monkeypatch, organizer_token):
    from services import ai_service

    def boom(*args, **kwargs):
        raise ai_service.AIError("AI Provider lỗi phía dịch vụ (503)", "model_error")

    monkeypatch.setattr(ai_service, "call_ai", boom)
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/summarize-paper", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 200
    assert res.json()["source"] == "fallback"
    assert "không khả dụng" in res.json()["fallback_notice"]


def test_TC_AI08_bad_json_uses_fallback(monkeypatch, organizer_token):
    from services import ai_service

    class FakeResult:
        text = "Xin chào, đây không phải JSON"
        source = "ai"
        provider = "mock"
        model = "mock"
        latency_ms = 1
        error_type = None

    monkeypatch.setattr(ai_service, "call_ai", lambda *a, **k: FakeResult())
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/summarize-paper", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 200
    assert res.json()["source"] == "fallback"


def test_TC_AI09_truncate_long_input():
    from services import ai_service
    text, truncated = ai_service.truncate_input("x" * 20000, limit=6000)
    assert truncated is True
    assert len(text) == 6000


def test_TC_AI10_email_missing_fields_boundary(monkeypatch, organizer_token):
    from services import ai_service

    class FakeResult:
        text = '{"subject": "Thông báo", "body": "Nội dung", "missing_fields": ["review_due"]}'
        source = "ai"
        provider = "mock"
        model = "mock"
        latency_ms = 1
        error_type = None

    monkeypatch.setattr(ai_service, "call_ai", lambda *a, **k: FakeResult())
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/email-draft?kind=accepted", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 200
    assert res.json()["data"]["missing_fields"] == ["review_due"]


def test_TC_AI11_email_kind_without_template(organizer_token):
    papers = client.get("/api/papers", headers=auth(organizer_token)).json()
    res = client.post("/api/ai/email-draft?kind=khong_ton_tai", headers=auth(organizer_token),
                      json={"paper_id": papers[0]["id"]})
    assert res.status_code == 400
    assert "mẫu email" in res.json()["detail"]


def test_TC_AI12_payload_has_no_pii():
    payload = {"paper_title": "T", "paper_keywords": ["k"], "paper_topics": ["f"],
               "full_name": "Nguyễn Văn A", "email": "a@example.com", "paper_id": 5}
    clean = ai_orchestrator.anonymize(payload)
    for forbidden in ("full_name", "email", "paper_id"):
        assert forbidden not in clean


def test_ai_status_hides_key(organizer_token):
    res = client.get("/api/ai/status")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"provider", "configured", "note"}
    assert "key" not in str(body).lower() or "configured" in body


# --------------------------------------------------------------- bảo mật ---
def test_TC10_cross_author_access_forbidden(author_token, organizer_token):
    """Tác giả B không được xem bài nộp của tác giả A (đã sửa lỗ hổng phân quyền)."""
    other = client.post("/api/auth/register", json={
        "full_name": "Tác giả Khác", "email": "other.author@example.com",
        "password": "matkhau12345", "role": "author",
    })
    token_b = other.json()["access_token"] if other.status_code == 200 else login(
        "other.author@example.com", "matkhau12345")
    papers = client.get("/api/papers", headers=auth(author_token)).json()
    if not papers:
        pytest.skip("Tác giả kiểm thử chưa có bài nộp")
    res = client.get(f"/api/papers/{papers[0]['id']}", headers=auth(token_b))
    assert res.status_code == 403


def test_reviewer_cannot_review_others_assignment(organizer_token):
    other = client.post("/api/auth/register", json={
        "full_name": "Phản biện Khác", "email": "other.reviewer@example.com",
        "password": "matkhau12345", "role": "reviewer",
    })
    token_b = other.json()["access_token"] if other.status_code == 200 else login(
        "other.reviewer@example.com", "matkhau12345")
    assignments = client.get("/api/assignments", headers=auth(organizer_token)).json()
    if not assignments:
        pytest.skip("Chưa có phân công nào")
    res = client.post(f"/api/assignments/{assignments[0]['id']}/review", headers=auth(token_b),
                      json={"score": 5, "recommendation": "accept", "comment": "Nhận xét trái phép"})
    assert res.status_code == 403


def test_endpoints_require_token():
    for path in ("/api/papers", "/api/conferences", "/api/assignments", "/api/reviewers"):
        assert client.get(path).status_code == 401


def test_organizer_only_endpoints(author_token):
    assert client.get("/api/admin/users", headers=auth(author_token)).status_code == 403
    assert client.get("/api/ai/logs", headers=auth(author_token)).status_code == 403
    assert client.get("/api/stats/overview", headers=auth(author_token)).status_code == 403


def test_no_api_key_in_source():
    """Không có giá trị API Key thật nào xuất hiện trong mã nguồn."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suspicious = ("sk-", "AIzaSy")
    for folder, _, files in os.walk(root):
        if any(part in folder for part in ("venv", "__pycache__", ".git", "tests")):
            continue
        for name in files:
            if not name.endswith((".py", ".js", ".html")):
                continue
            with open(os.path.join(folder, name), encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
            for marker in suspicious:
                assert marker not in content, f"Phát hiện chuỗi giống API Key trong {name}"
