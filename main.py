import threading
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from core_ai import StoreMonitor
from vibe_engine import store_metrics
import uvicorn

app = FastAPI(title="VibeSense AI - Analytics API Portal")

# Middleware to allow frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Background AI Pipeline
def run_ai_pipeline():
    monitor = StoreMonitor("store.mp4")
    monitor.start_monitoring()

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_ai_pipeline, daemon=True).start()

# Homepage route to serve index.html with path-finding logic
@app.get("/", response_class=HTMLResponse)
def read_root():
    # Construct the absolute path to the templates folder
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "templates", "index.html")
    
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        # If it fails, this will show the path it tried to access
        return f"<h1>Error: templates/index.html not found.</h1><p>Tried path: {file_path}</p>"

# API route for metrics
@app.get("/api/v1/store/vibe")
def get_store_vibe():
    return {
        "current_occupancy": store_metrics["current_count"],
        "store_vibe": store_metrics["vibe"],
        "ambient_music": store_metrics["ambient_music"],
        "realtime_alerts": store_metrics["realtime_alerts"][-5:]
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)