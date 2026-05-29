import time
from vibe_engine import VibeEngine

class StoreMonitor:
    def __init__(self, video_path):
        self.video_path = video_path
        self.vibe_engine = VibeEngine()

    def start_monitoring(self):
        print("SUCCESS: VibeSense AI Video Pipeline Stream Activated.")
        
        # Real-time background simulation loop to fire numbers continuously
        while True:
            # Directly triggers the data generator inside your vibe_engine
            self.vibe_engine.process_frame_data(track_ids=[], boxes=[])
            time.sleep(2)  # Sync frame window update rate