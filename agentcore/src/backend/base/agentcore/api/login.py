from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from agentcore.services.database.models.user.crud import get_user_by_username
from sqlalchemy.exc import IntegrityError

import httpx
from pydantic import BaseModel
from jose import jwt
import secrets
from agentcore.api.utils import DbSession
from agentcore.api.schemas import Token
from agentcore.services.auth.utils import (
    authenticate_user,
    create_refresh_token,
    create_user_tokens,
    get_password_hash,
)
from agentcore.services.database.models.user.crud import get_user_by_id
from agentcore.services.deps import get_settings_service
from agentcore.services.database.models.user.model import User
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.cache.user_cache import UserCacheService


class AzureSSORequest(BaseModel):
    idToken: str

class AzureSSOResponse(Token):
    role: str
    permissions: list[str]

router = APIRouter(tags=["Login"])


def _normalize_login_identity(value: str | None) -> str:
    identity = (value or "").strip()
    return identity.lower() if "@" in identity else identity


@router.post("/login", response_model=AzureSSOResponse)
async def login_to_get_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    auth_settings = get_settings_service().auth_settings
    try:
        user = await authenticate_user(form_data.username, form_data.password, db)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if user:
        tokens = await create_user_tokens(user_id=user.id, db=db, update_last_login=True)
        response.set_cookie(
            "refresh_token_lf",
            tokens["refresh_token"],
            httponly=auth_settings.REFRESH_HTTPONLY,
            samesite=auth_settings.REFRESH_SAME_SITE,
            secure=auth_settings.REFRESH_SECURE,
            expires=auth_settings.REFRESH_TOKEN_EXPIRE_SECONDS,
            domain=auth_settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            "access_token_lf",
            tokens["access_token"],
            httponly=auth_settings.ACCESS_HTTPONLY,
            samesite=auth_settings.ACCESS_SAME_SITE,
            secure=auth_settings.ACCESS_SECURE,
            expires=auth_settings.ACCESS_TOKEN_EXPIRE_SECONDS,
            domain=auth_settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            "apikey_tkn_lflw",
            str(user.store_api_key),
            httponly=auth_settings.ACCESS_HTTPONLY,
            samesite=auth_settings.ACCESS_SAME_SITE,
            secure=auth_settings.ACCESS_SECURE,
            expires=None,  # Set to None to make it a session cookie
            domain=auth_settings.COOKIE_DOMAIN,
        )
        current_role = normalize_role(getattr(user, "role", "developer"))
        permissions = await get_permissions_for_role(current_role)
        print(current_role,"current_roleeeeeeeeeee")
        print(permissions,"permissssssssssssssssions")
        return {
            **tokens,
            "role": current_role,
            "permissions": permissions
        }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/azure/sso", response_model=AzureSSOResponse)
async def azure_sso_login(
    body: AzureSSORequest,
    response: Response,
    db: DbSession,
):
    auth_settings = get_settings_service().auth_settings

    # -----------------------------
    # Verify Azure token
    # -----------------------------
    jwks_url = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
    async with httpx.AsyncClient() as client:
        jwks = (await client.get(jwks_url)).json()

    try:
        payload = jwt.decode(
            body.idToken,
            jwks,
            algorithms=["RS256"],
            audience=auth_settings.AZURE_CLIENT_ID,
            issuer=f"https://login.microsoftonline.com/{auth_settings.AZURE_TENANT_ID}/v2.0",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Azure token",
        ) from e

    email = payload.get("preferred_username") or payload.get("email")
    entra_object_id = payload.get("oid")
    normalized_email = _normalize_login_identity(email) if email else ""
    root_email = str(auth_settings.PLATFORM_ROOT_EMAIL).strip().lower() if auth_settings.PLATFORM_ROOT_EMAIL else ""

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Email not found in Azure token",
        )

    existing_user = await get_user_by_username(db, normalized_email)

    # -----------------------------
    # Find or Create User
    # -----------------------------
    user = existing_user
    resolved_role = "consumer"

    if root_email and normalized_email == root_email:
        resolved_role = "root"
        if user:
            if normalize_role(getattr(user, "role", "consumer")) != "root":
                user.role = "root"
                user.is_superuser = True
                db.add(user)
                await db.commit()
                await db.refresh(user)
    elif user:
        resolved_role = normalize_role(getattr(user, "role", "consumer"))
    else:
        resolved_role = "consumer"

    if not user:
        random_password = secrets.token_urlsafe(32)
        user = User(
            username=normalized_email,
            email=normalized_email,
            display_name=payload.get("name"),
            entra_object_id=entra_object_id,
            password=get_password_hash(random_password),
            role=resolved_role,
            is_superuser=resolved_role in {"root", "super_admin", "department_admin"},
            is_active=auth_settings.NEW_USER_IS_ACTIVE,
        )
        try:
            db.add(user)
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            existing_user = await get_user_by_username(db, normalized_email)
            if not existing_user:
                raise HTTPException(status_code=500, detail="Unable to provision SSO user.")
            user = existing_user
            resolved_role = normalize_role(getattr(user, "role", "consumer"))

    # DB role always wins for registered users (except configured root email override above)
    if user and not (root_email and normalized_email == root_email):
        resolved_role = normalize_role(getattr(user, "role", "consumer"))

    permissions = await get_permissions_for_role(resolved_role)

    settings_service = get_settings_service()
    user_cache = UserCacheService(settings_service)
    user_dict = user.model_dump(mode="json", exclude={"password"})
    await user_cache.set_user(user_dict)

    # -----------------------------
    # Issue LangBuilder Tokens
    # -----------------------------

    tokens = await create_user_tokens(user_id=user.id, db=db, update_last_login=True)
    
    response.set_cookie(
        "refresh_token_lf",
        tokens["refresh_token"],
        httponly=auth_settings.REFRESH_HTTPONLY,
        samesite=auth_settings.REFRESH_SAME_SITE,
        secure=auth_settings.REFRESH_SECURE,
        expires=auth_settings.REFRESH_TOKEN_EXPIRE_SECONDS,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    response.set_cookie(
        "access_token_lf",
        tokens["access_token"],
        httponly=auth_settings.ACCESS_HTTPONLY,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        expires=auth_settings.ACCESS_TOKEN_EXPIRE_SECONDS,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    response.set_cookie(
        "apikey_tkn_lflw",
        str(user.store_api_key),
        httponly=auth_settings.ACCESS_HTTPONLY,
        samesite=auth_settings.ACCESS_SAME_SITE,
        secure=auth_settings.ACCESS_SECURE,
        expires=None,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    return {
        **tokens,
        "role": resolved_role,
        "permissions": permissions
    }

@router.post("/refresh", response_model=AzureSSOResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: DbSession,
):
    auth_settings = get_settings_service().auth_settings

    token = request.cookies.get("refresh_token_lf")

    if token:
        tokens = await create_refresh_token(token, db)
        user_id = tokens.get("user_id") 
        user = await get_user_by_id(db, user_id)
        if not user:
             raise HTTPException(status_code=404, detail="User not found")
        user_role = normalize_role(getattr(user, "role", "developer"))
        permissions = await get_permissions_for_role(user_role)
        response.set_cookie(
            "refresh_token_lf",
            tokens["refresh_token"],
            httponly=auth_settings.REFRESH_HTTPONLY,
            samesite=auth_settings.REFRESH_SAME_SITE,
            secure=auth_settings.REFRESH_SECURE,
            expires=auth_settings.REFRESH_TOKEN_EXPIRE_SECONDS,
            domain=auth_settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            "access_token_lf",
            tokens["access_token"],
            httponly=auth_settings.ACCESS_HTTPONLY,
            samesite=auth_settings.ACCESS_SAME_SITE,
            secure=auth_settings.ACCESS_SECURE,
            expires=auth_settings.ACCESS_TOKEN_EXPIRE_SECONDS,
            domain=auth_settings.COOKIE_DOMAIN,
        )
        return {
            **tokens,
            "role": user_role,
            "permissions": permissions
        }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token_lf")
    response.delete_cookie("access_token_lf")
    response.delete_cookie("apikey_tkn_lflw")
    return {"message": "Logout successful"}

# @router.post("/logout")
# async def logout(response: Response):
#     auth_settings = get_settings_service().auth_settings
    
#     cookie_params = {
#         "domain": auth_settings.COOKIE_DOMAIN,
#         "path": "/", # Ensure this matches where the cookie was set
#         "httponly": True,
#         "samesite": auth_settings.REFRESH_SAME_SITE,
#         "secure": auth_settings.REFRESH_SECURE,
#     }

#     response.delete_cookie("refresh_token_lf", **cookie_params)
#     response.delete_cookie("access_token_lf", **cookie_params)
#     response.delete_cookie("apikey_tkn_lflw", **cookie_params)
    
#     return {"message": "Logout successful"}
