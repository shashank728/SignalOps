# Backpressure Handling

In a system expected to ingest 10,000 signals per second, handling backpressure gracefully is critical.

## 1. Rate Limiter (First Line of Defense)
The system uses a sliding window rate limiter backed by Redis. We limit traffic to **500 requests/second per IP**. If this limit is exceeded, the API responds with `HTTP 429 Too Many Requests` and a `Retry-After` header. This prevents a single misbehaving client from exhausting system resources.

## 2. In-Memory Bounded Queue (Burst Absorption)
Valid requests are pushed to an `asyncio.Queue` with a strict maximum capacity of **50,000 items**. This bounded queue absorbs temporary spikes in traffic. It decouples the fast ingestion endpoint from the relatively slower database writes.

## 3. Handling Queue Saturation
If the queue becomes full (indicating the backend workers or persistence layer cannot keep up), the system must not drop data silently. Instead, the `POST /api/v1/signals` endpoint immediately returns `HTTP 503 Service Unavailable` with `{"error": "backpressure", "retry_after_ms": 200}`. This explicit rejection forces upstream clients or load balancers to back off and retry.

## 4. Worker Pool Throughput
A pool of asynchronous workers drains the queue. Their throughput directly dictates the sustainable ingestion rate. To maximize throughput, these workers process signals and use non-blocking asynchronous calls to interact with Redis, MongoDB, and PostgreSQL. They implement retry logic with exponential backoff to handle transient database connection failures without dropping signals.
