from core_ai import StoreMonitor

if __name__ == "__main__":
   
    sample_video_url = "https://assets.mixkit.co/videos/preview/mixkit-people-shopping-in-a-boutique-store-41614-large.mp4"
    
    monitor = StoreMonitor(sample_video_url)
    monitor.start_monitoring()