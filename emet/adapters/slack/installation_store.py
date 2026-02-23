"""Slack OAuth installation store — Redis cache + PostgreSQL persistence.

Two-layer storage:
  - Redis: Fast reads (cache, TTL-based expiry)
  - PostgreSQL: Durable persistence (survives restarts)

On save: write to both.
On read: try Redis first, fall back to Postgres (and backfill Redis on miss).
On delete: remove from both.

Usage:
    store = DualInstallationStore(
        redis_url="redis://localhost:6379/0",
        database_url="postgresql://ftm:ftm@localhost:5432/emet",
    )
    await store.initialize()   # Creates Postgres table if needed
    await store.save(installation)
    inst = await store.find_by_team("T12345")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from emet.adapters.slack.oauth import InstallationStore, SlackInstallation

logger = logging.getLogger(__name__)

# Redis key prefix
_REDIS_PREFIX = "emet:slack:install"
_REDIS_TTL = 60 * 60 * 24  # 24 hours


# ---------------------------------------------------------------------------
# Redis layer
# ---------------------------------------------------------------------------


class RedisInstallationCache:
    """Redis cache for Slack installations."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                )
            except ImportError:
                logger.warning("redis package not installed; cache disabled")
                return None
            except Exception as exc:
                logger.warning("Redis connection failed: %s", exc)
                return None
        return self._redis

    async def set(self, key: str, installation: SlackInstallation) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            data = json.dumps(installation.to_dict())
            await r.set(f"{_REDIS_PREFIX}:{key}", data, ex=_REDIS_TTL)
        except Exception as exc:
            logger.warning("Redis SET failed: %s", exc)

    async def get(self, key: str) -> SlackInstallation | None:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            data = await r.get(f"{_REDIS_PREFIX}:{key}")
            if data:
                return SlackInstallation.from_dict(json.loads(data))
        except Exception as exc:
            logger.warning("Redis GET failed: %s", exc)
        return None

    async def delete(self, key: str) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.delete(f"{_REDIS_PREFIX}:{key}")
        except Exception as exc:
            logger.warning("Redis DELETE failed: %s", exc)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None


# ---------------------------------------------------------------------------
# PostgreSQL layer
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS slack_installations (
    team_id         TEXT PRIMARY KEY,
    team_name       TEXT NOT NULL,
    bot_token       TEXT NOT NULL,
    bot_user_id     TEXT NOT NULL,
    installed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    installer_user_id TEXT NOT NULL,
    org_id          TEXT,
    enterprise_id   TEXT,
    enterprise_name TEXT,
    is_enterprise_install BOOLEAN DEFAULT FALSE,
    incoming_webhook JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_slack_install_org ON slack_installations(org_id);
CREATE INDEX IF NOT EXISTS idx_slack_install_enterprise ON slack_installations(enterprise_id);
"""


class PostgresInstallationStore:
    """PostgreSQL durable store for Slack installations."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: Any = None

    async def initialize(self) -> None:
        """Create table if needed and open connection pool."""
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE)
            logger.info("Slack installation table ready")
        except ImportError:
            logger.warning("asyncpg not installed; Postgres store disabled")
        except Exception as exc:
            logger.warning("Postgres initialization failed: %s", exc)

    async def save(self, installation: SlackInstallation) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO slack_installations
                        (team_id, team_name, bot_token, bot_user_id, installed_at,
                         installer_user_id, org_id, enterprise_id, enterprise_name,
                         is_enterprise_install, incoming_webhook, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (team_id) DO UPDATE SET
                        team_name = EXCLUDED.team_name,
                        bot_token = EXCLUDED.bot_token,
                        bot_user_id = EXCLUDED.bot_user_id,
                        installer_user_id = EXCLUDED.installer_user_id,
                        org_id = EXCLUDED.org_id,
                        enterprise_id = EXCLUDED.enterprise_id,
                        enterprise_name = EXCLUDED.enterprise_name,
                        is_enterprise_install = EXCLUDED.is_enterprise_install,
                        incoming_webhook = EXCLUDED.incoming_webhook,
                        updated_at = EXCLUDED.updated_at
                    """,
                    installation.team_id,
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_user_id,
                    installation.installed_at,
                    installation.installer_user_id,
                    installation.org_id,
                    installation.enterprise_id,
                    installation.enterprise_name,
                    installation.is_enterprise_install,
                    json.dumps(installation.incoming_webhook) if installation.incoming_webhook else None,
                    datetime.now(timezone.utc),
                )
        except Exception as exc:
            logger.error("Postgres SAVE failed: %s", exc)
            raise

    async def find_by_team(self, team_id: str) -> SlackInstallation | None:
        if self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM slack_installations WHERE team_id = $1",
                    team_id,
                )
                return self._row_to_installation(row) if row else None
        except Exception as exc:
            logger.error("Postgres find_by_team failed: %s", exc)
            return None

    async def find_by_enterprise(self, enterprise_id: str) -> SlackInstallation | None:
        if self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM slack_installations WHERE enterprise_id = $1 LIMIT 1",
                    enterprise_id,
                )
                return self._row_to_installation(row) if row else None
        except Exception as exc:
            logger.error("Postgres find_by_enterprise failed: %s", exc)
            return None

    async def find_by_org(self, org_id: str) -> list[SlackInstallation]:
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM slack_installations WHERE org_id = $1",
                    org_id,
                )
                return [self._row_to_installation(r) for r in rows]
        except Exception as exc:
            logger.error("Postgres find_by_org failed: %s", exc)
            return []

    async def delete(self, team_id: str) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM slack_installations WHERE team_id = $1",
                    team_id,
                )
                return "DELETE 1" in result
        except Exception as exc:
            logger.error("Postgres DELETE failed: %s", exc)
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _row_to_installation(row: Any) -> SlackInstallation:
        webhook = row["incoming_webhook"]
        if isinstance(webhook, str):
            webhook = json.loads(webhook)
        return SlackInstallation(
            team_id=row["team_id"],
            team_name=row["team_name"],
            bot_token=row["bot_token"],
            bot_user_id=row["bot_user_id"],
            installed_at=row["installed_at"],
            installer_user_id=row["installer_user_id"],
            org_id=row["org_id"],
            enterprise_id=row["enterprise_id"],
            enterprise_name=row["enterprise_name"],
            is_enterprise_install=row["is_enterprise_install"],
            incoming_webhook=webhook,
        )


# ---------------------------------------------------------------------------
# Dual store — the one adapters should use
# ---------------------------------------------------------------------------


class DualInstallationStore(InstallationStore):
    """Redis cache + PostgreSQL persistence for Slack installations.

    Write-through: saves hit both layers.
    Read-through: cache miss backfills from Postgres.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        database_url: str = "",
    ) -> None:
        self._cache = RedisInstallationCache(redis_url)
        self._db = PostgresInstallationStore(database_url) if database_url else None

    async def initialize(self) -> None:
        """Initialize Postgres (creates table if needed)."""
        if self._db is not None:
            await self._db.initialize()

    async def save(self, installation: SlackInstallation) -> None:
        """Write to Postgres first (source of truth), then cache."""
        if self._db is not None:
            await self._db.save(installation)
        await self._cache.set(f"team:{installation.team_id}", installation)
        if installation.enterprise_id:
            await self._cache.set(f"ent:{installation.enterprise_id}", installation)

    async def find_by_team(self, team_id: str) -> SlackInstallation | None:
        # Try cache first
        cached = await self._cache.get(f"team:{team_id}")
        if cached is not None:
            return cached

        # Cache miss → query Postgres
        if self._db is not None:
            found = await self._db.find_by_team(team_id)
            if found is not None:
                # Backfill cache
                await self._cache.set(f"team:{team_id}", found)
            return found

        return None

    async def find_by_enterprise(
        self, enterprise_id: str,
    ) -> SlackInstallation | None:
        cached = await self._cache.get(f"ent:{enterprise_id}")
        if cached is not None:
            return cached

        if self._db is not None:
            found = await self._db.find_by_enterprise(enterprise_id)
            if found is not None:
                await self._cache.set(f"ent:{enterprise_id}", found)
            return found

        return None

    async def delete(self, team_id: str) -> bool:
        # Remove from cache
        await self._cache.delete(f"team:{team_id}")

        # Remove from Postgres
        if self._db is not None:
            return await self._db.delete(team_id)
        return True

    async def find_by_org(self, org_id: str) -> list[SlackInstallation]:
        if self._db is not None:
            return await self._db.find_by_org(org_id)
        return []

    async def close(self) -> None:
        """Shut down both layers."""
        await self._cache.close()
        if self._db is not None:
            await self._db.close()
