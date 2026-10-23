from typing import Annotated

from fastapi import APIRouter, Query, Response

from backend.app.api.deps import RuntimeDep, UserDep, version_headers
from backend.app.api.schemas import ModelSettingsResponse, SettingsPatch

router = APIRouter(prefix="/model", tags=["model"])


def model_payload(runtime, generation=None):
    payload = runtime.storage.model(generation)
    definition = runtime.storage.summary(payload["generation"])["modelDefinition"]
    return {**payload, "factors": definition["factors"], "isDefault": payload["settings"] == definition["defaults"]}


@router.get("/settings", response_model=ModelSettingsResponse)
def settings(runtime: RuntimeDep, user: UserDep, response: Response,
             generation: Annotated[int | None, Query(ge=1)] = None):
    return version_headers(response, model_payload(runtime, generation))


@router.patch("/settings", response_model=ModelSettingsResponse)
def patch_settings(patch: SettingsPatch, runtime: RuntimeDep, user: UserDep, response: Response):
    values = patch.model_dump(exclude_unset=True)
    expected = values.pop("expectedGeneration", None)
    state = runtime.core.update(patch=values, expected_generation=expected, actor=user.email)
    return version_headers(response, model_payload(runtime, state.generation))


@router.post("/settings/reset", response_model=ModelSettingsResponse)
def reset_settings(runtime: RuntimeDep, user: UserDep, response: Response,
                   expected_generation: Annotated[int | None, Query(alias="expectedGeneration", ge=0)] = None):
    state = runtime.core.update(reset=True, expected_generation=expected_generation, actor=user.email)
    return version_headers(response, model_payload(runtime, state.generation))
