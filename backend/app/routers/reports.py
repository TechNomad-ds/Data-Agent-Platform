"""报告导出路由"""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.deps import get_current_user
from app.models.user import User
from app.services.report_generator import generate_report

router = APIRouter()


def _content_disposition(filename: str) -> str:
    """构造支持中文文件名的 Content-Disposition（RFC 5987）。

    HTTP header 只能用 latin-1 编码，中文文件名直接塞进去会 UnicodeEncodeError。
    这里同时给出 ASCII 兜底名和 UTF-8 百分号编码名，浏览器优先用后者。
    """
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "report.md"
    utf8_quoted = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_quoted}"


@router.post("/generate")
async def generate_report_endpoint(
    conversation_id: str,
    format: str = "markdown",
    current_user: User = Depends(get_current_user),
):
    """生成对话分析报告"""
    try:
        conv_id = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的对话 ID")

    result = await generate_report(conv_id, current_user.id, format)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return Response(
        content=result["content"].encode("utf-8"),
        media_type=result["content_type"],
        headers={
            "Content-Disposition": _content_disposition(result["filename"]),
        },
    )
