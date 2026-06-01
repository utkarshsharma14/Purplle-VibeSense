import time
import random
import logging

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from vibe_engine import VibeEngine, store_metrics

logger = logging.getLogger("vibesense")

ZONES = {
    "ENTRY":    (0,   0,   160, 480),
    "AISLE":    (160, 0,   400, 320),
    "COSMETICS":(400, 0,   640, 320),
    "BILLING":  (160, 320, 640, 480),
}

def _is_staff(frame, box) -> bool:
    if not CV2_AVAILABLE:
        return False
    try:
        import numpy as np
        STAFF_HSV_LOWER = np.array([100, 50, 50])
        STAFF_HSV_UPPER = np.array([130, 255, 255])
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

def _get_zone(cx, cy) -> str:
    for zone_name, (x1, y1, x2, y2) in ZONES.items():
        if x1 <= cx < x2 and y1 <= cy < y2:
            return zone_name
    return "FLOOR"

def _is_entering(prev_cx, curr_cx) -> bool:
    return prev_cx > 160 and curr_cx <= 160

def _is_exiting(prev_cx, curr_cx) -> bool:
    return prev_cx <= 160 and curr_cx > 160


class StoreMonitor:
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.vibe_engine = VibeEngine()
        self.model = None
        self.track_history: dict = {}
        self.zone_dwell: dict = {}

    def _load_model(self) -> bool:
        try:
            from ultralytics import YOLO
            self.model = YOLO("yolov8n.pt")
            logger.info("YOLOv8n loaded successfully")
            return True
        except Exception as e:
            logger.warning(f"YOLOv8n load failed: {e} — simulation mode")
            return False

    def _check_video_blank(self, cap) -> bool:
        ret, frame = cap.read()
        if not ret:
            return True
        blank = frame.mean() < 5
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return blank

    def start_monitoring(self):
        logger.info("VibeSense AI pipeline starting...")

        if not CV2_AVAILABLE:
            logger.warning("cv2 not available — simulation mode")
            self._run_simulation()
            return

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.warning("Cannot open video — simulation mode")
            self._run_simulation()
            return

        if self._check_video_blank(cap):
            logger.warning("Video is blank — simulation mode")
            cap.release()
            self._run_simulation()
            return

        if not self._load_model():
            cap.release()
            self._run_simulation()
            return

        logger.info("Real YOLOv8n pipeline active")
        store_metrics["system_telemetry"]["pipeline_mode"] = "YOLO_BYTETRACK"

        try:
            self._run_real_pipeline(cap)
        except Exception as e:
            logger.error(f"Pipeline error: {e} — simulation mode")
            cap.release()
            self._run_simulation()

    def _run_real_pipeline(self, cap):
        from datetime import datetime, timezone
        while True:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            try:
                results = self.model.track(
                    frame, persist=True, classes=[0], conf=0.35, verbose=False)
                track_ids = []
                boxes_list = []
                now = datetime.now(timezone.utc)
                if results[0].boxes is not None and results[0].boxes.id is not None:
                    ids = results[0].boxes.id.tolist()
                    boxes = results[0].boxes.xyxy.tolist()
                    confs = results[0].boxes.conf.tolist()
                    for tid, box, conf in zip(ids, boxes, confs):
                        tid = int(tid)
                        x1, y1, x2, y2 = box
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2
                        is_staff = _is_staff(frame, box)
                        zone = _get_zone(cx, cy)
                        visitor_id = f"VIS_{tid:04d}"
                        if tid not in self.track_history:
                            self.track_history[tid] = []
                        self.track_history[tid].append((cx, cy))
                        history = self.track_history[tid]
                        if len(history) >= 2:
                            prev_cx = history[-2][0]
                            if _is_entering(prev_cx, cx):
                                self.vibe_engine.emit_event("ENTRY", visitor_id, is_staff=is_staff, confidence=round(conf, 3))
                            elif _is_exiting(prev_cx, cx):
                                self.vibe_engine.emit_event("EXIT", visitor_id, is_staff=is_staff, confidence=round(conf, 3))
                        if tid not in self.zone_dwell:
                            self.zone_dwell[tid] = {"zone": zone, "entry_time": now, "last_dwell_emit": now}
                            if zone not in ("ENTRY", "FLOOR"):
                                self.vibe_engine.emit_event("ZONE_ENTER", visitor_id, zone_id=zone, is_staff=is_staff, confidence=round(conf, 3))
                        else:
                            zd = self.zone_dwell[tid]
                            if zd["zone"] != zone:
                                self.vibe_engine.emit_event("ZONE_EXIT", visitor_id, zone_id=zd["zone"], is_staff=is_staff, confidence=round(conf, 3))
                                if zone not in ("ENTRY", "FLOOR"):
                                    self.vibe_engine.emit_event("ZONE_ENTER", visitor_id, zone_id=zone, is_staff=is_staff, confidence=round(conf, 3))
                                zd["zone"] = zone
                                zd["entry_time"] = now
                                zd["last_dwell_emit"] = now
                            else:
                                dwell_ms = int((now - zd["entry_time"]).total_seconds() * 1000)
                                since_last = (now - zd["last_dwell_emit"]).total_seconds()
                                if since_last >= 30 and zone not in ("ENTRY", "FLOOR"):
                                    self.vibe_engine.emit_event("ZONE_DWELL", visitor_id, zone_id=zone, dwell_ms=dwell_ms, is_staff=is_staff, confidence=round(conf, 3))
                                    zd["last_dwell_emit"] = now
                                if zone == "BILLING" and dwell_ms > 5000 and not zd.get("billing_joined", False):
                                    self.vibe_engine.emit_event("BILLING_QUEUE_JOIN", visitor_id, zone_id="BILLING", is_staff=is_staff, confidence=round(conf, 3))
                                    zd["billing_joined"] = True
                        track_ids.append(tid)
                        boxes_list.append(box)
                active = set(track_ids)
                for tid in list(self.zone_dwell.keys()):
                    if tid not in active:
                        del self.zone_dwell[tid]
                for tid in list(self.track_history.keys()):
                    if tid not in active:
                        del self.track_history[tid]
                self.vibe_engine.process_frame_data(track_ids, boxes_list)
            except Exception as e:
                logger.error(f"Frame error: {e}")
                continue

    def _run_simulation(self):
        logger.info("Pipeline running in SIMULATION mode")
        store_metrics["system_telemetry"]["pipeline_mode"] = "SIMULATION"
        while True:
            self.vibe_engine.process_frame_data(track_ids=[], boxes=[])
            time.sleep(2)
