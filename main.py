import threading
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import anthropic
import uvicorn

# Local modules
from core_ai import StoreMonitor
from vibe_engine import store_metrics

# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="VibeSense AI — Retail Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (store.mp4, images, etc.)
app.mount("/static", StaticFiles(directory="."), name="static")

# Anthropic client — reads ANTHROPIC_API_KEY from environment
ai_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── AI Pipeline ───────────────────────────────────────────────────────
def run_ai_pipeline():
    monitor = StoreMonitor("store.mp4")
    monitor.start_monitoring()

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_ai_pipeline, daemon=True).start()


# ── Routes ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def read_root():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(file_path, "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/v1/store/vibe")
def get_store_vibe():
    return {
        "current_occupancy": store_metrics["current_count"],
        "store_vibe":        store_metrics["vibe"],
        "ambient_music":     store_metrics["ambient_music"],
        "realtime_alerts":   store_metrics["realtime_alerts"][-5:],
    }


# ── AI Insights ───────────────────────────────────────────────────────
class InsightRequest(BaseModel):
    count:         int
    vibe:          str
    music:         str
    alerts:        List[str] = []
    avg_occupancy: int       = 0
    dominant_vibe: str       = ""
    timestamp:     str       = ""


@app.post("/api/v1/ai/insights")
def get_ai_insights(req: InsightRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY not set. Add it in Render → Environment Variables."
        )

    prompt = f"""You are VibeSense AI, an intelligent retail analytics assistant for a Purplle beauty store. Analyze this real-time store data and provide actionable insights.

CURRENT STORE DATA:
- Live Occupancy: {req.count} people
- Store Vibe: {req.vibe}
- Ambient Music: {req.music}
- Active Alerts: {', '.join(req.alerts) if req.alerts else 'None'}
- Session Avg Occupancy: {req.avg_occupancy} people
- Dominant Vibe (recent): {req.dominant_vibe or req.vibe}
- Time: {req.timestamp}

Provide a concise analysis in EXACTLY this format (use ** for bold):
1. **Situation Summary** — (2 sentences describing current store state and atmosphere)
2. **Staff Recommendation** — (1 specific, actionable staffing suggestion)
3. **Revenue Opportunity** — (1 concrete tip to increase sales right now)
4. **Music & Ambiance** — (1 specific music/atmosphere recommendation)
5. **30-Min Forecast** — (brief prediction of what will happen next)

Rules:
- Reference actual numbers from the data
- Be specific and direct, not generic
- Each point must be 1-2 sentences maximum
- Focus on what a store manager should DO right now"""

    try:
        message = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap for real-time insights
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        insight_text = message.content[0].text
        return {"insight": insight_text}

    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="Invalid ANTHROPIC_API_KEY. Check your Render environment variables."
        )
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Anthropic rate limit hit. Please wait a moment and try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI service error: {str(e)}"
        )


# ── Entry Point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)