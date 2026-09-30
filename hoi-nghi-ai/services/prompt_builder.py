"""Bộ dựng prompt — tách prompt khỏi mã nghiệp vụ (tiêu chí 3: prompt có hệ thống).

Mọi prompt nằm trong thư mục prompts/ dưới dạng template có placeholder {{ten_bien}}.
Mã nghiệp vụ không bao giờ nối chuỗi prompt trực tiếp.
"""
import os
import re
from typing import Any, Dict, Optional

PROMPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts"
)

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_cache: Dict[str, str] = {}

# Quy tắc chung áp dụng cho MỌI prompt, bảo đảm tính nhất quán về vai trò và phạm vi.
GLOBAL_GUARDRAILS = (
    "Bạn là trợ lý của ban tổ chức hội nghị khoa học. Bạn chỉ hỗ trợ tóm tắt, phân loại và "
    "gợi ý; bạn KHÔNG đưa ra quyết định học thuật cuối cùng và không nhận xét chất lượng "
    "bài báo. Chỉ sử dụng dữ liệu được cung cấp, tuyệt đối không suy diễn hay bịa thêm thông tin. "
    "Trả về JSON thuần, không bọc trong markdown, không thêm lời dẫn."
)


def load_template(name: str) -> str:
    """Đọc template prompt từ thư mục prompts/ (có cache trong bộ nhớ)."""
    if name in _cache:
        return _cache[name]
    filename = name if name.endswith(".txt") else f"{name}.txt"
    path = os.path.join(PROMPT_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy template prompt: {filename}")
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    _cache[name] = content
    return content


def render(template: str, values: Dict[str, Any]) -> str:
    """Thay thế placeholder {{ten}} bằng giá trị tương ứng; placeholder thiếu → chuỗi rỗng."""

    def _sub(match):
        key = match.group(1)
        value = values.get(key, "")
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        if value is None:
            return ""
        return str(value)

    return _PLACEHOLDER.sub(_sub, template)


def build_prompt(name: str, values: Optional[Dict[str, Any]] = None) -> str:
    """Ghép quy tắc chung với template riêng của từng chức năng AI."""
    values = values or {}
    template = load_template(name)
    return f"{GLOBAL_GUARDRAILS}\n\n{render(template, values)}"


def prompt_version(name: str) -> str:
    """Mã phiên bản prompt để ghi vào nhật ký AI, phục vụ đối chiếu khi cần."""
    template = load_template(name)
    return f"{name}#{abs(hash(template)) % 10000:04d}"
