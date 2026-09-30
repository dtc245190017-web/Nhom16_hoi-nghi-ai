"""Lớp adapter gọi nhà cung cấp AI.

Toàn bộ mã nghiệp vụ chỉ gọi duy nhất hàm `call_ai()`. Muốn đổi nhà cung cấp chỉ cần
đổi biến môi trường AI_PROVIDER, không phải sửa mã nghiệp vụ.

Nhà cung cấp hỗ trợ: mock (mặc định, không cần API Key), gemini, openai, ollama.
"""
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()
MODEL_NAME = os.getenv("AI_MODEL", "") or {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5:7b",
    "mock": "mock-local",
}.get(PROVIDER, "mock-local")

API_KEY = (
    os.getenv("AI_API_KEY", "")
    or os.getenv("GEMINI_API_KEY", "")
    or os.getenv("OPENAI_API_KEY", "")
)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))
MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "2"))
MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "6000"))

VALID_ERROR_TYPES = ("timeout", "rate_limit", "empty", "bad_format", "too_long", "model_error")


class AIError(Exception):
    """Lỗi khi gọi nhà cung cấp AI, kèm loại lỗi để ghi nhật ký."""

    def __init__(self, message: str, error_type: str = "model_error"):
        super().__init__(message)
        self.error_type = error_type if error_type in VALID_ERROR_TYPES else "model_error"


@dataclass
class AIResult:
    text: str
    source: str = "ai"
    provider: str = PROVIDER
    model: str = MODEL_NAME
    latency_ms: int = 0
    error_type: Optional[str] = None
    truncated: bool = False


def is_configured() -> bool:
    """Provider đã sẵn sàng gọi thật chưa (mock luôn coi là chưa cấu hình)."""
    if PROVIDER == "mock":
        return False
    if PROVIDER == "ollama":
        return True
    return bool(API_KEY)


def truncate_input(text: Optional[str], limit: int = MAX_INPUT_CHARS):
    """Cắt bớt dữ liệu đầu vào quá dài để tránh vượt hạn mức token.

    Trả về (chuỗi đã cắt, có bị cắt hay không).
    """
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit], True


# --------------------------------------------------------------------------- #
#  Mock provider — sinh kết quả hợp lệ để hệ thống chạy được khi chưa có API Key
# --------------------------------------------------------------------------- #
def _mock_summary(payload: Dict[str, Any]) -> str:
    abstract = (payload.get("paper_abstract") or "").strip()
    sentences = [s.strip() for s in abstract.replace("\n", " ").split(". ") if s.strip()]
    summary = ". ".join(sentences[:3])
    if summary and not summary.endswith("."):
        summary += "."
    method = sentences[3] if len(sentences) > 3 else (sentences[-1] if sentences else "")
    keywords = payload.get("paper_keywords") or []
    normalized = []
    for kw in keywords[:5]:
        k = str(kw).strip().lower()
        if k and k not in normalized:
            normalized.append(k)
    return json.dumps(
        {
            "summary": summary[:600],
            "contributions": sentences[1:3] or ([summary[:180]] if summary else []),
            "method": method[:300],
            "normalized_keywords": normalized,
        },
        ensure_ascii=False,
    )


def _mock_reviewers(payload: Dict[str, Any]) -> str:
    candidates = payload.get("reviewer_candidates") or []
    recs = []
    for cand in candidates[:3]:
        idx = cand.get("reviewer_index")
        if idx is None:
            continue
        recs.append(
            {
                "reviewer_index": idx,
                "reason": (
                    f"Lĩnh vực chuyên môn {', '.join(cand.get('expertise', [])[:3])} trùng với "
                    f"chủ đề bài báo; hiện phụ trách "
                    f"{cand.get('current_load', 0)}/{cand.get('max_load', 5)} bài."
                ),
                "confidence": "high" if cand.get("match_score", 0) >= 70 else "medium",
            }
        )
    return json.dumps(
        {
            "recommendations": recs,
            "bias_note": (
                "Gợi ý dựa trên mức trùng khớp từ khóa và lĩnh vực chuyên môn được khai báo. "
                "Cần kiểm tra để tránh thiên lệch về tổ chức công tác hoặc giới tính."
            ),
            "disclaimer": "Đây là gợi ý tham khảo, ban tổ chức quyết định phân công cuối cùng.",
        },
        ensure_ascii=False,
    )


def _mock_email(payload: Dict[str, Any]) -> str:
    kind = payload.get("email_kind", "accepted")
    missing = [f for f in (payload.get("missing_fields") or []) if f]
    title_map = {
        "accepted": "Thông báo chấp nhận bài báo",
        "rejected": "Thông báo kết quả phản biện",
        "revision": "Yêu cầu chỉnh sửa bài báo",
        "remind": "Nhắc nhở hoàn thành phản biện",
    }
    body_map = {
        "accepted": "Ban tổ chức trân trọng thông báo bài báo của quý tác giả đã được chấp nhận.",
        "rejected": "Ban tổ chức xin thông báo bài báo chưa đạt yêu cầu của hội nghị lần này.",
        "revision": "Ban tổ chức đề nghị quý tác giả chỉnh sửa bài báo theo nhận xét của phản biện.",
        "remind": "Ban tổ chức nhắc quý phản biện hoàn thành nhận xét đúng hạn.",
    }
    return json.dumps(
        {
            "subject": f"{title_map.get(kind, 'Thông báo từ ban tổ chức')} — "
                       f"{payload.get('conference_name', '')}".strip(),
            "body": f"{body_map.get(kind, '')}\n\nBài báo: {payload.get('paper_title', '')}",
            "missing_fields": missing,
        },
        ensure_ascii=False,
    )


def _mock_response(kind: str, payload: Dict[str, Any]) -> str:
    if kind == "summarize_paper":
        return _mock_summary(payload)
    if kind == "suggest_reviewers":
        return _mock_reviewers(payload)
    if kind == "email_draft":
        return _mock_email(payload)
    return json.dumps({"note": "mock"}, ensure_ascii=False)


# --------------------------------------------------------------------------- #
#  Gọi nhà cung cấp thật
# --------------------------------------------------------------------------- #
def _call_gemini(prompt: str) -> str:
    if not API_KEY:
        raise AIError("Chưa cấu hình AI_API_KEY cho nhà cung cấp Gemini", "model_error")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL_NAME}:generateContent?key={API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(os.getenv("AI_TEMPERATURE", "0.3")),
            "maxOutputTokens": int(os.getenv("AI_MAX_OUTPUT_TOKENS", "900")),
            "responseMimeType": "application/json",
        },
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        res = client.post(url, json=body)
    if res.status_code == 429:
        raise AIError("Vượt hạn mức gọi AI của nhà cung cấp", "rate_limit")
    if res.status_code >= 400:
        raise AIError(f"AI Provider lỗi phía dịch vụ ({res.status_code})", "model_error")
    data = res.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise AIError("Phản hồi của AI không đúng cấu trúc mong đợi", "bad_format") from exc


def _call_openai(prompt: str) -> str:
    if not API_KEY:
        raise AIError("Chưa cấu hình AI_API_KEY cho nhà cung cấp OpenAI", "model_error")
    body = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Chỉ trả về JSON thuần, không bọc trong markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.3")),
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        res = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=body,
        )
    if res.status_code == 429:
        raise AIError("Vượt hạn mức gọi AI của nhà cung cấp", "rate_limit")
    if res.status_code >= 400:
        raise AIError(f"AI Provider lỗi phía dịch vụ ({res.status_code})", "model_error")
    data = res.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise AIError("Phản hồi của AI không đúng cấu trúc mong đợi", "bad_format") from exc


def _call_ollama(prompt: str) -> str:
    body = {"model": MODEL_NAME, "prompt": prompt, "stream": False, "format": "json"}
    with httpx.Client(timeout=TIMEOUT) as client:
        res = client.post(f"{OLLAMA_BASE_URL}/api/generate", json=body)
    if res.status_code >= 400:
        raise AIError("Máy chủ Ollama nội bộ không phản hồi", "model_error")
    data = res.json()
    text = data.get("response", "")
    if not text:
        raise AIError("Phản hồi của AI rỗng", "empty")
    return text


_PROVIDER_CALLERS = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "ollama": _call_ollama,
}


def call_ai(prompt: str, kind: str = "generic", payload: Optional[Dict[str, Any]] = None) -> AIResult:
    """Gọi nhà cung cấp AI với cơ chế thử lại và phân loại lỗi rõ ràng.

    :raises AIError: khi mọi lần thử đều thất bại.
    """
    payload = payload or {}
    started = time.perf_counter()

    if PROVIDER == "mock" or PROVIDER not in _PROVIDER_CALLERS:
        text = _mock_response(kind, payload)
        return AIResult(
            text=text,
            source="ai",
            provider="mock",
            model="mock-local",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    caller = _PROVIDER_CALLERS[PROVIDER]
    last_error: Optional[AIError] = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            text = caller(prompt)
            if not text or not text.strip():
                raise AIError("Phản hồi của AI rỗng", "empty")
            return AIResult(
                text=text,
                source="ai",
                provider=PROVIDER,
                model=MODEL_NAME,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except httpx.TimeoutException as exc:
            last_error = AIError("Hết thời gian chờ phản hồi từ AI", "timeout")
        except AIError as exc:
            last_error = exc
            if exc.error_type in ("rate_limit", "model_error") and attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            if exc.error_type == "rate_limit":
                break
        except Exception as exc:  # pragma: no cover - phòng vệ
            last_error = AIError(f"Lỗi không xác định khi gọi AI: {exc}", "model_error")

        if last_error and last_error.error_type not in ("rate_limit", "timeout"):
            break

    raise last_error or AIError("Không gọi được nhà cung cấp AI", "model_error")
