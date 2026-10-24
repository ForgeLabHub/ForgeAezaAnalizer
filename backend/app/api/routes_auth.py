from fastapi import APIRouter, Request, Response

from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.api.schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, runtime: RuntimeDep, response: Response, request: Request):
    response.headers["Cache-Control"] = "no-store"
    # The throttle keys on the caller so a burst aimed at one account cannot
    # exhaust the budget for unrelated users sharing the same egress address.
    client = request.client.host if request.client else ""
    return runtime.auth.login(payload.email, payload.password.get_secret_value(), client)


@router.get("/me", response_model=UserInfo)
def me(user: UserDep):
    return {"email": user.email}


@router.post("/logout", status_code=204)
def logout(runtime: RuntimeDep, user: UserDep):
    runtime.auth.logout(user)
    return Response(status_code=204)
