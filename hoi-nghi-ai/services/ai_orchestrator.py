"""Điều phối các tác vụ AI: ghép dữ liệu, gọi AI, kiểm tra kết quả, ghi nhật ký và dự phòng.

Ba chức năng AI chính:
  * summarize_paper    — tóm tắt bài báo khoa học
  * suggest_reviewers  — gợi ý phản biện phù hợp (có cảnh báo thiên lệch)
  * email_draft        — sinh nháp email thông báo cho tác giả / phản biện

Mọi chức năng đều trả về dict thống nhất: {kind, paper_id, source, notice, data}
trong đó source ∈ {"ai", "fallback"}. Khi AI lỗi, hệ thống KHÔNG báo lỗi cho người dùng
mà chuyển sang kết quả tính toán nội bộ (fallback) và nêu rõ lý do.
"""
import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import AIGeneration, AILog, Assignment, EmailTemplate, Paper, ReviewerProfile, vietnam_now
from services import ai_service, prompt_builder, response_validator

# Các trường bị loại bỏ trước khi gửi ra ngoài nhà cung cấp AI (bảo vệ dữ liệu cá nhân).
PII_FIELDS = {
    "full_name",
    "email",
    "phone",
    "password",
    "password_hash",
    "user_id",
    "submitted_by",
    "paper_id",
    "assignment_id",
    "reviewer_profile_id",
    "author_email",
    "created_by",
}

NOTICE = "Kết quả gợi ý tham khảo từ AI, cần con người kiểm tra lại trước khi sử dụng."
FALLBACK_NOTICE = (
    "AI Provider không khả dụng hoặc trả về dữ liệu không đọc được; "
    "hệ thống đã dùng kết quả tính toán nội bộ."
)

EMAIL_KINDS = ("accepted", "rejected", "revision", "remind")

DEFAULT_TEMPLATES = {
    "accepted": (
        "Thông báo chấp nhận bài báo",
        "Kính gửi quý tác giả,\n\nBan tổ chức trân trọng thông báo bài báo \"{{paper_title}}\" "
        "đã được chấp nhận trình bày tại {{conference_name}}.\n\nTrân trọng.",
    ),
    "rejected": (
        "Thông báo kết quả phản biện",
        "Kính gửi quý tác giả,\n\nBan tổ chức xin thông báo bài báo \"{{paper_title}}\" "
        "chưa đạt yêu cầu của {{conference_name}} lần này.\n\nTrân trọng.",
    ),
    "revision": (
        "Yêu cầu chỉnh sửa bài báo",
        "Kính gửi quý tác giả,\n\nBan tổ chức đề nghị chỉnh sửa bài báo \"{{paper_title}}\" "
        "theo nhận xét của phản biện trước ngày {{camera_ready_deadline}}.\n\nTrân trọng.",
    ),
    "remind": (
        "Nhắc nhở hoàn thành phản biện",
        "Kính gửi quý phản biện,\n\nBan tổ chức nhắc quý phản biện hoàn thành nhận xét cho bài báo "
        "\"{{paper_title}}\" trước ngày {{review_due}}.\n\nTrân trọng.",
    ),
}


# --------------------------------------------------------------------------- #
#  Bảo vệ dữ liệu cá nhân
# --------------------------------------------------------------------------- #
def anonymize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Loại bỏ mọi trường định danh cá nhân trước khi dữ liệu rời khỏi hệ thống."""
    clean: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if key in PII_FIELDS:
            continue
        if isinstance(value, dict):
            clean[key] = anonymize(value)
        elif isinstance(value, list):
            clean[key] = [anonymize(v) if isinstance(v, dict) else v for v in value]
        else:
            clean[key] = value
    return clean


# --------------------------------------------------------------------------- #
#  Nhật ký AI
# --------------------------------------------------------------------------- #
def log_ai(
    db: Session,
    user_id: int,
    kind: str,
    paper_id: Optional[int] = None,
    result: Optional[ai_service.AIResult] = None,
    error: Optional[ai_service.AIError] = None,
) -> None:
    entry = AILog(
        user_id=user_id,
        kind=kind,
        paper_id=paper_id,
        provider=(result.provider if result else ai_service.PROVIDER),
        model=(result.model if result else ai_service.MODEL_NAME),
        latency_ms=(result.latency_ms if result else 0),
        success=error is None,
        error_type=(error.error_type if error else None),
        error_message=(str(error)[:500] if error else None),
    )
    db.add(entry)
    db.commit()


def save_generation(
    db: Session,
    user_id: int,
    kind: str,
    paper_id: Optional[int],
    content: Dict[str, Any],
    source: str,
    bias_note: str = "",
    scope_key: str = "default",
) -> None:
    """Lưu kết quả AI vào bảng riêng, không ghi vào bảng nghiệp vụ."""
    existing = (
        db.query(AIGeneration)
        .filter(
            AIGeneration.paper_id == paper_id,
            AIGeneration.kind == kind,
            AIGeneration.scope_key == scope_key,
        )
        .first()
    )
    payload = json.dumps(content, ensure_ascii=False)
    if existing:
        existing.content = payload
        existing.source = source
        existing.bias_note = bias_note[:500]
        existing.updated_at = vietnam_now()
    else:
        db.add(
            AIGeneration(
                user_id=user_id,
                paper_id=paper_id,
                kind=kind,
                scope_key=scope_key,
                content=payload,
                source=source,
                bias_note=bias_note[:500],
            )
        )
    db.commit()


# --------------------------------------------------------------------------- #
#  Kết quả dự phòng (tính nội bộ, không cần AI)
# --------------------------------------------------------------------------- #
def fallback_summary(paper: Paper) -> Dict[str, Any]:
    text = (paper.abstract or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    keywords = [k.keyword.strip().lower() for k in paper.keywords if k.keyword.strip()]
    return {
        "summary": " ".join(sentences[:3])[:600],
        "contributions": sentences[1:3],
        "method": sentences[-1] if sentences else "",
        "normalized_keywords": keywords[:8],
    }


def _paper_match_score(paper: Paper, profile: ReviewerProfile) -> int:
    """Điểm khớp chuyên môn 0–100 giữa bài báo và hồ sơ phản biện (tính bằng hệ thống)."""
    paper_fields = {t.field_id for t in paper.topics}
    reviewer_fields = {e.field_id for e in profile.expertise}
    overlap = len(paper_fields & reviewer_fields)
    score = 0.0
    if paper_fields:
        score += 70.0 * overlap / len(paper_fields)
    reviewer_keywords = " ".join(e.field.name.lower() for e in profile.expertise)
    hits = sum(1 for k in paper.keywords if k.keyword.strip().lower() in reviewer_keywords)
    score += min(30.0, hits * 10.0)
    if profile.max_load and profile.assignments:
        load = sum(1 for a in profile.assignments if a.status != "done")
        score -= min(20.0, load * 4.0)
    return max(0, min(100, int(round(score))))


def build_candidates(db: Session, paper: Paper, limit: int = 6) -> List[Dict[str, Any]]:
    """Danh sách phản biện ứng viên kèm chỉ số, điểm khớp và tải công việc hiện tại."""
    profiles = db.query(ReviewerProfile).filter(ReviewerProfile.active.is_(True)).all()
    assigned_ids = {a.reviewer_profile_id for a in paper.assignments}
    scored = []
    for profile in profiles:
        if profile.id in assigned_ids:
            continue
        if not profile.expertise:
            continue
        current_load = sum(1 for a in profile.assignments if a.status != "done")
        if profile.max_load and current_load >= profile.max_load:
            continue
        scored.append(
            {
                "profile": profile,
                "match_score": _paper_match_score(paper, profile),
                "current_load": current_load,
            }
        )
    scored.sort(key=lambda item: item["match_score"], reverse=True)
    candidates = []
    for index, item in enumerate(scored[:limit], start=1):
        profile = item["profile"]
        candidates.append(
            {
                "reviewer_index": index,
                "reviewer_profile_id": profile.id,
                "degree": profile.degree,
                "organization": profile.organization,
                "expertise": [e.field.name for e in profile.expertise],
                "match_score": item["match_score"],
                "current_load": item["current_load"],
                "max_load": profile.max_load,
            }
        )
    return candidates


def fallback_recommendations(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    recs = [
        {
            "reviewer_index": c["reviewer_index"],
            "reason": (
                f"Điểm khớp chuyên môn {c['match_score']}/100; lĩnh vực "
                f"{', '.join(c['expertise'][:3])}; tải công việc {c['current_load']}/{c['max_load']}."
            ),
            "confidence": "high" if c["match_score"] >= 70 else "medium",
        }
        for c in candidates[:3]
    ]
    return {
        "recommendations": recs,
        "bias_note": (
            "Xếp hạng nội bộ dựa trên lĩnh vực chuyên môn khai báo và tải công việc; "
            "chưa xét yếu tố tổ chức công tác nên có thể còn thiên lệch."
        ),
        "disclaimer": "Đây là gợi ý tham khảo, ban tổ chức quyết định phân công cuối cùng.",
    }


# --------------------------------------------------------------------------- #
#  Ba chức năng AI
# --------------------------------------------------------------------------- #
def summarize_paper(db: Session, paper: Paper, user_id: int) -> Dict[str, Any]:
    raw = {
        "paper_title": paper.title,
        "paper_abstract": paper.abstract,
        "paper_keywords": [k.keyword for k in paper.keywords],
        "paper_topics": [t.field.name for t in paper.topics],
        "paper_id": paper.id,
    }
    payload = anonymize(raw)
    abstract_text, truncated = ai_service.truncate_input(payload.get("paper_abstract", ""))
    payload["paper_abstract"] = abstract_text

    values = dict(payload)
    prompt = prompt_builder.build_prompt("summarize_paper", values)
    source, fallback_notice = "ai", None
    error = None
    result = None

    try:
        result = ai_service.call_ai(prompt, kind="summarize_paper", payload=payload)
        parsed = response_validator.parse_json(result.text)
        if parsed is None:
            raise ai_service.AIError("Kết quả AI không phải JSON hợp lệ", "bad_format")
        data = response_validator.normalize_summary(parsed)
    except ai_service.AIError as exc:
        error = exc
        source, fallback_notice = "fallback", FALLBACK_NOTICE
        data = fallback_summary(paper)

    log_ai(db, user_id, "summarize_paper", paper.id, result=result, error=error)
    save_generation(db, user_id, "summarize_paper", paper.id, data, source)

    return {
        "kind": "summarize_paper",
        "paper_id": paper.id,
        "source": source,
        "fallback_notice": fallback_notice,
        "notice": NOTICE + (" Dữ liệu đầu vào đã được cắt bớt do quá dài." if truncated else ""),
        "prompt_version": prompt_builder.prompt_version("summarize_paper"),
        "data": data,
    }


def suggest_reviewers(db: Session, paper: Paper, user_id: int) -> Dict[str, Any]:
    candidates = build_candidates(db, paper)
    raw = {
        "paper_title": paper.title,
        "paper_abstract": paper.abstract,
        "paper_keywords": [k.keyword for k in paper.keywords],
        "paper_topics": [t.field.name for t in paper.topics],
        "reviewer_candidates": candidates,
        "paper_id": paper.id,
    }
    payload = anonymize(raw)
    abstract_text, _ = ai_service.truncate_input(payload.get("paper_abstract", ""))
    payload["paper_abstract"] = abstract_text

    prompt = prompt_builder.build_prompt("suggest_reviewers", payload)
    source, fallback_notice = "ai", None
    error = None
    result = None

    try:
        result = ai_service.call_ai(prompt, kind="suggest_reviewers", payload=payload)
        parsed = response_validator.parse_json(result.text)
        if parsed is None:
            raise ai_service.AIError("Kết quả AI không phải JSON hợp lệ", "bad_format")
        data = response_validator.normalize_recommendations(parsed, candidates)
        if not data["recommendations"]:
            raise ai_service.AIError("AI không trả về gợi ý nào khớp danh sách ứng viên", "bad_format")
    except ai_service.AIError as exc:
        error = exc
        source, fallback_notice = "fallback", FALLBACK_NOTICE
        data = fallback_recommendations(candidates)

    # Ghép lại thông tin hồ sơ thật theo chỉ số, không lấy tên do AI sinh ra.
    by_index = {c["reviewer_index"]: c for c in candidates}
    for item in data["recommendations"]:
        cand = by_index.get(item["reviewer_index"], {})
        item["reviewer_profile_id"] = cand.get("reviewer_profile_id")
        item["match_score"] = cand.get("match_score")
        item["expertise"] = cand.get("expertise", [])

    log_ai(db, user_id, "suggest_reviewers", paper.id, result=result, error=error)
    save_generation(
        db, user_id, "suggest_reviewers", paper.id, data, source, bias_note=data.get("bias_note", "")
    )

    return {
        "kind": "suggest_reviewers",
        "paper_id": paper.id,
        "source": source,
        "fallback_notice": fallback_notice,
        "notice": NOTICE,
        "prompt_version": prompt_builder.prompt_version("suggest_reviewers"),
        "data": data,
    }


def ensure_email_templates(db: Session, conference_id: int) -> None:
    """Bảo đảm mỗi hội nghị có đủ mẫu email cho bốn loại thông báo."""
    existing = {
        t.kind for t in db.query(EmailTemplate).filter(EmailTemplate.conference_id == conference_id)
    }
    created = False
    for kind, (subject, body) in DEFAULT_TEMPLATES.items():
        if kind in existing:
            continue
        db.add(
            EmailTemplate(
                conference_id=conference_id,
                kind=kind,
                subject_template=subject,
                body_template=body,
            )
        )
        created = True
    if created:
        db.commit()


def email_draft(db: Session, paper: Paper, kind: str, user_id: int) -> Dict[str, Any]:
    if kind not in EMAIL_KINDS:
        raise ValueError(
            "Chưa cấu hình mẫu email cho loại thông báo này. "
            f"Các loại hợp lệ: {', '.join(EMAIL_KINDS)}."
        )
    ensure_email_templates(db, paper.conference_id)
    template = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.conference_id == paper.conference_id, EmailTemplate.kind == kind)
        .first()
    )
    if template is None:
        raise ValueError("Chưa cấu hình mẫu email cho loại thông báo này.")

    conference = paper.conference
    first_assignment = paper.assignments[0] if paper.assignments else None
    raw = {
        "email_kind": kind,
        "conference_name": conference.name if conference else "",
        "paper_title": paper.title,
        "paper_abstract": (paper.abstract or "")[:800],
        "paper_status": paper.status,
        "review_due": (first_assignment.due_date.isoformat() if first_assignment and first_assignment.due_date else ""),
        "camera_ready_deadline": (
            conference.camera_ready_deadline.isoformat()
            if conference and conference.camera_ready_deadline
            else ""
        ),
        "notification_date": (conference.notification_date.isoformat() if conference else ""),
        "subject_template": template.subject_template,
        "body_template": template.body_template,
        "signer": template.signer,
        "missing_fields": [
            name
            for name, value in (
                ("review_due", first_assignment.due_date if first_assignment else None),
                ("camera_ready_deadline", conference.camera_ready_deadline if conference else None),
            )
            if not value
        ],
        "paper_id": paper.id,
    }
    payload = anonymize(raw)
    prompt = prompt_builder.build_prompt("email_notification", payload)
    source, fallback_notice = "ai", None
    error = None
    result = None

    try:
        result = ai_service.call_ai(prompt, kind="email_draft", payload=payload)
        parsed = response_validator.parse_json(result.text)
        if parsed is None:
            raise ai_service.AIError("Kết quả AI không phải JSON hợp lệ", "bad_format")
        data = response_validator.normalize_email(parsed)
        if not data["subject"] or not data["body"]:
            raise ai_service.AIError("AI trả về nháp email thiếu tiêu đề hoặc nội dung", "bad_format")
        if not data["missing_fields"]:
            data["missing_fields"] = payload.get("missing_fields", [])
    except ai_service.AIError as exc:
        error = exc
        source, fallback_notice = "fallback", FALLBACK_NOTICE
        data = {
            "subject": prompt_builder.render(template.subject_template, payload),
            "body": prompt_builder.render(template.body_template, payload),
            "missing_fields": payload.get("missing_fields", []),
        }

    log_ai(db, user_id, "email_draft", paper.id, result=result, error=error)
    save_generation(db, user_id, "email_draft", paper.id, data, source, scope_key=kind)

    return {
        "kind": "email_draft",
        "paper_id": paper.id,
        "source": source,
        "fallback_notice": fallback_notice,
        "notice": NOTICE + " Email chỉ ở trạng thái nháp, chưa được gửi đi.",
        "prompt_version": prompt_builder.prompt_version("email_notification"),
        "data": data,
    }
