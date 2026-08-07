"""LINE webhook + internal ask API."""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..classifier import classifier
from ..config import settings
from ..deps import check_rate_limit
from ..logging_setup import logger
from ..services.chat import ChatService
from ..services.rag import rag
from ..services.redis_service import RedisService, get_redis_svc
from ..state import resources

router = APIRouter()
chat_service = ChatService(rag)

# Keep strong references to fire-and-forget reply tasks so they are not GC'd.
_pending_replies: set[asyncio.Task] = set()


def _verify_line_signature(body: bytes, signature: str) -> bool:
    mac = hmac.HMAC(
        settings.LINE_CHANNEL_SECRET.get_secret_value().encode(), body, hashlib.sha256
    ).digest()
    return secrets.compare_digest(base64.b64encode(mac).decode(), signature)


async def _reply_line(reply_token: str, text: str) -> None:
    if not resources.http_client:
        return
    try:
        await resources.http_client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text[:5000]}]},
        )
    except Exception as e:
        logger.warning("line_reply_failed", err=str(e))


def _schedule_reply(reply_token: str, text: str) -> None:
    task = asyncio.create_task(_reply_line(reply_token, text))
    _pending_replies.add(task)
    task.add_done_callback(_pending_replies.discard)


@router.post("/line/webhook", dependencies=[Depends(check_rate_limit)])
async def line_webhook(request: Request, rs: RedisService = Depends(get_redis_svc)):
    body = await request.body()
    sig = request.headers.get("X-Line-Signature", "")
    if not sig:
        raise HTTPException(401, "Missing Signature")
    if not _verify_line_signature(body, sig):
        raise HTTPException(401, "Invalid Signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON") from None

    for ev in data.get("events", []):
        if ev.get("type") != "message" or ev["message"].get("type") != "text":
            continue
        uid = ev["source"].get("userId")
        if not uid:
            continue

        question = ev["message"]["text"].strip()
        if not question:
            continue
        result = await chat_service.answer(question, uid, rs)
        _schedule_reply(ev["replyToken"], result.text)

    return JSONResponse({"status": "ok"})


class AskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(min_length=1, max_length=2_000)
    receiver_user_id: str = Field(alias="receiver_userId", min_length=1, max_length=255)
    chat_room_id: str = ""
    channel_type: str = ""
    replyToken: str = ""


@router.post("/api/ask", dependencies=[Depends(check_rate_limit)])
async def api_ask(payload: AskRequest, rs: RedisService = Depends(get_redis_svc)):
    uid = f"api:{payload.receiver_user_id}"
    q = payload.question.strip()
    if not q:
        raise HTTPException(status_code=422, detail="question must not be blank")
    result = await chat_service.answer(q, uid, rs)
    ans = result.text

    is_ho = classifier.is_handover(ans)
    return {
        "user_id": payload.receiver_user_id,
        "question": q,
        "answer": ans,
        "cached": result.cached,
        "bot_status": "handover" if is_ho else "handled",
        "requires_admin": is_ho,
    }
