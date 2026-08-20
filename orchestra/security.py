import secrets
import time
from collections import defaultdict
from dataclasses import dataclass

import jwt
from fastapi import Request
from redis.asyncio import Redis

from orchestra.config import Settings

ROLE_LEVELS = {"viewer": 10, "operator": 20, "manager": 30, "admin": 40}


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    tenant_id: str
    auth_type: str

    def can(self, minimum_role: str) -> bool:
        return ROLE_LEVELS.get(self.role, 0) >= ROLE_LEVELS[minimum_role]


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(self, authorization: str, api_key: str) -> Principal | None:
        if authorization.startswith("Bearer ") and self.settings.jwt_secret:
            token = authorization.removeprefix("Bearer ").strip()
            try:
                payload = jwt.decode(
                    token,
                    self.settings.jwt_secret,
                    algorithms=["HS256"],
                    issuer=self.settings.jwt_issuer,
                    options={"require": ["exp", "iat", "iss", "sub"]},
                )
            except jwt.PyJWTError:
                return None
            role = payload.get("role", "viewer")
            if role not in ROLE_LEVELS:
                return None
            return Principal(
                str(payload["sub"]),
                role,
                str(payload.get("tenant_id", "default")),
                "jwt",
            )

        for configured_key, credentials in self.settings.api_key_credentials.items():
            if api_key and secrets.compare_digest(api_key, configured_key):
                return Principal(
                    f"api-key:{credentials['role']}",
                    credentials["role"],
                    credentials["tenant_id"],
                    "api_key",
                )

        if not self.settings.api_key_roles and not self.settings.jwt_secret:
            return Principal("local-development", "admin", "default", "disabled")
        return None

    def from_request(self, request: Request) -> Principal | None:
        return self.authenticate(
            request.headers.get("authorization", ""),
            request.headers.get("x-api-key", ""),
        )


class RateLimiter:
    """Fixed-window limiter backed by Redis with a local development fallback."""

    def __init__(self, settings: Settings) -> None:
        self.limit = settings.rate_limit_per_minute
        self.production = settings.environment == "production"
        self.redis = Redis.from_url(settings.redis_url) if settings.redis_url else None
        self.local: dict[tuple[str, int], int] = defaultdict(int)

    async def allow(self, identity: str) -> tuple[bool, int]:
        window = int(time.time() // 60)
        key = f"orchestra:rate:{identity}:{window}"
        if self.redis:
            try:
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, 65)
                return count <= self.limit, max(0, self.limit - count)
            except Exception:
                if self.production:
                    raise
        local_key = (identity, window)
        self.local[local_key] += 1
        if len(self.local) > 10_000:
            self.local = {
                item: count for item, count in self.local.items() if item[1] >= window - 1
            }
        count = self.local[local_key]
        return count <= self.limit, max(0, self.limit - count)

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()
