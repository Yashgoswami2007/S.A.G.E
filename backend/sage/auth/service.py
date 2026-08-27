from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sage.core.schemas import TokenPair, UserInfo
from sage.core.exceptions import AuthError
from sage.core.utils import utc_now
from sage.config import settings
from sage.db.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = utc_now() + expires_delta
        else:
            expire = utc_now() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @classmethod
    async def login(cls, db: AsyncSession, username: str, password: str) -> TokenPair:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        if not user or not cls.verify_password(password, user.password_hash):
            raise AuthError("Invalid username or password")
            
        access_token_expires = timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
        access_token = cls.create_access_token(
            data={"sub": user.id, "role": user.role}, expires_delta=access_token_expires
        )
        refresh_token = cls.create_access_token(
            data={"sub": user.id, "type": "refresh"}, expires_delta=timedelta(days=7)
        )
        
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
        
    @classmethod
    def verify_token(cls, token: str) -> UserInfo:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id: str = payload.get("sub")
            if user_id is None:
                raise AuthError("Could not validate credentials")
            role: str = payload.get("role", "user")
            return UserInfo(sub=user_id, role=role)
        except JWTError:
            raise AuthError("Could not validate credentials")
