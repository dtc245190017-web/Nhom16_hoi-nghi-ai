"""Kiểm tra và làm sạch kết quả do AI trả về.

Nguyên tắc: AI là bên đề xuất, hệ thống là bên kiểm soát. Mọi dữ liệu do AI sinh ra phải
đi qua lớp này trước khi hiển thị hoặc lưu lại.
"""
import json
import re
from typing import Any, Dict, List, Optional

_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)

SUMMARY_KEYS = ("summary", "contributions", "method", "normalized_keywords")


def _strip_fences(text: str) -> str:
    cleaned = _FENCE.sub("", text or "").replace("```", "")
    return cleaned.strip()


def _extract_json_object(text: str) -> Optional[str]:
    """Lấy khối JSON đầu tiên trong văn bản, kể cả khi AI thêm lời dẫn xung quanh."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Phân tích phản hồi AI thành dict; trả về None nếu không phân tích được."""
    cleaned = _strip_fences(text)
    for candidate in (cleaned, _extract_json_object(cleaned)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def normalize_summary(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Chuẩn hoá kết quả tóm tắt về đúng bốn khoá, đúng kiểu dữ liệu."""
    data = data or {}
    contributions = data.get("contributions")
    if isinstance(contributions, str):
        contributions = [contributions] if contributions.strip() else []
    if not isinstance(contributions, list):
        contributions = []
    keywords = data.get("normalized_keywords")
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    if not isinstance(keywords, list):
        keywords = []
    return {
        "summary": str(data.get("summary") or "").strip(),
        "contributions": [str(c).strip() for c in contributions[:3] if str(c).strip()],
        "method": str(data.get("method") or "").strip(),
        "normalized_keywords": [str(k).strip().lower() for k in keywords[:8] if str(k).strip()],
    }


def filter_recommendations(
    items: Optional[List[Dict[str, Any]]], candidates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Loại bỏ mọi gợi ý không ánh xạ được về danh sách phản biện do hệ thống cung cấp.

    Đây là lớp chặn hiện tượng AI bịa ra phản biện không tồn tại.
    """
    allowed = {c.get("reviewer_index") for c in (candidates or [])}
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("reviewer_index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        if idx not in allowed or idx in seen:
            continue
        seen.add(idx)
        confidence = str(item.get("confidence") or "medium").lower()
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"
        result.append(
            {
                "reviewer_index": idx,
                "reason": str(item.get("reason") or "").strip()[:600],
                "confidence": confidence,
            }
        )
    return result


def normalize_recommendations(
    data: Optional[Dict[str, Any]], candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    data = data or {}
    return {
        "recommendations": filter_recommendations(data.get("recommendations"), candidates),
        "bias_note": str(data.get("bias_note") or "").strip()[:500],
        "disclaimer": str(
            data.get("disclaimer")
            or "Đây là gợi ý tham khảo, ban tổ chức quyết định phân công cuối cùng."
        ).strip(),
    }


def normalize_email(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = data or {}
    missing = data.get("missing_fields")
    if isinstance(missing, str):
        missing = [m.strip() for m in missing.split(",") if m.strip()]
    if not isinstance(missing, list):
        missing = []
    return {
        "subject": str(data.get("subject") or "").strip()[:300],
        "body": str(data.get("body") or "").strip(),
        "missing_fields": [str(m).strip() for m in missing],
    }


def contains_fabricated_name(text: str, allowed_names: List[str]) -> bool:
    """Phát hiện tên người xuất hiện trong phản hồi AI nhưng không có trong danh sách hợp lệ."""
    if not text:
        return False
    normalized_allowed = " ".join(allowed_names).lower()
    for token in re.findall(r"(?:GS|PGS|TS|ThS)\.?\s+[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)*", text):
        if token.lower() not in normalized_allowed:
            return True
    return False
