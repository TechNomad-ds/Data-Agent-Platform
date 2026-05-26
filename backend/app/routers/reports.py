"""报告导出路由"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.deps import get_current_user
from app.models.user import User
from app.services.report_generator import generate_report

router = APIRouter()


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
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        },
    )
