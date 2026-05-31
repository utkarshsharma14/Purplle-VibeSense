from datetime import datetime
import random

from event_store import add_event

store_metrics = {
    "current_count": 0,
    "vibe": "Cozy & Premium",
    "ambient_music": "Soft acoustic melodies playing.",
    "realtime_alerts": [],
    "system_telemetry": {
        "status": "HEALTHY",
        "last_inference_timestamp": "",
        "anomaly_flag": False
    }
}


class VibeEngine:

    def __init__(self):
        self.previous_count = 0

    def process_frame_data(self, track_ids, boxes):

        simulated_people_count = random.randint(2, 14)

        store_metrics["current_count"] = simulated_people_count

        store_metrics["system_telemetry"][
            "last_inference_timestamp"
        ] = datetime.now().isoformat()

        # AUTO EVENT GENERATION

        if simulated_people_count > self.previous_count:

            for i in range(
                simulated_people_count -
                self.previous_count
            ):

                add_event(
                    store_id="STORE001",
                    visitor_id=f"VISITOR_{random.randint(1000,9999)}",
                    event_type="ENTRY"
                )

        elif simulated_people_count < self.previous_count:

            for i in range(
                self.previous_count -
                simulated_people_count
            ):

                add_event(
                    store_id="STORE001",
                    visitor_id=f"VISITOR_{random.randint(1000,9999)}",
                    event_type="EXIT"
                )

        self.previous_count = simulated_people_count

        # VIBE LOGIC

        if simulated_people_count > 10:

            store_metrics["vibe"] = \
                "Energetic & Crowded"

            store_metrics["ambient_music"] = \
                "Upbeat synth-pop tunes tracking."

            store_metrics["system_telemetry"][
                "anomaly_flag"
            ] = True

            alert = (
                "CRITICAL ANOMALY: "
                "Store capacity threshold exceeded."
            )

            if alert not in store_metrics[
                "realtime_alerts"
            ]:
                store_metrics[
                    "realtime_alerts"
                ].append(alert)

        elif simulated_people_count > 5:

            store_metrics["vibe"] = \
                "Moderate & Buzzing"

            store_metrics["ambient_music"] = \
                "Lo-Fi indie grooves streaming."

            store_metrics["system_telemetry"][
                "anomaly_flag"
            ] = False

        else:

            store_metrics["vibe"] = \
                "Cozy & Premium"

            store_metrics["ambient_music"] = \
                "Soft acoustic melodies playing."

            store_metrics["system_telemetry"][
                "anomaly_flag"
            ] = False

        if len(
            store_metrics["realtime_alerts"]
        ) > 5:

            store_metrics[
                "realtime_alerts"
            ].pop(0)