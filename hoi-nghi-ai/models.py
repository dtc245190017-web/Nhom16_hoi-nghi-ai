"""
Mô hình dữ liệu — Hệ thống quản lý hội nghị khoa học có tích hợp AI.

Bao gồm 22 bảng nghiệp vụ và bảng hỗ trợ AI. Mọi bảng AI được tách riêng khỏi bảng
nghiệp vụ để dữ liệu do máy sinh không trộn lẫn với dữ liệu do con người xác nhận.
"""
import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base

TZ_VN = timezone(timedelta(hours=7))


def vietnam_now() -> datetime:
    """Thời điểm hiện tại theo múi giờ Việt Nam (UTC+7), lưu dạng naive."""
    return datetime.now(TZ_VN).replace(tzinfo=None)


class UserRole(str, enum.Enum):
    organizer = "organizer"
    author = "author"
    reviewer = "reviewer"


class UserStatus(str, enum.Enum):
    active = "active"
    locked = "locked"


class PaperStatus(str, enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    accepted = "accepted"
    rejected = "rejected"
    camera_ready = "camera_ready"


class AssignmentStatus(str, enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    done = "done"


class RegistrationType(str, enum.Enum):
    listener = "listener"
    author = "author"


class EmailKind(str, enum.Enum):
    accepted = "accepted"
    rejected = "rejected"
    revision = "revision"
    remind = "remind"


class AITaskKind(str, enum.Enum):
    summarize_paper = "summarize_paper"
    suggest_reviewers = "suggest_reviewers"
    email_draft = "email_draft"


# --------------------------------------------------------------------------- #
#  Người dùng & phân quyền
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.author.value)
    status = Column(String(20), nullable=False, default=UserStatus.active.value)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=vietnam_now)

    papers = relationship(
        "Paper", back_populates="submitter", foreign_keys="Paper.submitted_by"
    )
    reviewer_profile = relationship(
        "ReviewerProfile", back_populates="user", uselist=False
    )
    notifications = relationship("Notification", back_populates="user")
    ai_logs = relationship("AILog", back_populates="user")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(128), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=vietnam_now)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True)
    level = Column(String(20), default="error")
    source = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=vietnam_now)


# --------------------------------------------------------------------------- #
#  Hội nghị & lĩnh vực chuyên môn
# --------------------------------------------------------------------------- #
class Conference(Base):
    __tablename__ = "conferences"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    year = Column(Integer, nullable=False)
    location = Column(String(200), default="")
    description = Column(Text, default="")
    submission_deadline = Column(Date, nullable=False)
    review_deadline = Column(Date, nullable=False)
    notification_date = Column(Date, nullable=False)
    camera_ready_deadline = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="open")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=vietnam_now)

    papers = relationship("Paper", back_populates="conference")
    sessions = relationship("ConferenceSession", back_populates="conference")
    email_templates = relationship("EmailTemplate", back_populates="conference")


class ExpertiseField(Base):
    """Lĩnh vực chuyên môn của hội nghị, dùng để phân loại bài báo và phản biện."""

    __tablename__ = "expertise_fields"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(String(300), default="")


# --------------------------------------------------------------------------- #
#  Bài báo nộp
# --------------------------------------------------------------------------- #
class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (Index("ix_paper_conf_status", "conference_id", "status"),)

    id = Column(Integer, primary_key=True)
    conference_id = Column(Integer, ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False)
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(400), nullable=False)
    abstract = Column(Text, nullable=False)
    file_path = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default=PaperStatus.submitted.value)
    submitted_at = Column(DateTime, default=vietnam_now)

    conference = relationship("Conference", back_populates="papers")
    submitter = relationship("User", back_populates="papers", foreign_keys=[submitted_by])
    authors = relationship("PaperAuthor", back_populates="paper", cascade="all, delete-orphan")
    keywords = relationship("PaperKeyword", back_populates="paper", cascade="all, delete-orphan")
    topics = relationship("PaperTopic", back_populates="paper", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="paper", cascade="all, delete-orphan")


class PaperAuthor(Base):
    __tablename__ = "paper_authors"

    id = Column(Integer, primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=False)
    organization = Column(String(200), default="")
    is_corresponding = Column(Boolean, nullable=False, default=False)

    paper = relationship("Paper", back_populates="authors")


class PaperKeyword(Base):
    __tablename__ = "paper_keywords"
    __table_args__ = (UniqueConstraint("paper_id", "keyword", name="uq_paper_keyword"),)

    id = Column(Integer, primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    keyword = Column(String(120), nullable=False)

    paper = relationship("Paper", back_populates="keywords")


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "field_id", name="uq_paper_topic"),)

    id = Column(Integer, primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(Integer, ForeignKey("expertise_fields.id", ondelete="CASCADE"), nullable=False)

    paper = relationship("Paper", back_populates="topics")
    field = relationship("ExpertiseField")


# --------------------------------------------------------------------------- #
#  Phản biện
# --------------------------------------------------------------------------- #
class ReviewerProfile(Base):
    __tablename__ = "reviewer_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    degree = Column(String(50), default="")
    organization = Column(String(200), default="")
    max_load = Column(Integer, nullable=False, default=5)
    active = Column(Boolean, nullable=False, default=True)

    user = relationship("User", back_populates="reviewer_profile")
    expertise = relationship(
        "ReviewerExpertise", back_populates="profile", cascade="all, delete-orphan"
    )
    assignments = relationship("Assignment", back_populates="reviewer_profile")


class ReviewerExpertise(Base):
    __tablename__ = "reviewer_expertise"
    __table_args__ = (
        UniqueConstraint("reviewer_profile_id", "field_id", name="uq_reviewer_field"),
    )

    id = Column(Integer, primary_key=True)
    reviewer_profile_id = Column(
        Integer, ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), nullable=False
    )
    field_id = Column(Integer, ForeignKey("expertise_fields.id", ondelete="CASCADE"), nullable=False)

    profile = relationship("ReviewerProfile", back_populates="expertise")
    field = relationship("ExpertiseField")


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("paper_id", "reviewer_profile_id", name="uq_assignment_paper_reviewer"),
        Index("ix_assignment_reviewer_status", "reviewer_profile_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    reviewer_profile_id = Column(
        Integer, ForeignKey("reviewer_profiles.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default=AssignmentStatus.assigned.value)
    created_at = Column(DateTime, default=vietnam_now)

    paper = relationship("Paper", back_populates="assignments")
    reviewer_profile = relationship("ReviewerProfile", back_populates="assignments")
    review = relationship("Review", back_populates="assignment", uselist=False)


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(
        Integer, ForeignKey("assignments.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score = Column(Float, nullable=False)
    recommendation = Column(String(20), nullable=False)
    comment = Column(Text, nullable=False)
    internal_note = Column(Text, default="")
    created_at = Column(DateTime, default=vietnam_now)

    assignment = relationship("Assignment", back_populates="review")


# --------------------------------------------------------------------------- #
#  Phiên trình bày & đăng ký
# --------------------------------------------------------------------------- #
class ConferenceSession(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    conference_id = Column(Integer, ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    session_date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    room = Column(String(100), default="")
    chair = Column(String(150), default="")

    conference = relationship("Conference", back_populates="sessions")
    papers = relationship("SessionPaper", back_populates="session", cascade="all, delete-orphan")


class SessionPaper(Base):
    __tablename__ = "session_papers"
    __table_args__ = (UniqueConstraint("session_id", "paper_id", name="uq_session_paper"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, default=0)

    session = relationship("ConferenceSession", back_populates="papers")
    paper = relationship("Paper")


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("conference_id", "user_id", name="uq_registration_conf_user"),
    )

    id = Column(Integer, primary_key=True)
    conference_id = Column(Integer, ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    registration_type = Column(String(20), nullable=False, default=RegistrationType.listener.value)
    note = Column(String(300), default="")
    created_at = Column(DateTime, default=vietnam_now)

    conference = relationship("Conference")
    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False, default="assignment")
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=vietnam_now)

    user = relationship("User", back_populates="notifications")


# --------------------------------------------------------------------------- #
#  Email & khu vực AI
# --------------------------------------------------------------------------- #
class EmailTemplate(Base):
    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("conference_id", "kind", name="uq_email_template_kind"),)

    id = Column(Integer, primary_key=True)
    conference_id = Column(Integer, ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False)
    subject_template = Column(String(300), nullable=False)
    body_template = Column(Text, nullable=False)
    signer = Column(String(150), default="Ban tổ chức hội nghị")

    conference = relationship("Conference", back_populates="email_templates")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id = Column(Integer, primary_key=True)
    conference_id = Column(Integer, ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="SET NULL"), nullable=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(30), nullable=False)
    subject = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    missing_fields = Column(String(300), default="")
    source = Column(String(20), nullable=False, default="ai")
    status = Column(String(20), nullable=False, default="draft")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=vietnam_now)

    conference = relationship("Conference")
    paper = relationship("Paper")


class AILog(Base):
    """Nhật ký mọi lần gọi AI: chỉ lưu siêu dữ liệu, KHÔNG lưu nội dung prompt/trả lời."""

    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(30), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(30), default="mock")
    model = Column(String(80), default="")
    latency_ms = Column(Integer, default=0)
    success = Column(Boolean, nullable=False, default=True)
    error_type = Column(String(40), nullable=True)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=vietnam_now)

    user = relationship("User", back_populates="ai_logs")
    paper = relationship("Paper")


class AIGeneration(Base):
    """Kết quả AI đã sinh, tách khỏi bảng nghiệp vụ để phục vụ tra cứu và đối chiếu."""

    __tablename__ = "ai_generations"
    __table_args__ = (
        UniqueConstraint("paper_id", "kind", "scope_key", name="uq_ai_generation_scope"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(30), nullable=False)
    scope_key = Column(String(80), nullable=False, default="default")
    content = Column(Text, nullable=False)
    source = Column(String(20), nullable=False, default="ai")
    bias_note = Column(String(500), default="")
    created_at = Column(DateTime, default=vietnam_now)
    updated_at = Column(DateTime, default=vietnam_now, onupdate=vietnam_now)

    paper = relationship("Paper")
