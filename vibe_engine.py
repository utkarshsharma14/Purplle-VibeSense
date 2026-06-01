"""
vibe_engine.py — Vibe Engine + Shared Metrics Registry

Responsibilities:
- Maintain store_metrics dict (read by FastAPI handlers)
- Classify store vibe from occupancy + zone activity
- Map vibe to ambient music
- Generate anomaly flags and realtime alerts
- Provide emit_event() for the detection pipeline
"""

import random
import logging
from datetime import datetime, timezone   # FIX: timezone-aware timestamps

from event_store import add_event

logger = logging.getLogger("vibesense")

# ── Shared metrics registry ───────────────────────────────────────────
# Written by VibeEngine (daemon thread), read by FastAPI handlers.
# Thread safety: GIL provides sufficient protection for dict reads.
# Production fix: replace with Redis pub/sub for multi-process safety.
store_metrics = {
    "current_count": 0,
    "vibe":          "Cozy & Premium",
    "ambient_music": "Soft acoustic melodies playing.",
    "realtime_alerts": [],
    "system_telemetry": {
        "status":                   "HEALTHY",
        "last_inference_timestamp": "",
        "anomaly_flag":             False,
        "pipeline_mode":            "STARTING",
    }
}

# ── Vibe thresholds ───────────────────────────────────────────────────
VIBE_ENERGETIC_THRESHOLD = 10   # people
VIBE_MODERATE_THRESHOLD  = 5

# 30-second hysteresis — prevents boundary flickering
# e.g. count oscillating between 9 and 11 won't flip vibe every cycle
_last_vibe_change = datetime.now(timezone.utc)
_current_vibe_level = "COZY"


class VibeEngine:

    def __init__(self):
        self.previous_count = 0
        self._seen_visitor_events: set = set()   # dedup within pipeline

    def emit_event(
        self,
        event_type: str,
        visitor_id: str,
        zone_id:    str  = None,
        dwell_ms:   int  = 0,
        is_staff:   bool = False,
        confidence: float = 0.95,
    ) -> None:
        """
        Emit a structured event from the detection pipeline into events_db.
        Deduplicates ENTRY events per visitor_id within a session to prevent
        re-entry inflation (same physical person re-entering = REENTRY, not ENTRY).
        """
        # Re-entry dedup: if visitor already has an ENTRY, emit REENTRY instead
        entry_key = f"{visitor_id}:ENTRY"
        if event_type == "ENTRY":
            if entry_key in self._seen_visitor_events:
                event_type = "REENTRY"
                logger.debug(f"Re-entry detected for {visitor_id}")
            else:
                self._seen_visitor_events.add(entry_key)

        # Clear entry key on EXIT so next appearance is fresh ENTRY
        if event_type == "EXIT":
            self._seen_visitor_events.discard(entry_key)

        add_event(
            store_id    = "STORE001",
            visitor_id  = visitor_id,
            event_type  = event_type,
            zone_id     = zone_id,
            dwell_ms    = dwell_ms,
            is_staff    = is_staff,
            confidence  = confidence,
        )
        logger.debug(f"Event emitted: {event_type} {visitor_id} zone={zone_id}")

    def process_frame_data(self, track_ids: list, boxes: list) -> None:
        """
        Called every frame by StoreMonitor.
        Updates store_metrics with current occupancy + vibe classification.

        When track_ids is empty (simulation mode), generates realistic
        random occupancy to drive the vibe engine and dashboard.
        """
        global _last_vibe_change, _current_vibe_level

        # ── Occupancy ─────────────────────────────────────────────────
        if track_ids:
            # Real pipeline — use actual tracked person count
            count = len(track_ids)
        else:
            # Simulation mode — generate realistic retail occupancy pattern
            count = random.randint(2, 14)

            # Simulate entry/exit events for the event store
            if count > self.previous_count:
                for _ in range(count - self.previous_count):
                    visitor_id = f"VISITOR_{random.randint(1000, 9999)}"
                    self.emit_event(
                        event_type="ENTRY",
                        visitor_id=visitor_id,
                    )
            elif count < self.previous_count:
                for _ in range(self.previous_count - count):
                    visitor_id = f"VISITOR_{random.randint(1000, 9999)}"
                    self.emit_event(
                        event_type="EXIT",
                        visitor_id=visitor_id,
                    )

        store_metrics["current_count"] = count
        self.previous_count = count

        # FIX: timezone-aware timestamp (was datetime.now() — naive)
        store_metrics["system_telemetry"][
            "last_inference_timestamp"
        ] = datetime.now(timezone.utc).isoformat()

        # ── Vibe classification with hysteresis ───────────────────────
        now = datetime.now(timezone.utc)
        seconds_since_change = (now - _last_vibe_change).total_seconds()

        if seconds_since_change >= 30:   # 30s hysteresis gate
            if count > VIBE_ENERGETIC_THRESHOLD:
                new_level = "ENERGETIC"
            elif count > VIBE_MODERATE_THRESHOLD:
                new_level = "MODERATE"
            else:
                new_level = "COZY"

            if new_level != _current_vibe_level:
                _current_vibe_level = new_level
                _last_vibe_change = now

        # Apply vibe
        if _current_vibe_level == "ENERGETIC":
            store_metrics["vibe"]          = "Energetic & Crowded"
            store_metrics["ambient_music"] = "Upbeat synth-pop tunes tracking."
            store_metrics["system_telemetry"]["anomaly_flag"] = True
            alert = "CRITICAL ANOMALY: Store capacity threshold exceeded."
            if alert not in store_metrics["realtime_alerts"]:
                store_metrics["realtime_alerts"].append(alert)

        elif _current_vibe_level == "MODERATE":
            store_metrics["vibe"]          = "Moderate & Buzzing"
            store_metrics["ambient_music"] = "Lo-Fi indie grooves streaming."
            store_metrics["system_telemetry"]["anomaly_flag"] = False

        else:
            store_metrics["vibe"]          = "Cozy & Premium"
            store_metrics["ambient_music"] = "Soft acoustic melodies playing."
            store_metrics["system_telemetry"]["anomaly_flag"] = False

        # Keep alert list bounded
        if len(store_metrics["realtime_alerts"]) > 5:
            store_metrics["realtime_alerts"].pop(0)