# CHOICES.md — Key Technical Decisions

This document covers three decisions that shaped the architecture of VibeSense AI.
For each: options I considered, what AI suggested, what I chose, and why.

---

## Decision 1 — Detection Model: YOLOv8n

### Options Considered

| Model | Latency | mAP@50 | Size | Notes |
|-------|---------|--------|------|-------|
| YOLOv8n | ~28ms | 37.3 | 6.3MB | Nano — fastest |
| YOLOv8s | ~45ms | 44.9 | 22MB | Small — more accurate |
| Faster R-CNN | ~120ms | 46.2 | 140MB | Two-stage — too slow |
| MobileNet-SSD | ~20ms | 23.1 | 6.9MB | Fast but insufficient accuracy |
| RT-DETR | ~35ms | 46.5 | 67MB | Strong but heavy for free-tier deploy |

### What AI Suggested

I asked Claude to evaluate these models for a retail analytics use case with 15fps CCTV
footage deployed on a resource-constrained server. The AI recommended YOLOv8s as a
better balance — arguing the 7 mAP improvement over YOLOv8n would meaningfully reduce
missed detections in partial occlusion scenarios (people behind displays, grouped entries).

### What I Chose and Why

I chose **YOLOv8n** and partially disagreed with the AI's reasoning.

The AI was correct that YOLOv8s has better detection accuracy. However, the deployment
context matters: the system runs on Render's free tier with limited CPU, and the detection
pipeline runs in a daemon thread sharing resources with the FastAPI server. At 15fps, a
45ms inference time means the pipeline cannot keep up in real time (45ms × 15fps = 675ms
of compute per second, leaving almost nothing for the API layer). YOLOv8n at 28ms keeps
the pipeline sustainable.

More importantly, in retail analytics the cost of a missed detection is low — a visitor
counted as 11 instead of 12 is acceptable. The cost of a lagging pipeline that causes
stale metrics or API timeouts is not. I chose latency over marginal accuracy.

**If I were deploying on dedicated GPU hardware**, I would reconsider YOLOv8s or RT-DETR.

---

## Decision 2 — Event Schema Design

### Options Considered

**Option A — Flat schema, one event type per action**
Every action (entry, zone visit, dwell, billing) is a separate event type with a fixed flat
structure. Simple to parse, easy to validate.

**Option B — Hierarchical schema with nested metadata**
A base event with a `metadata` field for type-specific data (queue_depth for billing events,
sku_zone for zone events, session_seq for ordering).

**Option C — Separate schemas per event type**
Different Pydantic models for ENTRY, ZONE_DWELL, BILLING_QUEUE_JOIN, etc.

### What AI Suggested

I asked Claude to design an event schema that would support the analytics queries in the
problem statement (funnel, heatmap, anomaly detection, conversion rate). The AI suggested
Option B — a unified base schema with a `metadata` dict for type-specific fields. Its
reasoning: a single schema simplifies the ingest endpoint (one Pydantic model validates
all events), and the `metadata` dict allows extension without breaking existing consumers.

### What I Chose and Why

I chose **Option B** and agreed with the AI's suggestion, but made one important addition.

The base schema includes all analytically critical fields at the top level — `visitor_id`,
`event_type`, `zone_id`, `dwell_ms`, `is_staff`, `confidence` — rather than nesting them
in metadata. This is intentional: the API's analytics queries filter and aggregate on these
fields constantly. Keeping them top-level means no JSON parsing inside query loops.

The `metadata` dict carries type-specific extensions (`queue_depth`, `sku_zone`,
`session_seq`) that are only relevant for specific event types. This keeps the core schema
stable while allowing the pipeline to add context without a schema migration.

One decision the AI didn't flag but I added: `confidence` is always emitted, never
suppressed. Low-confidence detections (0.3–0.6) are stored with their actual confidence
value rather than dropped. This allows the API to filter by confidence threshold at query
time, and preserves the ability to audit detection quality across zones.

---

## Decision 3 — API State: In-Memory vs Database

### Options Considered

**Option A — SQLite**
Persistent, zero external dependencies, file-based. Simple to deploy.

**Option B — PostgreSQL**
Production-grade, concurrent writes, query power. Requires a separate container.

**Option C — In-memory Python list**
Zero setup, zero latency, resets on restart. Suitable for prototype.

**Option D — Redis**
In-memory but persistent, pub/sub support, works across processes.

### What AI Suggested

I asked Claude what storage approach was appropriate for a challenge prototype that needs
to demonstrate production thinking without over-engineering. The AI recommended SQLite —
arguing it is persistent (survives restarts), requires no external service, and is one
`pip install` away. It pointed out that in-memory state would fail the "production-aware"
criterion in the problem statement since it resets on every deploy.

### What I Chose and Why

I chose **in-memory (Option C)** for the prototype and partially disagreed with the AI.

My reasoning: the problem statement's acceptance gate requires `docker compose up` to
work on a clean machine. Adding SQLite introduces a file path dependency and volume mount.
For a challenge submission where the evaluator will run the system once, the operational
simplicity of in-memory state outweighs the persistence benefit.

More importantly, the problem statement says "production-aware" — not "production-ready."
I demonstrated production awareness by:
1. Documenting the limitation explicitly in DESIGN.md and README.md
2. Designing `event_store.py` with a `add_event_from_model()` abstraction so the storage
   layer can be swapped to PostgreSQL without changing any API endpoint code
3. Using a module-level shared reference so test fixtures can call `events_db.clear()`
   to reset state between tests — exactly how a database transaction rollback would work

**In production with 40 stores**, I would use PostgreSQL with a connection pool and
partition the events table by `store_id` + date. The API query patterns (filter by
store_id, aggregate by event_type, window by timestamp) map cleanly to indexed SQL queries.

---

## Summary

| Decision | AI Suggestion | My Choice | Agreed? |
|---|---|---|---|
| Detection model | YOLOv8s (better accuracy) | YOLOv8n (lower latency) | Partial — context matters |
| Event schema | Unified base + metadata dict | Same, top-level critical fields | Yes, with additions |
| API storage | SQLite (persistent) | In-memory (simpler deployment) | Partial — documented tradeoff |