from typing import Annotated

from fastapi import APIRouter, Query, Response

from backend.app.api.deps import RuntimeDep, SourceIngestActorDep, UserDep, version_headers
from backend.app.api.schemas import SourceAccepted, SourceInfo
from backend.app.source import Snapshot

router = APIRouter(prefix="/source", tags=["source"])


@router.get("/snapshot", response_model=SourceInfo)
def source(runtime: RuntimeDep, user: UserDep, response: Response,
           generation: Annotated[int | None, Query(ge=1)] = None):
    return version_headers(response, runtime.storage.source(generation))


@router.put("/snapshot", response_model=SourceAccepted)
def import_source(payload: Snapshot, runtime: RuntimeDep, actor: SourceIngestActorDep, response: Response,
                  expected_generation: Annotated[int | None, Query(alias="expectedGeneration", ge=0)] = None):
    before = runtime.storage.load()
    state = runtime.core.update(source=payload.model_dump(mode="json", by_alias=True),
        expected_generation=expected_generation, actor=actor)
    counts = {key: len(rows) for key, rows in state.source.items()}
    if state.source_version == before.source_version:
        previous = counts
    else:
        previous = runtime.storage.source(state.generation - 1)["counts"] if state.generation > 1 else dict.fromkeys(counts, 0)
    return version_headers(response, {"snapshot": {"status": "accepted", **counts},
        "report": {"status": "succeeded", "accepted": counts, "rejected": 0, "duplicates": 0,
            "previous": previous, "message": "Снимок и расчёт опубликованы атомарно"}, **state.metadata()})


@router.get("/observations")
def observations(runtime: RuntimeDep, user: UserDep,
                 service_id: Annotated[int | None, Query(alias="serviceId", ge=1)] = None,
                 limit: Annotated[int, Query(ge=1, le=200)] = 100):
    return {"items": runtime.storage.observations(service_id=service_id, limit=limit),
        "note": "observedAt — время наблюдения; время самого события неизвестно"}
