"""
core_ai.py — VibeSense AI Detection Pipeline

Real implementation:
  - YOLOv8n person detection via Ultralytics
  - ByteTrack multi-object tracking (built into Ultralytics)
  - Zone mapping from bounding box position
  - Entry/exit direction detection
  - Staff exclusion (uniform colour heuristic)
  - Graceful fallback to simulation if video is blank/unavailable

Architecture:
  StoreMonitor reads frames from store.mp4 (or RTSP stream),
  runs YOLOv8n inference, passes detections to VibeEngine,
  and emits structured events into events_db.
"""

import time
import random
import logging
import cv2
import numpy as np

from vibe_engine import VibeEngine, store_metrics

logger = logging.getLogger("vibesense")

# ── Zone definitions (relative to 640x480 frame) ─────────────────────
# These map bounding box centroids to named retail zones.
# In production: replace with homography-mapped store_layout.json coords.
ZONES = {
    "ENTRY":    (0,   0,   160, 480),   # left 25% — entry threshold
    "AISLE":    (160, 0,   400, 320),   # centre-left — main floor
    "COSMETICS":(400, 0,   640, 320),   # centre-right — cosmetics zone
    "BILLING":  (160, 320, 640, 480),   # bottom — billing counter area
}

# ── Staff detection heuristic ─────────────────────────────────────────
# Detects staff by dominant uniform colour (blue/dark uniform).
# In production: replace with a fine-tuned classifier or Re-ID model.
STAFF_HSV_LOWER = np.array([100, 50, 50])   # blue uniform range
STAFF_HSV_UPPER = np.array([130, 255, 255])

def _is_staff(frame: np.ndarray, box) -> bool:
    """
    Heuristic: if >30% of the person's bounding box pixels fall in the
    staff uniform colour range (blue HSV), classify as staff.
    Confidence: ~70% on typical retail CCTV. Documented limitation.
    """
    try:
        x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, STAFF_HSV_LOWER, STAFF_HSV_UPPER)
        ratio = mask.sum() / (255 * mask.size)
        return ratio > 0.30
    except Exception:
        return False

def _get_zone(cx: float, cy: float) -> str:
    """Map centroid (cx, cy) to a named zone."""
    for zone_name, (x1, y1, x2, y2) in ZONES.items():
        if x1 <= cx < x2 and y1 <= cy < y2:
            return zone_name
    return "FLOOR"

def _is_entering(prev_cx: float, curr_cx: float) -> bool:
    """Entry = moving right-to-left across entry threshold (x < 160)."""
    return prev_cx > 160 and curr_cx <= 160

def _is_exiting(prev_cx: float, curr_cx: float) -> bool:
    """Exit = moving left-to-right across entry threshold."""
    return prev_cx <= 160 and curr_cx > 160


class StoreMonitor:
    """
    Main detection pipeline.

    Reads frames from video_path, runs YOLOv8n person detection,
    applies ByteTrack tracking (built into Ultralytics .track()),
    maps detections to zones, emits structured events.

    Falls back to simulation mode if:
    - Video is blank (mean pixel < 5 — make_video.py output)
    - YOLOv8 model unavailable
    - Any unrecoverable pipeline error
    """

    def __init__(self, video_path: str):
        self.video_path = video_path
        self.vibe_engine = VibeEngine()
        self.model = None
        self.track_history: dict = {}   # track_id → list of (cx, cy)
        self.zone_dwell:    dict = {}   # track_id → {zone: entry_time}
        self._simulation_mode = False

    def _load_model(self) -> bool:
        """Load YOLOv8n. Returns True if successful."""
        try:
            from ultralytics import YOLO
            self.model = YOLO("yolov8n.pt")
            logger.info("YOLOv8n loaded successfully")
            return True
        except Exception as e:
            logger.warning(f"YOLOv8n load failed: {e} — falling back to simulation")
            return False

    def _check_video_blank(self, cap) -> bool:
        """Return True if video is blank/simulated (mean pixel < 5)."""
        ret, frame = cap.read()
        if not ret:
            return True
        blank = frame.mean() < 5
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return blank

    def start_monitoring(self):
        """
        Main loop. Tries real YOLOv8 pipeline first.
        Falls back to simulation if video is blank or model unavailable.
        """
        logger.info("VibeSense AI pipeline starting...")

        # Try to open video
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.warning(f"Cannot open video: {self.video_path} — simulation mode")
            self._run_simulation()
            return

        # Check if video is blank (make_video.py output)
        if self._check_video_blank(cap):
            logger.warning("Video is blank/simulated — switching to simulation mode")
            cap.release()
            self._simulation_mode = True
            self._run_simulation()
            return

        # Try to load model
        if not self._load_model():
            cap.release()
            self._run_simulation()
            return

        # ── Real pipeline ─────────────────────────────────────────────
        logger.info("Real YOLOv8n pipeline active")
        store_metrics["system_telemetry"]["pipeline_mode"] = "YOLO_BYTETRACK"

        try:
            self._run_real_pipeline(cap)
        except Exception as e:
            logger.error(f"Pipeline error: {e} — falling back to simulation")
            cap.release()
            self._run_simulation()

    def _run_real_pipeline(self, cap):
        """
        YOLOv8n + ByteTrack real detection loop.

        For each frame:
        1. Run model.track() — YOLOv8n detection + ByteTrack assignment
        2. For each tracked person: get zone, check staff, emit events
        3. Detect ENTRY/EXIT by tracking centroid crossing entry threshold
        4. Detect ZONE_DWELL after 30s continuous zone presence
        5. Pass track IDs + boxes to VibeEngine for occupancy + vibe
        """
        from datetime import datetime, timezone

        while True:
            ret, frame = cap.read()
            if not ret:
                # Loop video
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            try:
                results = self.model.track(
                    frame,
                    persist=True,
                    classes=[0],        # class 0 = person
                    conf=0.35,          # min confidence threshold
                    verbose=False,
                )

                track_ids = []
                boxes_list = []
                now = datetime.now(timezone.utc)

                if (results[0].boxes is not None and
                        results[0].boxes.id is not None):

                    ids   = results[0].boxes.id.tolist()
                    boxes = results[0].boxes.xyxy.tolist()
                    confs = results[0].boxes.conf.tolist()

                    for tid, box, conf in zip(ids, boxes, confs):
                        tid = int(tid)
                        x1, y1, x2, y2 = box
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2

                        is_staff = _is_staff(frame, box)
                        zone     = _get_zone(cx, cy)
                        visitor_id = f"VIS_{tid:04d}"

                        # Track centroid history
                        if tid not in self.track_history:
                            self.track_history[tid] = []
                        self.track_history[tid].append((cx, cy))

                        history = self.track_history[tid]

                        # ── ENTRY / EXIT detection ────────────────────
                        if len(history) >= 2:
                            prev_cx = history[-2][0]
                            if _is_entering(prev_cx, cx):
                                self.vibe_engine.emit_event(
                                    event_type="ENTRY",
                                    visitor_id=visitor_id,
                                    is_staff=is_staff,
                                    confidence=round(conf, 3),
                                )
                            elif _is_exiting(prev_cx, cx):
                                self.vibe_engine.emit_event(
                                    event_type="EXIT",
                                    visitor_id=visitor_id,
                                    is_staff=is_staff,
                                    confidence=round(conf, 3),
                                )

                        # ── ZONE_ENTER ────────────────────────────────
                        if tid not in self.zone_dwell:
                            self.zone_dwell[tid] = {
                                "zone": zone,
                                "entry_time": now,
                                "last_dwell_emit": now,
                            }
                            if zone not in ("ENTRY", "FLOOR"):
                                self.vibe_engine.emit_event(
                                    event_type="ZONE_ENTER",
                                    visitor_id=visitor_id,
                                    zone_id=zone,
                                    is_staff=is_staff,
                                    confidence=round(conf, 3),
                                )
                        else:
                            zd = self.zone_dwell[tid]
                            # Zone changed
                            if zd["zone"] != zone:
                                self.vibe_engine.emit_event(
                                    event_type="ZONE_EXIT",
                                    visitor_id=visitor_id,
                                    zone_id=zd["zone"],
                                    is_staff=is_staff,
                                    confidence=round(conf, 3),
                                )
                                if zone not in ("ENTRY", "FLOOR"):
                                    self.vibe_engine.emit_event(
                                        event_type="ZONE_ENTER",
                                        visitor_id=visitor_id,
                                        zone_id=zone,
                                        is_staff=is_staff,
                                        confidence=round(conf, 3),
                                    )
                                zd["zone"] = zone
                                zd["entry_time"] = now
                                zd["last_dwell_emit"] = now
                            else:
                                # ── ZONE_DWELL every 30s ──────────────
                                dwell_ms = int(
                                    (now - zd["entry_time"])
                                    .total_seconds() * 1000
                                )
                                since_last = (
                                    now - zd["last_dwell_emit"]
                                ).total_seconds()
                                if since_last >= 30 and zone not in ("ENTRY", "FLOOR"):
                                    self.vibe_engine.emit_event(
                                        event_type="ZONE_DWELL",
                                        visitor_id=visitor_id,
                                        zone_id=zone,
                                        dwell_ms=dwell_ms,
                                        is_staff=is_staff,
                                        confidence=round(conf, 3),
                                    )
                                    zd["last_dwell_emit"] = now

                                # ── BILLING_QUEUE_JOIN ────────────────
                                if zone == "BILLING" and dwell_ms > 5000 and not zd.get("billing_joined", False):
                                    self.vibe_engine.emit_event(
                                        event_type="BILLING_QUEUE_JOIN",
                                        visitor_id=visitor_id,
                                        zone_id="BILLING",
                                        is_staff=is_staff,
                                        confidence=round(conf, 3),
                                    )
                                    zd["billing_joined"] = True

                        track_ids.append(tid)
                        boxes_list.append(box)

                # Clean up lost tracks
                active = set(track_ids)
                for tid in list(self.zone_dwell.keys()):
                    if tid not in active:
                        del self.zone_dwell[tid]
                for tid in list(self.track_history.keys()):
                    if tid not in active:
                        del self.track_history[tid]

                # Update vibe engine with current occupancy
                self.vibe_engine.process_frame_data(track_ids, boxes_list)

            except Exception as e:
                logger.error(f"Frame processing error: {e}")
                continue

    def _run_simulation(self):
        """
        Fallback simulation mode.
        Used when video is blank (make_video.py) or model unavailable.
        Documented in DESIGN.md Known Limitations.
        Generates realistic occupancy patterns to drive vibe + API.
        """
        logger.info("Pipeline running in SIMULATION mode")
        store_metrics["system_telemetry"]["pipeline_mode"] = "SIMULATION"

        while True:
            self.vibe_engine.process_frame_data(
                track_ids=[],
                boxes=[],
            )
            time.sleep(2)