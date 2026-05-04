# Master Development Prompt: Mission-Critical Incident Management System (IMS)

## 0. Project Summary

Build a production-grade **Incident Management System (IMS)** that monitors a distributed stack (APIs, MCP Hosts, Distributed Caches, Async Queues, RDBMS, NoSQL stores) and manages the full incident mediation workflow from signal ingestion to root cause analysis. The system must handle **10,000 signals/second** without data loss, enforce business rules on state transitions, and expose a live incident dashboard.

**Repository structure (mandatory):**
```
/
├── backend/
│   ├── src/
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt  (or package.json / go.mod)
├── frontend/
│   ├── src/
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── scripts/
│   └── seed_failure_event.json   (mock RDBMS outage + MCP failure)
├── docs/
│   ├── architecture.md
│   └── backpressure.md
├── prompts/
│   └── (all AI prompts / specs used — commit these)
└── README.md
```

## 1. Technology Stack Decisions

Choose your stack and justify it in `docs/architecture.md`. Recommended defaults:

| Layer | Recommended | Rationale |
|---|---|---|
| Backend language | **Python (FastAPI + asyncio)** or **Go** | Native async/goroutines for concurrency |
| Signal ingestion protocol | **HTTP/2 + WebSocket** (primary) + optional Kafka consumer | High-throughput, low-latency |
| In-memory buffer | **asyncio.Queue** (Python) or **channels** (Go) | Backpressure-safe bounded buffer |
| NoSQL (raw signal sink) | **MongoDB** or **Cassandra** | High-write throughput, flexible schema |
| RDBMS (Work Items + RCA) | **PostgreSQL** | ACID transactions for state changes |
| Cache (hot-path dashboard) | **Redis** | Sub-millisecond dashboard reads |
| Timeseries aggregations | **TimescaleDB** (PostgreSQL extension) or **InfluxDB** | Native timeseries queries |
| Frontend | **React + TypeScript + Vite** | Component model fits incident detail views |
| Containerization | **Docker Compose** | Single-command local setup |

If you deviate from these, document why in `docs/architecture.md`.

## 2. Backend Architecture

### 2.1 Signal Ingestion (The Producer)

**Endpoint:** `POST /api/v1/signals`

**Request schema (enforce strictly):**
```json
{
  "signal_id": "uuid-v4",
  "component_id": "CACHE_CLUSTER_01",
  "component_type": "CACHE | RDBMS | API | MCP_HOST | QUEUE | NOSQL",
  "severity": "P0 | P1 | P2 | P3",
  "error_code": "string (max 64 chars)",
  "message": "string (max 512 chars)",
  "metadata": { "arbitrary": "key-value pairs" },
  "timestamp": "ISO 8601"
}
```

**Rate limiter (mandatory):**
- Implement a **sliding window rate limiter**: max **500 requests/second per IP**.
- When the limit is exceeded, return `HTTP 429 Too Many Requests` with a `Retry-After` header.
- Use a Redis-backed counter or an in-memory token bucket — do NOT use a naive sleep loop.
- Edge case: rate limiter state must **not** block the main event loop. Run it as a non-blocking check.

**In-memory buffer (mandatory for resilience):**
- All ingested signals go into a **bounded asyncio.Queue** (Python) or **buffered channel** (Go) with a max capacity of **50,000 items**.
- If the queue is full (persistence layer is slow), return `HTTP 503 Service Unavailable` with body `{"error": "backpressure", "retry_after_ms": 200}` — never drop silently.
- A separate async worker pool (min 4 workers) drains the queue and writes to the persistence layer.
- Edge case: if a worker crashes, it must be restarted automatically (use a supervisor pattern or task group with error handling).

**Debouncing logic (mandatory):**
- Maintain an in-memory dict `{component_id: (work_item_id, window_start_ts)}`.
- If `N >= 100` signals arrive for the same `component_id` within a **10-second sliding window**, only **one Work Item** is created.
- All signals in that window are linked to that Work Item in MongoDB via a `work_item_id` field.
- After the window expires, reset the counter for that component.
- Edge case: two concurrent workers could race to create a Work Item for the same `component_id`. Use a **distributed lock** (Redis `SET NX EX`) or an asyncio Lock to prevent duplicate Work Items.
- Edge case: signal arrives exactly at window boundary — assign to the **earlier** window.

### 2.2 Data Persistence Layer

**MongoDB — Raw Signal Sink:**
```
Collection: signals
Indexes:
  - { component_id: 1, timestamp: -1 }   (for debounce window queries)
  - { work_item_id: 1 }                   (for incident detail lookup)
  - { timestamp: -1 }                     (for time-range scans)
TTL index: { timestamp: 1 }, expireAfterSeconds: 2592000  (30-day audit log)
```

**PostgreSQL — Work Items + RCA (Source of Truth):**
```sql
CREATE TABLE work_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

CREATE TABLE rca_records (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_item_id      UUID NOT NULL REFERENCES work_items(id),
    incident_start    TIMESTAMPTZ NOT NULL,
    incident_end      TIMESTAMPTZ NOT NULL,
    root_cause_category VARCHAR(64) NOT NULL,
    fix_applied       TEXT NOT NULL CHECK (char_length(fix_applied) >= 20),
    prevention_steps  TEXT NOT NULL CHECK (char_length(prevention_steps) >= 20),
    submitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT rca_per_work_item UNIQUE (work_item_id)
);

CREATE INDEX idx_work_items_status ON work_items(status);
CREATE INDEX idx_work_items_severity ON work_items(severity);
CREATE INDEX idx_work_items_component ON work_items(component_id);
```

**State transitions must be transactional:**
- Use `BEGIN; SELECT ... FOR UPDATE; UPDATE ...; COMMIT;` to prevent concurrent state corruption.
- Rejected transitions must roll back cleanly.

**Redis — Hot-Path Dashboard Cache:**
```
Key: dashboard:live
Value: JSON array of work items with status OPEN or INVESTIGATING
TTL: 10 seconds (auto-refresh)
Update strategy: write-through on every Work Item status change
```

**TimescaleDB — Timeseries Aggregations:**
```sql
CREATE TABLE signal_metrics (
    time          TIMESTAMPTZ NOT NULL,
    component_id  VARCHAR(128),
    component_type VARCHAR(32),
    severity      VARCHAR(4),
    signal_count  INTEGER
);
SELECT create_hypertable('signal_metrics', 'time');
```
Aggregate into this table every 5 seconds from the in-memory counter.

### 2.3 Workflow Engine

**State Machine (State Pattern — mandatory):**

Implement a `WorkItemStateMachine` class with explicit state classes:

```
States:    OPEN → INVESTIGATING → RESOLVED → CLOSED
Allowed transitions:
  OPEN          → INVESTIGATING  (any authenticated user)
  INVESTIGATING → RESOLVED       (any authenticated user)
  RESOLVED      → CLOSED         (ONLY if RCA record exists and is complete)
  RESOLVED      → INVESTIGATING  (allowed — regression)
  CLOSED        → *              (NO transitions — terminal state)
```

Each state class implements:
- `can_transition_to(new_state: str) -> bool`
- `on_enter(work_item)` — side effects (e.g., set `end_time` on RESOLVED)
- `on_exit(work_item)` — cleanup

**Business rule (hard enforce):** Any call to `transition(work_item_id, "CLOSED")` must:
1. Query PostgreSQL for a `rca_records` row with matching `work_item_id`.
2. Verify `fix_applied` and `prevention_steps` are non-empty strings of at least 20 characters.
3. Verify `incident_start` < `incident_end`.
4. If any check fails, raise `RCAIncompleteError` and return `HTTP 422` with field-level error details.
5. On success, calculate `mttr_seconds = (incident_end - work_item.start_time).total_seconds()` and persist it.

**Alerting Strategy (Strategy Pattern — mandatory):**

```python
class AlertStrategy(ABC):
    @abstractmethod
    def build_alert(self, work_item: WorkItem) -> Alert: ...

class P0DatabaseAlert(AlertStrategy): ...   # RDBMS failure
class P1APIAlert(AlertStrategy): ...        # API failure
class P2CacheAlert(AlertStrategy): ...      # Cache failure
class P3QueueAlert(AlertStrategy): ...      # Queue degradation

ALERT_STRATEGY_MAP = {
    ("RDBMS",    "P0"): P0DatabaseAlert,
    ("API",      "P1"): P1APIAlert,
    ("CACHE",    "P2"): P2CacheAlert,
    ("QUEUE",    "P3"): P3QueueAlert,
    # ... cover all component_type × severity combinations
}
```

Alert payload (log to console + store in MongoDB):
```json
{
  "alert_id": "uuid",
  "work_item_id": "uuid",
  "alert_type": "P0_DATABASE_CRITICAL",
  "message": "human-readable alert message",
  "notified_at": "ISO 8601",
  "channels": ["slack", "pagerduty"]   // simulated — just log, don't actually call
}
```

### 2.4 API Endpoints (Full Specification)

```
POST   /api/v1/signals                  Ingest a signal
GET    /api/v1/work-items               List work items (filters: status, severity, component_type)
GET    /api/v1/work-items/{id}          Get work item detail
PATCH  /api/v1/work-items/{id}/status   Transition state { "status": "INVESTIGATING" }
GET    /api/v1/work-items/{id}/signals  Get raw signals (from MongoDB) paginated
POST   /api/v1/work-items/{id}/rca      Submit RCA record
GET    /api/v1/work-items/{id}/rca      Get RCA record
GET    /api/v1/dashboard                Get live dashboard (served from Redis cache)
GET    /api/v1/metrics                  Throughput metrics (signals/sec, queue depth, etc.)
GET    /health                          Health check
```

**Pagination:** All list endpoints must support `?page=1&limit=50` (max limit: 200).

**Filtering:** `GET /api/v1/work-items?status=OPEN&severity=P0&component_type=RDBMS`

**Sorting:** `GET /api/v1/work-items?sort=severity&order=asc`

**CORS:** Allow all origins in development (`*`); configure via environment variable in production.

### 2.5 Concurrency and Resilience

**Async processing:** Every database call must be non-blocking (`asyncpg`, `motor`, `aioredis`).

**DB write retry logic (mandatory):**
```python
async def write_with_retry(write_fn, max_retries=3, base_delay=0.1):
    for attempt in range(max_retries):
        try:
            return await write_fn()
        except (ConnectionError, TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(base_delay * (2 ** attempt))  # exponential backoff
```
Apply this wrapper to ALL PostgreSQL and MongoDB writes.

**No race conditions on status updates:** Use `SELECT ... FOR UPDATE` (PostgreSQL row-level lock) before every `UPDATE work_items SET status = ...`.

**Throughput metrics (mandatory):** Every 5 seconds, print to console:
```
[METRICS] signals_ingested=1240 signals_per_sec=248.0 queue_depth=0 work_items_open=3 db_write_errors=0
```
Use an `asyncio.Task` that loops with `asyncio.sleep(5)`.

**Health endpoint response:**
```json
{
  "status": "healthy | degraded | unhealthy",
  "checks": {
    "postgres": "ok | error",
    "mongodb": "ok | error",
    "redis": "ok | error",
    "queue_depth": 0,
    "queue_capacity": 50000
  },
  "uptime_seconds": 3600
}
```
Return `HTTP 200` if all checks pass, `HTTP 503` if any check fails.

## 3. Frontend Architecture

### 3.1 Tech Stack
- React 18 + TypeScript + Vite
- React Query (TanStack Query) for data fetching and caching
- React Router v6 for routing
- A UI component library of your choice (shadcn/ui, Radix UI, or custom)

### 3.2 Pages and Components

**Page: `/` — Live Incident Dashboard**

- **Auto-refreshes every 10 seconds** via React Query's `refetchInterval`.
- Displays active incidents sorted by severity: P0 → P1 → P2 → P3.
- Each incident card shows: severity badge, component ID, status badge, signal count, time since first signal (live countdown), alert type.
- Color coding: P0 = red, P1 = orange, P2 = yellow, P3 = blue.
- A top banner shows total open incidents and a throughput sparkline (last 60 seconds).
- Empty state: "No active incidents — system healthy 🟢" with a pulsing green dot.

**Page: `/incidents/:id` — Incident Detail**

Three-tab layout:

**Tab 1: Overview**
- Work Item fields (status, severity, component, alert type, signal count, start time, MTTR if resolved).
- Status transition button — context-aware:
  - OPEN → shows "Start Investigation" button
  - INVESTIGATING → shows "Mark Resolved" button
  - RESOLVED → shows "Close Incident" button (disabled + tooltip if RCA not submitted)
  - CLOSED → shows "Closed" badge, no action

**Tab 2: Raw Signals**
- Paginated table of signals from MongoDB (via `/api/v1/work-items/{id}/signals`).
- Columns: Timestamp, Component ID, Error Code, Message, Severity.
- Virtual scrolling for large signal lists (use `react-window` or `tanstack-virtual`).
- Filter by severity within the tab.

**Tab 3: Root Cause Analysis**
- If RCA not submitted: show the RCA form (see below).
- If RCA submitted: show read-only view of submitted RCA.

**RCA Form (mandatory fields):**
```
Incident Start *     [DateTime picker — pre-populated from work item start_time]
Incident End *       [DateTime picker — must be after Incident Start]
Root Cause Category * [Dropdown]:
  - Infrastructure Failure
  - Software Bug
  - Configuration Error
  - Human Error
  - Third-Party Dependency
  - Capacity Exhaustion
  - Security Incident
  - Unknown
Fix Applied *        [Textarea, min 20 chars, real-time char count]
Prevention Steps *   [Textarea, min 20 chars, real-time char count]
[Submit RCA] button  — disabled until all fields valid
```
- Client-side validation must mirror server-side rules exactly.
- On submit: optimistic update → show spinner → handle error state gracefully.
- On success: automatically switch to read-only view and enable the "Close Incident" button.

### 3.3 Edge Cases for UI
- Loading skeletons for every async data fetch (no raw spinners without context).
- Error boundaries around each tab — one tab failing must not crash the others.
- Network error toast: "Failed to update status — retrying..." with a manual retry button.
- If the user tries to close an incident without an RCA, show a blocking modal: "You must submit a Root Cause Analysis before closing this incident."
- Optimistic status transitions: update the UI immediately, roll back on error.
- Mobile-responsive: the dashboard and detail views must be usable on a 375px-wide screen.

## 4. Testing Requirements

### 4.1 Unit Tests (mandatory)

**RCA Validation Logic (minimum test cases):**
```python
def test_rca_rejected_if_fix_applied_too_short():
    ...  # fix_applied = "short" → expect RCAIncompleteError

def test_rca_rejected_if_prevention_steps_missing():
    ...  # prevention_steps = "" → expect RCAIncompleteError

def test_rca_rejected_if_end_before_start():
    ...  # incident_end < incident_start → expect RCAIncompleteError

def test_rca_accepted_with_valid_data():
    ...  # all fields valid → no exception

def test_closed_transition_rejected_without_rca():
    ...  # work_item has no rca_record → expect RCAIncompleteError

def test_closed_transition_accepted_with_complete_rca():
    ...  # complete rca_record present → status becomes CLOSED

def test_mttr_calculated_on_close():
    ...  # verify mttr_seconds = (incident_end - start_time).total_seconds()
```

**State Machine Tests:**
```python
def test_cannot_transition_from_closed():
    ...  # CLOSED → any state → expect InvalidTransitionError

def test_valid_transitions():
    ...  # OPEN → INVESTIGATING → RESOLVED → CLOSED (with RCA)

def test_regression_allowed():
    ...  # RESOLVED → INVESTIGATING → allowed
```

**Debounce Logic Tests:**
```python
def test_100_signals_create_one_work_item():
    ...

def test_signals_in_different_windows_create_separate_work_items():
    ...

def test_concurrent_signals_no_duplicate_work_items():
    ...  # simulate race condition with asyncio.gather
```

### 4.2 Integration Tests (recommended)

- Test the full signal → debounce → Work Item → state transition → RCA → close flow using an in-memory or test database.
- Test that `/health` returns 503 when PostgreSQL is unreachable.
- Test that the rate limiter returns 429 after the threshold is exceeded.

## 5. Seed Data Script

Create `scripts/seed_failure_event.json` with this scenario:

**Scenario: RDBMS Outage → MCP Host cascade failure**

```json
{
  "scenario": "RDBMS outage causes connection pool exhaustion, triggering MCP Host failures",
  "events": [
    {
      "delay_ms": 0,
      "signals": [
        {
          "component_id": "POSTGRES_PRIMARY_01",
          "component_type": "RDBMS",
          "severity": "P0",
          "error_code": "CONN_POOL_EXHAUSTED",
          "message": "All 100 connections exhausted. Queries timing out.",
          "metadata": { "pool_size": 100, "active_connections": 100, "waiting_queries": 247 }
        }
      ]
    },
    {
      "delay_ms": 3000,
      "signals": [
        {
          "component_id": "MCP_HOST_CLUSTER_A",
          "component_type": "MCP_HOST",
          "severity": "P1",
          "error_code": "UPSTREAM_DB_UNAVAILABLE",
          "message": "Cannot acquire DB connection. Returning 503 to clients.",
          "metadata": { "failed_requests_last_60s": 892, "upstream": "POSTGRES_PRIMARY_01" }
        },
        {
          "component_id": "MCP_HOST_CLUSTER_B",
          "component_type": "MCP_HOST",
          "severity": "P1",
          "error_code": "UPSTREAM_DB_UNAVAILABLE",
          "message": "Cannot acquire DB connection. Returning 503 to clients.",
          "metadata": { "failed_requests_last_60s": 654, "upstream": "POSTGRES_PRIMARY_01" }
        }
      ]
    },
    {
      "delay_ms": 8000,
      "signals": [
        {
          "component_id": "CACHE_CLUSTER_01",
          "component_type": "CACHE",
          "severity": "P2",
          "error_code": "CACHE_MISS_SPIKE",
          "message": "Cache miss rate 94% — stale data due to DB write failures.",
          "metadata": { "miss_rate_percent": 94 }
        }
      ]
    }
  ]
}
```

Also create `scripts/seed.py` (or `seed.sh`) that reads this file and POSTs each event to the ingestion endpoint with the specified delays.

## 6. Docker Compose

```yaml
version: "3.9"
services:
  postgres:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_DB: ims
      POSTGRES_USER: ims_user
      POSTGRES_PASSWORD: ims_pass
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ims_user -d ims"]
      interval: 5s
      timeout: 5s
      retries: 10

  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: ["mongodata:/data/db"]
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      POSTGRES_DSN: postgresql://ims_user:ims_pass@postgres:5432/ims
      MONGO_URI: mongodb://mongodb:27017/ims
      REDIS_URL: redis://redis:6379
      QUEUE_MAX_SIZE: 50000
      RATE_LIMIT_PER_SECOND: 500
      LOG_LEVEL: INFO
    depends_on:
      postgres: { condition: service_healthy }
      mongodb:  { condition: service_healthy }
      redis:    { condition: service_healthy }

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      VITE_API_BASE_URL: http://localhost:8000
    depends_on: [backend]

volumes:
  pgdata:
  mongodata:
```

## 7. README.md Requirements

The README must contain:

1. **Architecture Diagram** — ASCII or linked image showing: Signal → Rate Limiter → In-memory Queue → Worker Pool → MongoDB / PostgreSQL / Redis / TimescaleDB → Frontend.

2. **Setup Instructions:**
```bash
git clone <repo>
cd ims
docker compose up --build
# Visit http://localhost:3000
# Run seed script:
python scripts/seed.py --url http://localhost:8000
```

3. **Backpressure Handling section** — explain:
   - How the bounded queue absorbs bursts.
   - What happens when the queue fills (503 response with `retry_after_ms`).
   - How the worker pool's throughput determines the sustainable ingestion rate.
   - Why the rate limiter is the first line of defense, not the queue.

4. **Tech Stack Justification** — one paragraph per major component choice.

5. **Known Limitations and Future Work** — honest list.

## 8. Edge Cases and Error Handling Checklist

The following edge cases must be explicitly handled (reference each in code comments where applicable):

### Ingestion
- Duplicate `signal_id` → idempotent insert (upsert by signal_id in MongoDB)
- Missing required fields → `HTTP 422` with field-level validation errors
- `timestamp` in the future (> 60s ahead of server time) → reject with `HTTP 400`
- `timestamp` older than 24 hours → accept but log a warning
- `component_type` not in enum → `HTTP 422`
- Malformed JSON → `HTTP 400`
- Empty `message` field → `HTTP 422`
- Queue full → `HTTP 503` with `retry_after_ms`
- Rate limit exceeded → `HTTP 429` with `Retry-After`

### State Transitions
- Transition to current state (e.g., OPEN → OPEN) → `HTTP 400 "Already in this state"`
- Transition from CLOSED → any → `HTTP 409 "Work item is closed and immutable"`
- Skip state (OPEN → RESOLVED) → `HTTP 409 "Invalid transition"`
- Concurrent transition attempt → row lock ensures only one succeeds; second returns `HTTP 409`
- Work item not found → `HTTP 404`

### RCA
- Submit RCA for non-existent work item → `HTTP 404`
- Submit duplicate RCA → `HTTP 409 "RCA already submitted for this work item"`
- `fix_applied` < 20 chars → `HTTP 422` with field path
- `prevention_steps` < 20 chars → `HTTP 422` with field path
- `incident_end` ≤ `incident_start` → `HTTP 422`
- `root_cause_category` not in enum → `HTTP 422`
- Submit RCA for a CLOSED work item → `HTTP 409 "Work item already closed"`

### Debouncing
- Exactly 100 signals (boundary) → still one Work Item (use `>= 100`)
- 99 signals + 1 signal 11 seconds later → two Work Items
- Two concurrent requests for the same `component_id` → exactly one Work Item via distributed lock

### Database
- PostgreSQL connection failure → worker retries 3× with exponential backoff; logs error
- MongoDB connection failure → same retry logic
- Redis connection failure → fall back to direct PostgreSQL for dashboard reads; log degraded status
- TimescaleDB write failure → non-critical, log and continue (do not fail the main write path)

### Frontend
- API unreachable → error boundary shows "Service unavailable" with retry button
- Signal list empty (no signals yet linked) → "No signals linked yet"
- RCA form partially filled → browser navigation warning ("Leave page? Changes will be lost")
- Status transition takes > 3 seconds → show loading state; auto-cancel at 10 seconds
- Work item deleted (shouldn't happen, but 404 on detail page) → redirect to dashboard with toast

## 9. Bonus Points (Optional, High Impact)

- **WebSocket live feed:** Push new Work Items to the dashboard in real-time via WebSocket, eliminating the 10-second polling interval.
- **Signal replay:** A "Replay Signals" button on the incident detail page that re-runs the seed scenario.
- **Slack/PagerDuty webhook simulation:** Log a simulated webhook payload to a `webhooks.log` file when an alert is generated.
- **Audit log:** Every state transition appended to an `audit_log` PostgreSQL table with `(work_item_id, from_state, to_state, changed_by, changed_at)`.
- **Dark mode:** Full dark mode support in the frontend, respecting `prefers-color-scheme`.
- **Export to CSV:** Download all signals for an incident as a CSV file.
- **Multi-tenancy stub:** A `tenant_id` field on all resources, enforced via middleware, ready for future multi-tenancy.

## 10. Evaluation Self-Checklist

Before submission, verify:

- `docker compose up --build` starts all services cleanly from a fresh clone
- `python scripts/seed.py` creates Work Items and transitions state correctly
- `/health` returns `{"status": "healthy"}` when all services are running
- Console prints throughput metrics every 5 seconds
- POSTing 150 signals for the same component within 10 seconds creates exactly 1 Work Item
- Attempting `PATCH /work-items/{id}/status` with `{"status": "CLOSED"}` without RCA returns `HTTP 422`
- All unit tests pass (`pytest` or `go test ./...`)
- Frontend dashboard auto-refreshes and shows severity-sorted incidents
- RCA form validates client-side before allowing submission
- README contains Architecture Diagram, setup instructions, and Backpressure section
- All prompts/specs used are committed to `/prompts/`
