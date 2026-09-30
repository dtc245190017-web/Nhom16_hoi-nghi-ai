"""
Hệ thống quản lý hội nghị khoa học có tích hợp AI — API chính (FastAPI).
Nhóm 05 — môn Ứng dụng Trí tuệ nhân tạo.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from database import Base, engine, get_db
from models import (
    AIGeneration,
    AILog,
    Assignment,
    Conference,
    ConferenceSession,
    EmailDraft,
    EmailTemplate,
    ExpertiseField,
    Notification,
    Paper,
    PaperAuthor,
    PaperKeyword,
    PaperTopic,
    PasswordResetToken,
    Registration,
    Review,
    ReviewerExpertise,
    ReviewerProfile,
    SessionPaper,
    SystemLog,
    User,
    vietnam_now,
)
from services import ai_orchestrator, ai_service

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

SECRET_KEY = os.getenv("SECRET_KEY", "thay-bang-chuoi-ngau-nhien-toi-thieu-32-ky-tu")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "organizer@hoinghi.vn")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "organizer123")
MAX_REVIEWERS_PER_PAPER = 3
AI_RATE_LIMIT_PER_HOUR = int(os.getenv("AI_RATE_LIMIT_PER_HOUR", "60"))

ROLE_ORGANIZER = "organizer"
ROLE_AUTHOR = "author"
ROLE_REVIEWER = "reviewer"

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

app = FastAPI(
    title="Hệ thống quản lý hội nghị khoa học có tích hợp AI",
    description="API quản lý hội nghị, bài báo, phản biện, phiên trình bày và các chức năng AI.",
    version="1.0.0",
)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Bộ đếm tần suất gọi AI theo người dùng (chống lạm dụng hạn mức).
_ai_calls: Dict[int, List[float]] = defaultdict(list)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Chuẩn hoá lỗi dữ liệu đầu vào về HTTP 400 kèm thông báo tiếng Việt."""
    errors = exc.errors() or []
    first = errors[0] if errors else {}
    loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
    field = ".".join(loc) or "dữ liệu"
    return JSONResponse(
        status_code=400,
        content={"detail": f"Dữ liệu không hợp lệ ở trường '{field}': {first.get('msg', 'không hợp lệ')}"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    db = next(get_db())
    try:
        db.add(SystemLog(level="error", source=str(request.url.path), message=str(exc)[:2000]))
        db.commit()
    finally:
        db.close()
    return JSONResponse(status_code=500, content={"detail": "Lỗi hệ thống, vui lòng thử lại sau."})


# --------------------------------------------------------------------------- #
#  Tiện ích xác thực
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: DBSession = Depends(get_db)
) -> User:
    if not token:
        raise HTTPException(401, "Chưa đăng nhập. Vui lòng đăng nhập để tiếp tục.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(401, "Tài khoản không tồn tại.")
    if user.status != "active":
        raise HTTPException(403, "Tài khoản đã bị khoá.")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này.")
        return user

    return dependency


require_organizer = require_roles(ROLE_ORGANIZER)
require_reviewer = require_roles(ROLE_REVIEWER)
require_author_or_organizer = require_roles(ROLE_AUTHOR, ROLE_ORGANIZER)


def check_paper_access(db: DBSession, paper: Paper, user: User) -> None:
    """Kiểm soát quyền truy cập bài báo (chặn lỗ hổng truy cập chéo dữ liệu)."""
    if user.role == ROLE_ORGANIZER:
        return
    if user.role == ROLE_AUTHOR:
        if paper.submitted_by != user.id:
            raise HTTPException(403, "Bạn không có quyền truy cập bài báo này.")
        return
    profile = db.query(ReviewerProfile).filter(ReviewerProfile.user_id == user.id).first()
    if profile:
        assigned = (
            db.query(Assignment)
            .filter(Assignment.paper_id == paper.id, Assignment.reviewer_profile_id == profile.id)
            .first()
        )
        if assigned:
            return
    raise HTTPException(403, "Bạn không có quyền truy cập bài báo này.")


def enforce_ai_rate_limit(user_id: int) -> None:
    now = time.time()
    window = [t for t in _ai_calls[user_id] if now - t < 3600]
    if len(window) >= AI_RATE_LIMIT_PER_HOUR:
        raise HTTPException(429, "Bạn đã dùng hết hạn mức gọi AI trong giờ này, vui lòng thử lại sau.")
    window.append(now)
    _ai_calls[user_id] = window


# --------------------------------------------------------------------------- #
#  Lược đồ dữ liệu vào/ra
# --------------------------------------------------------------------------- #
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: str = "author"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    status: str


class ConferenceIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    year: int = Field(ge=2000, le=2100)
    location: str = ""
    description: str = ""
    submission_deadline: date
    review_deadline: date
    notification_date: date
    camera_ready_deadline: Optional[date] = None


class PaperIn(BaseModel):
    conference_id: int
    title: str = Field(min_length=8, max_length=400)
    abstract: str
    keywords: List[str] = []
    topics: List[int] = []
    authors: List[str] = []
    file_path: Optional[str] = None


class ReviewerProfileIn(BaseModel):
    full_name: str = ""
    email: str = ""
    degree: str = ""
    organization: str = ""
    max_load: int = Field(default=5, ge=1, le=20)
    expertise_ids: List[int] = []
    active: bool = True


class AssignmentIn(BaseModel):
    paper_id: int
    reviewer_profile_id: int
    due_date: date


class ReviewIn(BaseModel):
    score: float = Field(ge=1, le=10)
    recommendation: str
    comment: str = Field(min_length=10)
    internal_note: str = ""


class SessionIn(BaseModel):
    conference_id: int
    title: str = Field(min_length=3, max_length=200)
    session_date: Optional[date] = None
    room: str = ""
    chair: str = ""
    paper_ids: List[int] = []


class RegistrationIn(BaseModel):
    conference_id: int
    registration_type: str = "listener"
    note: str = ""


class PaperRefIn(BaseModel):
    paper_id: int


# --------------------------------------------------------------------------- #
#  Hàm chuyển đổi dữ liệu
# --------------------------------------------------------------------------- #
def iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def user_out(user: User) -> Dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
    }


def conference_out(db: DBSession, conf: Conference) -> Dict:
    count = db.query(func.count(Paper.id)).filter(Paper.conference_id == conf.id).scalar() or 0
    return {
        "id": conf.id,
        "name": conf.name,
        "year": conf.year,
        "location": conf.location,
        "description": conf.description,
        "submission_deadline": iso(conf.submission_deadline),
        "review_deadline": iso(conf.review_deadline),
        "notification_date": iso(conf.notification_date),
        "camera_ready_deadline": iso(conf.camera_ready_deadline),
        "status": conf.status,
        "paper_count": int(count),
    }


def paper_out(db: DBSession, paper: Paper) -> Dict:
    assignments = paper.assignments or []
    scores = [a.review.score for a in assignments if a.review is not None]
    return {
        "id": paper.id,
        "title": paper.title,
        "abstract": paper.abstract,
        "conference_id": paper.conference_id,
        "conference_name": paper.conference.name if paper.conference else "",
        "status": paper.status,
        "submitted_at": iso(paper.submitted_at),
        "keywords": [k.keyword for k in paper.keywords],
        "topics": [{"id": t.field_id, "name": t.field.name if t.field else ""} for t in paper.topics],
        "authors": [
            {"full_name": a.full_name, "email": a.email, "organization": a.organization}
            for a in paper.authors
        ],
        "assignment_count": len(assignments),
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
    }


def reviewer_out(profile: ReviewerProfile) -> Dict:
    current_load = sum(1 for a in profile.assignments if a.status != "done")
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "full_name": profile.user.full_name if profile.user else "",
        "degree": profile.degree,
        "organization": profile.organization,
        "max_load": profile.max_load,
        "current_load": current_load,
        "active": profile.active,
        "expertise": [{"id": e.field_id, "name": e.field.name if e.field else ""} for e in profile.expertise],
    }


def assignment_out(assignment: Assignment) -> Dict:
    reviewer = assignment.reviewer_profile
    return {
        "id": assignment.id,
        "paper_id": assignment.paper_id,
        "paper_title": assignment.paper.title if assignment.paper else "",
        "reviewer_profile_id": assignment.reviewer_profile_id,
        "reviewer_name": reviewer.user.full_name if reviewer and reviewer.user else "",
        "due_date": iso(assignment.due_date),
        "status": assignment.status,
        "score": assignment.review.score if assignment.review else None,
        "recommendation": assignment.review.recommendation if assignment.review else None,
    }


def paper_visible_filter(query, db: DBSession, user: User):
    """Giới hạn danh sách bài báo theo vai trò của người dùng."""
    if user.role == ROLE_ORGANIZER:
        return query
    if user.role == ROLE_AUTHOR:
        return query.filter(Paper.submitted_by == user.id)
    profile = db.query(ReviewerProfile).filter(ReviewerProfile.user_id == user.id).first()
    if not profile:
        return query.filter(Paper.id == -1)
    subquery = (
        db.query(Assignment.paper_id)
        .filter(Assignment.reviewer_profile_id == profile.id)
        .subquery()
    )
    return query.filter(Paper.id.in_(subquery))


# --------------------------------------------------------------------------- #
#  Xác thực
# --------------------------------------------------------------------------- #
@app.post("/api/auth/register", response_model=TokenOut)
def register(data: RegisterIn, db: DBSession = Depends(get_db)):
    email = data.email.lower().strip()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(400, "Email này đã được sử dụng.")
    if data.role not in (ROLE_AUTHOR, ROLE_REVIEWER):
        raise HTTPException(400, "Vai trò đăng ký không hợp lệ (chỉ tác giả hoặc phản biện).")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if user.role == ROLE_REVIEWER:
        db.add(ReviewerProfile(user_id=user.id, max_load=5))
        db.commit()
    return TokenOut(
        access_token=create_access_token(user), role=user.role, full_name=user.full_name
    )


@app.post("/api/auth/login", response_model=TokenOut)
def login(username: str = Form(...), password: str = Form(...), db: DBSession = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == username.lower().strip()).first()
    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= 5:
                user.locked_until = vietnam_now() + timedelta(minutes=15)
            db.commit()
        raise HTTPException(400, "Email hoặc mật khẩu không chính xác.")
    if user.status != "active":
        raise HTTPException(403, "Tài khoản đã bị khoá. Vui lòng liên hệ ban tổ chức.")
    if user.locked_until and user.locked_until > vietnam_now():
        raise HTTPException(403, "Tài khoản tạm khoá do đăng nhập sai nhiều lần. Vui lòng thử lại sau.")
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()
    return TokenOut(
        access_token=create_access_token(user), role=user.role, full_name=user.full_name
    )


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(**user_out(user))


# --------------------------------------------------------------------------- #
#  Lĩnh vực chuyên môn
# --------------------------------------------------------------------------- #
@app.get("/api/expertise-fields")
def list_expertise_fields(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    fields = db.query(ExpertiseField).order_by(ExpertiseField.name).all()
    return [{"id": f.id, "name": f.name, "description": f.description} for f in fields]


# --------------------------------------------------------------------------- #
#  Hội nghị
# --------------------------------------------------------------------------- #
@app.get("/api/conferences")
def list_conferences(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    conferences = db.query(Conference).order_by(Conference.id).all()
    return [conference_out(db, c) for c in conferences]


@app.post("/api/conferences", status_code=201)
def create_conference(
    data: ConferenceIn, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    if not (data.submission_deadline <= data.review_deadline <= data.notification_date):
        raise HTTPException(
            400,
            "Thứ tự mốc thời gian không hợp lệ: hạn nộp bài ≤ hạn phản biện ≤ ngày thông báo kết quả.",
        )
    if data.camera_ready_deadline and data.camera_ready_deadline < data.notification_date:
        raise HTTPException(400, "Hạn nộp bản camera-ready không được trước ngày thông báo kết quả.")
    conference = Conference(
        name=data.name.strip(),
        year=data.year,
        location=data.location,
        description=data.description,
        submission_deadline=data.submission_deadline,
        review_deadline=data.review_deadline,
        notification_date=data.notification_date,
        camera_ready_deadline=data.camera_ready_deadline,
        created_by=user.id,
    )
    db.add(conference)
    db.commit()
    db.refresh(conference)
    ai_orchestrator.ensure_email_templates(db, conference.id)
    return conference_out(db, conference)


# --------------------------------------------------------------------------- #
#  Bài báo
# --------------------------------------------------------------------------- #
@app.get("/api/papers")
def list_papers(
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    conference_id: Optional[int] = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Paper)
    query = paper_visible_filter(query, db, user)
    if conference_id:
        query = query.filter(Paper.conference_id == conference_id)
    if status_filter:
        query = query.filter(Paper.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Paper.title.ilike(like), Paper.abstract.ilike(like)))
    papers = query.order_by(Paper.id).all()
    return [paper_out(db, p) for p in papers]


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: int, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper is None:
        raise HTTPException(404, "Không tìm thấy bài báo.")
    check_paper_access(db, paper, user)
    return paper_out(db, paper)


@app.post("/api/papers", status_code=201)
def submit_paper(
    data: PaperIn, db: DBSession = Depends(get_db), user: User = Depends(require_author_or_organizer)
):
    conference = db.query(Conference).filter(Conference.id == data.conference_id).first()
    if conference is None:
        raise HTTPException(404, "Không tìm thấy hội nghị.")
    if len((data.abstract or "").strip()) < 100:
        raise HTTPException(400, "Abstract quá ngắn, cần tối thiểu 100 ký tự.")
    paper = Paper(
        conference_id=conference.id,
        submitted_by=user.id,
        title=data.title.strip(),
        abstract=data.abstract.strip(),
        file_path=data.file_path,
        status="submitted",
    )
    db.add(paper)
    db.flush()
    for keyword in dict.fromkeys(k.strip() for k in data.keywords if k and k.strip()):
        db.add(PaperKeyword(paper_id=paper.id, keyword=keyword[:120]))
    for field_id in dict.fromkeys(data.topics):
        if db.query(ExpertiseField).filter(ExpertiseField.id == field_id).first():
            db.add(PaperTopic(paper_id=paper.id, field_id=field_id))
    for index, line in enumerate(data.authors):
        parts = [p.strip() for p in line.split("|")]
        if not parts or not parts[0]:
            continue
        db.add(
            PaperAuthor(
                paper_id=paper.id,
                full_name=parts[0][:150],
                email=(parts[1] if len(parts) > 1 else "chua-co-email@example.com")[:255],
                organization=(parts[2] if len(parts) > 2 else "")[:200],
                is_corresponding=(index == 0),
            )
        )
    db.commit()
    db.refresh(paper)
    return paper_out(db, paper)


@app.patch("/api/papers/{paper_id}/status")
def update_paper_status(
    paper_id: int,
    new_status: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_organizer),
):
    allowed = ("submitted", "under_review", "accepted", "rejected", "camera_ready")
    if new_status not in allowed:
        raise HTTPException(400, f"Trạng thái không hợp lệ. Giá trị cho phép: {', '.join(allowed)}.")
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper is None:
        raise HTTPException(404, "Không tìm thấy bài báo.")
    paper.status = new_status
    db.commit()
    return paper_out(db, paper)


# --------------------------------------------------------------------------- #
#  Phản biện
# --------------------------------------------------------------------------- #
@app.get("/api/reviewers")
def list_reviewers(db: DBSession = Depends(get_db), user: User = Depends(require_organizer)):
    profiles = db.query(ReviewerProfile).all()
    return [reviewer_out(p) for p in profiles]


@app.put("/api/reviewers/{profile_id}")
def update_reviewer(
    profile_id: int,
    data: ReviewerProfileIn,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_organizer),
):
    profile = db.query(ReviewerProfile).filter(ReviewerProfile.id == profile_id).first()
    if profile is None:
        raise HTTPException(404, "Không tìm thấy hồ sơ phản biện.")
    profile.degree = data.degree
    profile.organization = data.organization
    profile.max_load = data.max_load
    profile.active = data.active
    db.query(ReviewerExpertise).filter(ReviewerExpertise.reviewer_profile_id == profile.id).delete()
    for field_id in dict.fromkeys(data.expertise_ids):
        if db.query(ExpertiseField).filter(ExpertiseField.id == field_id).first():
            db.add(ReviewerExpertise(reviewer_profile_id=profile.id, field_id=field_id))
    db.commit()
    db.refresh(profile)
    result = reviewer_out(profile)
    result["expertise_count"] = len(result["expertise"])
    return result


# --------------------------------------------------------------------------- #
#  Phân công phản biện
# --------------------------------------------------------------------------- #
@app.get("/api/assignments")
def list_assignments(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Assignment)
    if user.role == ROLE_REVIEWER:
        profile = db.query(ReviewerProfile).filter(ReviewerProfile.user_id == user.id).first()
        if not profile:
            return []
        query = query.filter(Assignment.reviewer_profile_id == profile.id)
    elif user.role == ROLE_AUTHOR:
        paper_ids = [p.id for p in db.query(Paper).filter(Paper.submitted_by == user.id).all()]
        query = query.filter(Assignment.paper_id.in_(paper_ids or [-1]))
    return [assignment_out(a) for a in query.order_by(Assignment.id).all()]


@app.post("/api/assignments", status_code=201)
def create_assignment(
    data: AssignmentIn, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    paper = db.query(Paper).filter(Paper.id == data.paper_id).first()
    if paper is None:
        raise HTTPException(404, "Không tìm thấy bài báo.")
    profile = db.query(ReviewerProfile).filter(ReviewerProfile.id == data.reviewer_profile_id).first()
    if profile is None:
        raise HTTPException(404, "Không tìm thấy hồ sơ phản biện.")
    if not profile.active:
        raise HTTPException(400, "Phản biện này hiện không nhận phân công.")
    if data.due_date < date.today():
        raise HTTPException(400, "Hạn hoàn thành phản biện không được ở quá khứ.")
    existing = (
        db.query(Assignment)
        .filter(
            Assignment.paper_id == paper.id,
            Assignment.reviewer_profile_id == profile.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "Phản biện này đã được phân công cho bài báo.")
    current_load = sum(1 for a in profile.assignments if a.status != "done")
    if profile.max_load and current_load >= profile.max_load:
        raise HTTPException(400, f"Phản biện đã đạt tải công việc tối đa ({profile.max_load} bài).")
    if len(paper.assignments) >= MAX_REVIEWERS_PER_PAPER:
        raise HTTPException(400, f"Mỗi bài báo chỉ được phân công tối đa {MAX_REVIEWERS_PER_PAPER} phản biện.")
    assignment = Assignment(
        paper_id=paper.id,
        reviewer_profile_id=profile.id,
        assigned_by=user.id,
        due_date=data.due_date,
        status="assigned",
    )
    db.add(assignment)
    if paper.status == "submitted":
        paper.status = "under_review"
    db.commit()
    db.refresh(assignment)
    if profile.user_id:
        db.add(
            Notification(
                user_id=profile.user_id,
                kind="assignment",
                title="Bạn có phân công phản biện mới",
                message=f"Bài báo '{paper.title}' cần hoàn thành nhận xét trước {data.due_date.isoformat()}.",
            )
        )
        db.commit()
    return assignment_out(assignment)


@app.post("/api/assignments/{assignment_id}/review")
def submit_review(
    assignment_id: int,
    data: ReviewIn,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if assignment is None:
        raise HTTPException(404, "Không tìm thấy phân công.")
    profile = db.query(ReviewerProfile).filter(ReviewerProfile.user_id == user.id).first()
    if user.role != ROLE_ORGANIZER and (not profile or assignment.reviewer_profile_id != profile.id):
        raise HTTPException(403, "Bạn chỉ được gửi nhận xét cho phân công của chính mình.")
    if data.recommendation not in ("accept", "minor", "major", "reject"):
        raise HTTPException(400, "Khuyến nghị không hợp lệ.")
    review = assignment.review
    if review is None:
        review = Review(assignment_id=assignment.id)
        db.add(review)
    review.score = data.score
    review.recommendation = data.recommendation
    review.comment = data.comment
    review.internal_note = data.internal_note
    review.created_at = vietnam_now()
    assignment.status = "done"
    db.commit()
    return {"assignment_id": assignment.id, "assignment_status": assignment.status, "score": review.score}


# --------------------------------------------------------------------------- #
#  Phiên trình bày & đăng ký
# --------------------------------------------------------------------------- #
@app.get("/api/sessions")
def list_sessions(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ConferenceSession).order_by(ConferenceSession.id).all()
    return [
        {
            "id": s.id,
            "conference_id": s.conference_id,
            "title": s.title,
            "session_date": iso(s.session_date),
            "room": s.room,
            "chair": s.chair,
            "papers": [{"id": sp.paper_id, "title": sp.paper.title if sp.paper else ""} for sp in s.papers],
        }
        for s in rows
    ]


@app.post("/api/sessions", status_code=201)
def create_session(
    data: SessionIn, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    conference = db.query(Conference).filter(Conference.id == data.conference_id).first()
    if conference is None:
        raise HTTPException(404, "Không tìm thấy hội nghị.")
    papers = []
    for paper_id in data.paper_ids:
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if paper is None:
            raise HTTPException(404, f"Không tìm thấy bài báo #{paper_id}.")
        if paper.status not in ("accepted", "camera_ready"):
            raise HTTPException(
                400, "Chỉ bài báo đã được chấp nhận mới được đưa vào phiên trình bày."
            )
        papers.append(paper)
    session = ConferenceSession(
        conference_id=conference.id,
        title=data.title.strip(),
        session_date=data.session_date,
        room=data.room,
        chair=data.chair,
    )
    db.add(session)
    db.flush()
    for index, paper in enumerate(papers):
        db.add(SessionPaper(session_id=session.id, paper_id=paper.id, order_index=index))
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "title": session.title,
        "session_date": iso(session.session_date),
        "paper_count": len(papers),
    }


@app.get("/api/registrations")
def list_registrations(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Registration)
    if user.role != ROLE_ORGANIZER:
        query = query.filter(Registration.user_id == user.id)
    rows = query.order_by(Registration.id).all()
    return [
        {
            "id": r.id,
            "conference_id": r.conference_id,
            "conference_name": r.conference.name if r.conference else "",
            "user_name": r.user.full_name if r.user else "",
            "registration_type": r.registration_type,
            "note": r.note,
        }
        for r in rows
    ]


@app.post("/api/registrations", status_code=201)
def create_registration(
    data: RegistrationIn, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conference = db.query(Conference).filter(Conference.id == data.conference_id).first()
    if conference is None:
        raise HTTPException(404, "Không tìm thấy hội nghị.")
    if data.registration_type not in ("listener", "author"):
        raise HTTPException(400, "Loại đăng ký không hợp lệ.")
    existing = (
        db.query(Registration)
        .filter(Registration.conference_id == conference.id, Registration.user_id == user.id)
        .first()
    )
    if existing:
        raise HTTPException(400, "Bạn đã đăng ký tham dự hội nghị này rồi.")
    registration = Registration(
        conference_id=conference.id,
        user_id=user.id,
        registration_type=data.registration_type,
        note=data.note,
    )
    db.add(registration)
    db.commit()
    return {"id": registration.id, "conference_id": conference.id, "status": "registered"}


# --------------------------------------------------------------------------- #
#  Thống kê
# --------------------------------------------------------------------------- #
@app.get("/api/stats/overview")
def stats_overview(
    conference_id: Optional[int] = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_organizer),
):
    paper_query = db.query(Paper)
    assignment_query = db.query(Assignment)
    if conference_id:
        paper_query = paper_query.filter(Paper.conference_id == conference_id)
        paper_ids = [p.id for p in paper_query.all()]
        assignment_query = assignment_query.filter(Assignment.paper_id.in_(paper_ids or [-1]))

    papers = paper_query.all()
    assignments = assignment_query.all()
    today = date.today()

    by_status: Dict[str, int] = {}
    for paper in papers:
        by_status[paper.status] = by_status.get(paper.status, 0) + 1

    by_field: Dict[str, int] = {}
    for paper in papers:
        for topic in paper.topics:
            name = topic.field.name if topic.field else "Khác"
            by_field[name] = by_field.get(name, 0) + 1

    completed = sum(1 for a in assignments if a.status == "done")
    overdue = [a for a in assignments if a.status != "done" and a.due_date and a.due_date < today]
    total = len(assignments)

    return {
        "total_papers": len(papers),
        "total_assignments": total,
        "completed_assignments": completed,
        "overdue_assignments": len(overdue),
        "review_progress_percent": round(completed / total * 100, 1) if total else 0.0,
        "by_status": by_status,
        "by_field": by_field,
        "overdue_list": [
            {
                "paper_title": a.paper.title if a.paper else "",
                "reviewer_name": a.reviewer_profile.user.full_name
                if a.reviewer_profile and a.reviewer_profile.user
                else "",
                "due_date": iso(a.due_date),
            }
            for a in overdue
        ],
    }


# --------------------------------------------------------------------------- #
#  Khu vực AI
# --------------------------------------------------------------------------- #
def _get_paper_or_404(db: DBSession, paper_id: int) -> Paper:
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper is None:
        raise HTTPException(404, "Không tìm thấy bài báo.")
    return paper


@app.get("/api/ai/status")
def ai_status():
    return {
        "provider": ai_service.PROVIDER,
        "configured": ai_service.is_configured(),
        "note": (
            "Nhà cung cấp AI đã sẵn sàng."
            if ai_service.is_configured()
            else "Đang dùng chế độ mô phỏng (mock) hoặc chưa cấu hình API Key; "
                 "hệ thống vẫn hoạt động nhờ kết quả dự phòng tính nội bộ."
        ),
    }


@app.post("/api/ai/summarize-paper")
def ai_summarize_paper(
    data: PaperRefIn, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    enforce_ai_rate_limit(user.id)
    paper = _get_paper_or_404(db, data.paper_id)
    return ai_orchestrator.summarize_paper(db, paper, user.id)


@app.post("/api/ai/suggest-reviewers")
def ai_suggest_reviewers(
    data: PaperRefIn, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    enforce_ai_rate_limit(user.id)
    paper = _get_paper_or_404(db, data.paper_id)
    return ai_orchestrator.suggest_reviewers(db, paper, user.id)


@app.post("/api/ai/email-draft")
def ai_email_draft(
    kind: str,
    data: PaperRefIn,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_organizer),
):
    enforce_ai_rate_limit(user.id)
    paper = _get_paper_or_404(db, data.paper_id)
    try:
        result = ai_orchestrator.email_draft(db, paper, kind, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    draft = EmailDraft(
        conference_id=paper.conference_id,
        paper_id=paper.id,
        kind=kind,
        subject=result["data"]["subject"][:300],
        body=result["data"]["body"],
        missing_fields=",".join(result["data"]["missing_fields"])[:300],
        source=result["source"],
        created_by=user.id,
    )
    db.add(draft)
    db.commit()
    return result


@app.get("/api/ai/logs")
def ai_logs(
    limit: int = 100, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    rows = db.query(AILog).order_by(AILog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "paper_id": r.paper_id,
            "provider": r.provider,
            "model": r.model,
            "latency_ms": r.latency_ms,
            "success": r.success,
            "error_type": r.error_type,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


@app.get("/api/ai/generations")
def ai_generations(
    limit: int = 100, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    rows = db.query(AIGeneration).order_by(AIGeneration.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "paper_id": r.paper_id,
            "source": r.source,
            "bias_note": r.bias_note,
            "content": r.content,
            "updated_at": iso(r.updated_at),
        }
        for r in rows
    ]


@app.get("/api/email-drafts")
def email_drafts(
    limit: int = 100, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    rows = db.query(EmailDraft).order_by(EmailDraft.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "paper_id": r.paper_id,
            "subject": r.subject,
            "status": r.status,
            "missing_fields": r.missing_fields,
            "source": r.source,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
#  Quản trị
# --------------------------------------------------------------------------- #
@app.get("/api/admin/users")
def admin_users(db: DBSession = Depends(get_db), user: User = Depends(require_organizer)):
    users = db.query(User).order_by(User.id).all()
    rows = []
    for item in users:
        count = db.query(func.count(Paper.id)).filter(Paper.submitted_by == item.id).scalar() or 0
        rows.append({**user_out(item), "paper_count": int(count)})
    return rows


@app.get("/api/admin/system-logs")
def admin_system_logs(
    limit: int = 100, db: DBSession = Depends(get_db), user: User = Depends(require_organizer)
):
    rows = db.query(SystemLog).order_by(SystemLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "level": r.level,
            "source": r.source,
            "message": r.message,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


@app.get("/api/notifications")
def my_notifications(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "message": r.message,
            "is_read": r.is_read,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
#  Giao diện
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


# --------------------------------------------------------------------------- #
#  Dữ liệu khởi tạo
# --------------------------------------------------------------------------- #
DEFAULT_FIELDS = [
    "Trí tuệ nhân tạo",
    "Học máy và học sâu",
    "Khoa học dữ liệu",
    "An toàn thông tin",
    "Mạng máy tính",
    "Kỹ thuật phần mềm",
    "Hệ thống thông tin",
    "Thị giác máy tính",
    "Xử lý ngôn ngữ tự nhiên",
    "Tính toán hiệu năng cao",
    "Công nghệ phần mềm nhúng",
    "Giáo dục số",
]


def seed(db: DBSession) -> None:
    """Tạo dữ liệu khởi tạo: lĩnh vực chuyên môn, ban tổ chức, phản biện mẫu, mẫu email."""
    for name in DEFAULT_FIELDS:
        if not db.query(ExpertiseField).filter(ExpertiseField.name == name).first():
            db.add(ExpertiseField(name=name))
    db.commit()

    organizer = db.query(User).filter(func.lower(User.email) == ADMIN_EMAIL.lower()).first()
    if organizer is None:
        organizer = User(
            email=ADMIN_EMAIL.lower(),
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name="Ban tổ chức hội nghị",
            role=ROLE_ORGANIZER,
        )
        db.add(organizer)
        db.commit()
        db.refresh(organizer)

    fields = db.query(ExpertiseField).order_by(ExpertiseField.id).all()
    sample_reviewers = [
        ("reviewer1@hoinghi.vn", "Nguyễn Văn An", "PGS.TS", "Đại học Công nghệ Thông tin", [0, 1, 8]),
        ("reviewer2@hoinghi.vn", "Trần Thị Bình", "TS", "Học viện Kỹ thuật Quân sự", [3, 4, 5]),
    ]
    for email, full_name, degree, organization, field_indexes in sample_reviewers:
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password("reviewer123"),
                full_name=full_name,
                role=ROLE_REVIEWER,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        profile = db.query(ReviewerProfile).filter(ReviewerProfile.user_id == user.id).first()
        if profile is None:
            profile = ReviewerProfile(user_id=user.id, max_load=5)
            db.add(profile)
            db.commit()
            db.refresh(profile)
        profile.degree = degree
        profile.organization = organization
        if not profile.expertise:
            for index in field_indexes:
                if index < len(fields):
                    db.add(ReviewerExpertise(reviewer_profile_id=profile.id, field_id=fields[index].id))
            db.commit()

    if not db.query(Conference).first():
        conference = Conference(
            name="Hội nghị Khoa học Công nghệ Thông tin 2026",
            year=2026,
            location="Thái Nguyên",
            description="Hội nghị thường niên về công nghệ thông tin và ứng dụng trí tuệ nhân tạo.",
            submission_deadline=date(2026, 10, 31),
            review_deadline=date(2026, 11, 30),
            notification_date=date(2026, 12, 15),
            camera_ready_deadline=date(2026, 12, 31),
            created_by=organizer.id,
        )
        db.add(conference)
        db.commit()
        db.refresh(conference)
        ai_orchestrator.ensure_email_templates(db, conference.id)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed(db)
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:  # pragma: no cover
    init_db()
    if SECRET_KEY.startswith("thay-bang-chuoi"):
        print("[CẢNH BÁO] SECRET_KEY vẫn là giá trị mẫu. Hãy đổi trong tệp .env trước khi triển khai.")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
