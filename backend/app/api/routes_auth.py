from fastapi import APIRouter, Response

from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.api.schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, runtime: RuntimeDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return runtime.auth.login(payload.email, payload.password.get_secret_value())


@router.get("/me", response_model=UserInfo)
def me(user: UserDep):
    return {"email": user.email}


@router.post("/logout", status_code=204)
def logout(runtime: RuntimeDep, user: UserDep):
    runtime.auth.logout(user)
    return Response(status_code=204)
