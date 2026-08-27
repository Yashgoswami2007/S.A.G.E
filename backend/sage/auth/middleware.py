from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from sage.auth.service import AuthService
from sage.core.exceptions import AuthError
from fastapi.responses import JSONResponse

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for certain routes
        path = request.url.path
        if path.startswith("/api/auth/") or path.startswith("/health") or path.startswith("/docs") or path.startswith("/openapi.json"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Missing or invalid authorization header"})

        token = auth_header.split(" ")[1]
        try:
            user_info = AuthService.verify_token(token)
            request.state.user = user_info
        except AuthError as e:
            return JSONResponse(status_code=401, content={"error": e.message})

        return await call_next(request)
