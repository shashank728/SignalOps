import asyncpg
import asyncio
import logging
from src.config import settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.pg_pool = None

    async def connect(self):
        logger.info("Connecting to Postgres...")
        
        for attempt in range(5):
            try:
                self.pg_pool = await asyncpg.create_pool(settings.POSTGRES_DSN)
                logger.info("Postgres connected")
                break
            except Exception as e:
                logger.warning(f"Postgres connection failed, retrying... ({e})")
                await asyncio.sleep(2)

    async def close(self):
        if self.pg_pool:
            await self.pg_pool.close()

    async def init_schema(self):
        if not self.pg_pool:
            return
            
        async with self.pg_pool.acquire() as conn:
            # Create postgres tables
            await conn.execute("""
            CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
            
            CREATE TABLE IF NOT EXISTS work_items (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                component_id  VARCHAR(128) NOT NULL,
                component_type VARCHAR(32) NOT NULL,
                severity      VARCHAR(4) NOT NULL,
                status        VARCHAR(32) NOT NULL DEFAULT 'OPEN',
                alert_type    VARCHAR(32) NOT NULL,
                signal_count  INTEGER NOT NULL DEFAULT 1,
                start_time    TIMESTAMPTZ NOT NULL,
                end_time      TIMESTAMPTZ,
                mttr_seconds  INTEGER,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS rca_records (
                id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                work_item_id      UUID NOT NULL REFERENCES work_items(id) UNIQUE,
                incident_start    TIMESTAMPTZ NOT NULL,
                incident_end      TIMESTAMPTZ NOT NULL,
                root_cause_category VARCHAR(64) NOT NULL,
                fix_applied       TEXT NOT NULL CHECK (char_length(fix_applied) >= 20),
                prevention_steps  TEXT NOT NULL CHECK (char_length(prevention_steps) >= 20),
                submitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Signals table to replace MongoDB
            CREATE TABLE IF NOT EXISTS signals (
                id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                signal_id       UUID UNIQUE NOT NULL,
                work_item_id    UUID REFERENCES work_items(id),
                component_id    VARCHAR(128) NOT NULL,
                component_type  VARCHAR(32) NOT NULL,
                severity        VARCHAR(4) NOT NULL,
                error_code      VARCHAR(64) NOT NULL,
                message         VARCHAR(512) NOT NULL,
                metadata        JSONB,
                timestamp       TIMESTAMPTZ NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Metrics table
            CREATE TABLE IF NOT EXISTS signal_metrics (
                id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                time          TIMESTAMPTZ NOT NULL,
                signal_count  INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status);
            CREATE INDEX IF NOT EXISTS idx_work_items_severity ON work_items(severity);
            CREATE INDEX IF NOT EXISTS idx_work_items_component ON work_items(component_id);
            
            CREATE INDEX IF NOT EXISTS idx_signals_work_item ON signals(work_item_id);
            CREATE INDEX IF NOT EXISTS idx_signals_comp_ts ON signals(component_id, timestamp DESC);
            """)

db_manager = DatabaseManager()

async def write_with_retry(write_fn, max_retries=3, base_delay=0.1):
    for attempt in range(max_retries):
        try:
            return await write_fn()
        except (ConnectionError, TimeoutError, asyncpg.exceptions.PostgresConnectionError) as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))
