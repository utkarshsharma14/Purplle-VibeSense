# CHOICES.md

## Why FastAPI?

FastAPI was selected because it provides high performance, automatic OpenAPI documentation, built-in validation through Pydantic, and excellent support for real-time APIs.

## Why YOLOv8?

YOLOv8 was chosen because it offers a strong balance between detection accuracy and inference speed, making it suitable for real-time retail analytics.

## Why Rule-Based Vibe Classification?

A rule-based approach was selected because there is no labeled dataset available for "store vibe" classification. It also provides explainable decisions for store managers.

## Why Claude AI?

Claude was integrated to generate operational insights and recommendations from store telemetry data. This allows managers to receive human-readable suggestions instead of raw metrics.

## Why In-Memory Event Storage?

For the challenge prototype, an in-memory event store keeps the architecture lightweight and easy to deploy. In production, this can be replaced with PostgreSQL or Kafka.
