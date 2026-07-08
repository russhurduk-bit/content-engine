#!/usr/bin/env python3
"""
Content Engine API — HTTP сервер для экспорта, анализа и генерации контента.
Порт: 8608
"""

import os
import sys
import json
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager

from tg_export import export_channel
from style_analyzer import analyze
from content_generator import generate, load_style

PORT = int(os.environ.get("CONTENT_ENGINE_PORT", "8608"))
EXPORTS_DIR = "/root/content-engine/exports"
STYLES_DIR = "/root/content-engine/styles"
VAULT_DIR = "/root/content-engine/vault"


# --- Models ---
class ExportRequest(BaseModel):
    channel: str  # username, link, or ID
    limit: int = 500
    account: int = 1
    since_days: Optional[int] = None


class AnalyzeRequest(BaseModel):
    channel_name: str  # name of exported channel (matches filename)
    json_path: Optional[str] = None  # or explicit path


class GenerateRequest(BaseModel):
    channel_name: str
    topic: str
    post_type: str = "informational"
    count: int = 1
    tone: Optional[str] = None
    extra_instructions: Optional[str] = None


class FullPipelineRequest(BaseModel):
    channel: str
    topic: str
    limit: int = 300
    account: int = 1
    since_days: Optional[int] = 90
    post_type: str = "informational"
    count: int = 3


# --- Background task tracking ---
tasks_status = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[content-engine] Started on port {PORT}")
    yield

app = FastAPI(title="Content Engine", version="1.0", lifespan=lifespan)


@app.get("/health")
def health():
    exports = glob.glob(os.path.join(EXPORTS_DIR, "*.json"))
    styles = glob.glob(os.path.join(STYLES_DIR, "*_style.md"))
    return {
        "status": "ok",
        "exports": len(exports),
        "styles": len(styles),
        "channels": [os.path.basename(f).replace(".json", "") for f in exports],
    }


@app.post("/export")
async def api_export(req: ExportRequest, bg: BackgroundTasks):
    """Export TG channel posts to JSON + Markdown vault."""
    task_id = f"export_{req.channel}"
    tasks_status[task_id] = {"status": "running", "channel": req.channel}

    async def run():
        try:
            result = await export_channel(req.channel, req.limit, req.account, req.since_days)
            tasks_status[task_id] = {"status": "done", "result": result}
        except Exception as e:
            tasks_status[task_id] = {"status": "error", "error": str(e)}

    bg.add_task(run)
    return {"task_id": task_id, "status": "started", "message": f"Exporting {req.channel}..."}


@app.post("/analyze")
async def api_analyze(req: AnalyzeRequest):
    """Analyze exported channel style."""
    json_path = req.json_path
    if not json_path:
        # Find by channel name
        safe = req.channel_name.replace(' ', '_').replace('@', '')
        candidates = glob.glob(os.path.join(EXPORTS_DIR, f"*{safe}*.json"))
        if not candidates:
            raise HTTPException(404, f"No export found for '{req.channel_name}'. Export first via /export")
        json_path = candidates[0]

    if not os.path.exists(json_path):
        raise HTTPException(404, f"File not found: {json_path}")

    result = await analyze(json_path, req.channel_name)
    return {"status": "done", **result}


@app.post("/generate")
async def api_generate(req: GenerateRequest):
    """Generate content in channel's style."""
    profile, guide = load_style(req.channel_name)
    if not guide:
        raise HTTPException(404, f"No style guide for '{req.channel_name}'. Run /analyze first.")

    result = await generate(
        req.channel_name, req.topic, req.post_type,
        req.count, req.tone, req.extra_instructions,
    )

    if result.get("error"):
        raise HTTPException(500, result["error"])

    return result


@app.post("/pipeline")
async def full_pipeline(req: FullPipelineRequest, bg: BackgroundTasks):
    """Full pipeline: export → analyze → generate."""
    task_id = f"pipeline_{req.channel}"
    tasks_status[task_id] = {"status": "running", "step": "export"}

    async def run():
        try:
            # Step 1: Export
            tasks_status[task_id]["step"] = "export"
            export_result = await export_channel(req.channel, req.limit, req.account, req.since_days)
            if not export_result:
                tasks_status[task_id] = {"status": "error", "error": "Export failed"}
                return

            # Step 2: Analyze
            tasks_status[task_id]["step"] = "analyze"
            analyze_result = await analyze(export_result["json"])

            # Step 3: Generate
            tasks_status[task_id]["step"] = "generate"

            # Get channel name from export
            with open(export_result["json"]) as f:
                data = json.load(f)
            channel_name = data.get("channel", {}).get("title", req.channel)

            gen_result = await generate(
                channel_name, req.topic, req.post_type, req.count,
            )

            tasks_status[task_id] = {
                "status": "done",
                "export": export_result,
                "style_guide": analyze_result.get("guide"),
                "content": gen_result,
            }
        except Exception as e:
            tasks_status[task_id] = {"status": "error", "error": str(e), "step": tasks_status[task_id].get("step")}

    bg.add_task(run)
    return {"task_id": task_id, "status": "started"}


@app.get("/task/{task_id}")
def get_task(task_id: str):
    if task_id not in tasks_status:
        raise HTTPException(404, "Task not found")
    return tasks_status[task_id]


@app.get("/styles")
def list_styles():
    """List all analyzed channel styles."""
    guides = glob.glob(os.path.join(STYLES_DIR, "*_style.md"))
    result = []
    for g in guides:
        name = os.path.basename(g).replace("_style.md", "").replace("_", " ")
        profile_path = g.replace("_style.md", "_profile.json")
        stats = {}
        if os.path.exists(profile_path):
            with open(profile_path) as f:
                data = json.load(f)
                stats = data.get("basic_stats", {})
        result.append({
            "name": name,
            "guide": g,
            "posts_analyzed": stats.get("total_posts", 0),
            "avg_words": stats.get("avg_words", 0),
        })
    return {"styles": result, "count": len(result)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
