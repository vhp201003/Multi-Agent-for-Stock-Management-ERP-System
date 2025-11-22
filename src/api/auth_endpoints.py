import logging
import uuid
from datetime import timedelta

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from config.settings import get_redis_host, get_redis_port
from src.typing.user import Token, User, UserCreate
from src.utils.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


async def get_redis():
    client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


async def get_current_user(
    token: str = Depends(oauth2_scheme), redis_client: redis.Redis = Depends(get_redis)
) -> User:
    from jose import JWTError, jwt
    from src.utils.auth import ALGORITHM, SECRET_KEY

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # In a real app, you'd fetch user from DB. Here we simulate with Redis or just return basic info
    # For now, let's assume we store users in Redis hash "users:{email}"
    user_data = await redis_client.hgetall(f"users:{email}")
    if not user_data:
        raise credentials_exception
    
    return User(**user_data)


@router.post("/register", response_model=User)
async def register(user: UserCreate, redis_client: redis.Redis = Depends(get_redis)):
    # Check if user exists
    if await redis_client.exists(f"users:{user.email}"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    hashed_password = get_password_hash(user.password)
    user_id = str(uuid.uuid4())
    
    user_db = {
        "id": user_id,
        "email": user.email,
        "full_name": user.full_name or "",
        "hashed_password": hashed_password,
        "is_active": "true"
    }
    
    await redis_client.hset(f"users:{user.email}", mapping=user_db)
    
    return User(
        id=user_id,
        email=user.email,
        full_name=user.full_name,
        is_active=True
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    redis_client: redis.Redis = Depends(get_redis),
):
    user_data = await redis_client.hgetall(f"users:{form_data.username}")
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not verify_password(form_data.password, user_data["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_data["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
