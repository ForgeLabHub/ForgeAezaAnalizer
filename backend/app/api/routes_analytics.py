from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import PublishedSummary
from backend.app.auth.security import Unauthorized

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=PublishedSummary)
def summary(runtime: RuntimeDep, user: UserDep, response: Response,
            generation: Annotated[int | None, Query(ge=1)] = None):
    return version_headers(response, runtime.storage.summary(generation))


async def events(runtime, token: str, request: Request, last_id: int | None):
    cursor = last_id
    heartbeat = 0
    while not await request.is_disconnected():
        try:
            await run_in_threadpool(runtime.auth.authenticate, token)
        except Unauthorized:
            return
        summary = await run_in_threadpool(runtime.storage.summary)
        generation = summary["generation"]
        if generation != cursor:
            cursor = generation
            data = json.dumps(summary["version"], ensure_ascii=False)
            yield f"id: {generation}\nevent: analysis.updated\ndata: {data}\n\n"
            heartbeat = 0
        elif heartbeat >= 15:
            yield ": heartbeat\n\n"
            heartbeat = 0
        heartbeat += 1
        await asyncio.sleep(1)


@router.get("/events", response_class=StreamingResponse, responses={200: {
    "description": "Последняя опубликованная версия; повторное подключение через Last-Event-ID",
    "content": {"text/event-stream": {"schema": {"type": "string"}}},
}})
async def updates(request: Request, runtime: RuntimeDep, user: UserDep,
                  last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None):
    await run_in_threadpool(runtime.storage.summary)
    token = request.headers["authorization"].split(" ", 1)[1]
    return StreamingResponse(events(runtime, token, request, last_event_id),
        media_type="text/event-stream", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        })
