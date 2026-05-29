import random
from datetime import datetime

# Clean Event Schema Architecture for Store Intelligence Data Tracking
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
    def process_frame_data(self, track_ids, boxes):
        # 1. Simulate dynamic customer count variance
        simulated_people_count = random.randint(2, 14) 
        store_metrics["current_count"] = simulated_people_count
        store_metrics["system_telemetry"]["last_inference_timestamp"] = datetime.now().isoformat()
        
        # 2. Dynamic Threshold Mapping & Atmosphere Management
        if simulated_people_count > 10:
            store_metrics["vibe"] = "Energetic & Crowded"
            store_metrics["ambient_music"] = "Upbeat synth-pop tunes tracking."
            
            # ANOMALY DETECTION ENGINE TRIPPED (High Congestion Trigger)
            store_metrics["system_telemetry"]["anomaly_flag"] = True
            
            critical_alert = "CRITICAL ANOMALY: Store capacity threshold exceeded at checkout zone."
            if critical_alert not in store_metrics["realtime_alerts"]:
                store_metrics["realtime_alerts"].append(critical_alert)
                
        elif simulated_people_count > 5:
            store_metrics["vibe"] = "Moderate & Buzzing"
            store_metrics["ambient_music"] = "Lo-Fi indie grooves streaming."
            store_metrics["system_telemetry"]["anomaly_flag"] = False
            
            standard_alert = "Floor Alert: High linger-duration observed near aisle 3."
            if standard_alert not in store_metrics["realtime_alerts"]:
                store_metrics["realtime_alerts"].append(standard_alert)
        else:
            store_metrics["vibe"] = "Cozy & Premium"
            store_metrics["ambient_music"] = "Soft acoustic melodies playing."
            store_metrics["system_telemetry"]["anomaly_flag"] = False
            
            # Keep log window light by managing list length
            if len(store_metrics["realtime_alerts"]) > 5:
                store_metrics["realtime_alerts"].pop(0)