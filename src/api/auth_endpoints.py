import logging
import uuid
from datetime import timedelta

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from config.settings import get_redis_host, get_redis_port
from src.typing.user import Token, User, UserCreate, UserSettings, UserSettingsUpdate
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

    user_data = await redis_client.hgetall(f"users:{email}")
    if not user_data:
        raise credentials_exception

    # Parse settings from Redis (stored as JSON string)
    settings_str = user_data.pop("settings", None)
    if settings_str:
        import json

        try:
            settings_dict = json.loads(settings_str)
            settings = UserSettings(**settings_dict)
        except (json.JSONDecodeError, ValueError):
            settings = UserSettings()
    else:
        settings = UserSettings()

    # Convert is_active string to bool
    is_active = user_data.get("is_active", "true").lower() == "true"

    return User(
        id=user_data["id"],
        email=user_data["email"],
        full_name=user_data.get("full_name") or None,
        is_active=is_active,
        settings=settings,
    )


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
        "is_active": "true",
    }

    await redis_client.hset(f"users:{user.email}", mapping=user_db)

    return User(id=user_id, email=user.email, full_name=user.full_name, is_active=True)


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


@router.patch("/settings", response_model=UserSettings)
async def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis),
):
    """Update current user's settings (e.g., HITL mode)."""
    import json

    # Merge with existing settings
    current_settings = current_user.settings.model_dump()
    update_data = settings_update.model_dump(exclude_unset=True)
    current_settings.update(update_data)

    new_settings = UserSettings(**current_settings)

    # Save to Redis
    await redis_client.hset(
        f"users:{current_user.email}", "settings", json.dumps(new_settings.model_dump())
    )

    logger.info(f"Updated settings for user {current_user.email}: {new_settings}")
    return new_settings


@router.get("/settings", response_model=UserSettings)
async def get_user_settings(current_user: User = Depends(get_current_user)):
    """Get current user's settings."""
    return current_user.settings
