"""Authenticated single read-tool execution, before model tool calling."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.request_limits import bounded_body
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.tools.registry import execute_tool
from app.tools.schemas import ToolInvocation, ToolResult

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.post("/execute", response_model=ToolResult, openapi_extra={
    "requestBody": {"required": True, "content": {"application/json": {
        "schema": ToolInvocation.model_json_schema(),
    }}},
})
async def execute(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ToolResult:
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise HTTPException(415, "Use application/json")
    try:
        raw = await bounded_body(request, 8192)
        call = ToolInvocation.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid tool request") from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Request body timed out") from exc
    return await run_in_threadpool(execute_tool, call, db, user)
