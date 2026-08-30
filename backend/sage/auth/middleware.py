from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from sage.core.schemas import UserInfo


class AuthMiddleware(BaseHTTPMiddleware):
    """Auth middleware — currently a pass-through for offline/local usage.

    SAGE is designed for sovereign, air-gapped deployments where all access
    is local.  Authentication can be re-enabled in the future by uncommenting
    the token-validation logic below.
    """

    async def dispatch(self, request: Request, call_next):
        # Inject a default local operator identity so downstream code that
        # inspects request.state.user still works without changes.
        request.state.user = UserInfo(sub="local-operator", role="admin")
        return await call_next(request)

        # ── Future: uncomment the block below to re-enable JWT auth ──
        # path = request.url.path
        # if path.startswith("/api/auth/") or path.startswith("/health") or path.startswith("/docs") or path.startswith("/openapi.json"):
        #     return await call_next(request)
        #
        # auth_header = request.headers.get("Authorization")
        # if not auth_header or not auth_header.startswith("Bearer "):
        #     return JSONResponse(status_code=401, content={"error": "Missing or invalid authorization header"})
        #
        # token = auth_header.split(" ")[1]
        # try:
        #     from sage.auth.service import AuthService
        #     user_info = AuthService.verify_token(token)
        #     request.state.user = user_info
        # except Exception as e:
        #     from fastapi.responses import JSONResponse
        #     return JSONResponse(status_code=401, content={"error": str(e)})
        #
        # return await call_next(request)
