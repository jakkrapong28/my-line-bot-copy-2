"""LINE webhook + internal ask API."""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from typing import Set

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..classifier import classifier
from ..config import settings
from ..deps import cache_key, check_rate_limit
from ..logging_setup import logger
from ..services.rag import rag
from ..services.redis_service import RedisService, get_redis_svc
from ..state import resources

router = APIRouter()

# Keep strong references to fire-and-forget reply tasks so they are not GC'd.
_pending_replies: Set[asyncio.Task] = set()


def _verify_line_signature(body: bytes, signature: str) -> bool:
    mac = hmac.HMAC(settings.LINE_CHANNEL_SECRET.get_secret_value().encode(), body, hashlib.sha256).digest()
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


async def _answer(question: str, user_id: str, rs: RedisService) -> str:
    key = cache_key(question)
    cached = await rs.get_cache(key)
    if cached:
        return cached
    history = await rs.get_history(user_id)
    answer = await rag.ask(question, history, rs, user_id)
    if not classifier.is_handover(answer):
        await rs.set_cache(key, answer)
    return answer


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
        raise HTTPException(400, "Invalid JSON")

    for ev in data.get("events", []):
        if ev.get("type") != "message" or ev["message"].get("type") != "text":
            continue
        uid = ev["source"].get("userId")
        if not uid:
            continue

        answer = await _answer(ev["message"]["text"].strip(), uid, rs)
        _schedule_reply(ev["replyToken"], answer)

    return JSONResponse({"status": "ok"})


class AskRequest(BaseModel):
    question: str
    receiver_userId: str
    chat_room_id: str = ""
    channel_type: str = ""
    replyToken: str = ""


@router.post("/api/ask", dependencies=[Depends(check_rate_limit)])
async def api_ask(payload: AskRequest, rs: RedisService = Depends(get_redis_svc)):
    uid = f"api:{payload.receiver_userId}"
    q = payload.question.strip()
    key = cache_key(q)

    cached_val = await rs.get_cache(key)
    cached = bool(cached_val)
    if cached_val:
        ans = cached_val
    else:
        history = await rs.get_history(uid)
        ans = await rag.ask(q, history, rs, uid)
        if not classifier.is_handover(ans):
            await rs.set_cache(key, ans)

    is_ho = classifier.is_handover(ans)
    return {
        "user_id": payload.receiver_userId,
        "question": q,
        "answer": ans,
        "cached": cached,
        "bot_status": "handover" if is_ho else "handled",
        "requires_admin": is_ho,
    }
