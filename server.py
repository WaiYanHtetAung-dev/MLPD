from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import re
import shutil
import json
import time
from html import escape
from pathlib import Path
from urllib.parse import quote

# The LPR engine is exposed to the web app through a small service adapter.
import lpr_service as backend

app = FastAPI(title="MLPD LPR")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(backend.BASE_DIR)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/plate_captures", StaticFiles(directory=BASE_DIR / backend.SAVE_FOLDER), name="plate_captures")


@app.get("/", response_class=HTMLResponse)
def index():
    index_path = BASE_DIR / "dashboard.html"
    headers = {"Cache-Control": "no-store, max-age=0"}
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding='utf-8'), headers=headers)
    return HTMLResponse("<h1>LPR FastAPI</h1>", headers=headers)


@app.get("/video_feed")
def video_feed():
    try:
        return StreamingResponse(backend.generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
    except Exception as e:
        return PlainTextResponse(f"Video feed error: {e}", status_code=500)


@app.get("/health")
def health():
    camera_ready = False
    try:
        camera_ready = backend.camera_is_ready()
    except Exception:
        camera_ready = False
    tracking = backend.get_tracking_stats()
    return JSONResponse({
        "status": "ok",
        "engine": "MLPD",
        "camera_ready": camera_ready,
        "camera_source": backend.camera_source_label,
        "ocr_engine": backend.OCR_ENGINE,
        "model_ready": backend.engine.model is not None,
        "color_model_ready": backend.engine.color_model is not None,
        "detection_status": backend.last_detection_status,
        "active_tracks": tracking["active"],
        "recognized_tracks": tracking["recognized"],
        "queued_tracks": tracking["queued"],
    })


@app.get("/data")
def data():
    with backend.lock:
        payload = backend.latest_data.copy()
    return JSONResponse(payload)


@app.get("/events")
def events(limit: int = 50):
    return JSONResponse({"events": backend.get_recent_events(limit), "stats": backend.get_event_stats()})


@app.get("/event_stats")
def event_stats():
    return JSONResponse(backend.get_event_stats())


class CameraRequest(BaseModel):
    source: str | int = 0
    label: str = "Live Camera"
    rotation: str = "none"
    mirror: bool = False


@app.post("/camera/start")
def start_camera(request: CameraRequest):
    source = request.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    ok = backend.start_camera(source, request.label, request.rotation, request.mirror)
    return JSONResponse(
        {"success": ok, "message": "Camera connected." if ok else "Unable to connect camera."},
        status_code=200 if ok else 400,
    )


@app.post("/camera/stop")
def stop_camera():
    backend.stop_camera()
    return JSONResponse({"success": True, "message": "Camera stopped."})


@app.post("/camera/settings")
def camera_settings(request: CameraRequest):
    backend.set_camera_settings(request.rotation, request.mirror)
    return JSONResponse({"success": True, "message": "Rotation settings applied."})


@app.get("/log_file", response_class=PlainTextResponse)
def log_file():
    log_path = BASE_DIR / backend.LOG_FILE
    if log_path.exists():
        return PlainTextResponse(log_path.read_text(encoding='utf-8'))
    return PlainTextResponse("", status_code=404)


def parse_detection_log_entries(limit=100):
    log_path = BASE_DIR / backend.LOG_FILE
    if not log_path.exists():
        return []
    raw = log_path.read_text(encoding="utf-8", errors="replace")
    blocks = [block.strip() for block in raw.split("=" * 60) if block.strip()]
    entries = []
    for block in blocks:
        entry = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            entry[normalized] = value.strip()
        if entry:
            file_path = entry.get("file", "")
            file_name = os.path.basename(file_path.replace("\\", "/"))
            entry["capture_url"] = f"/plate_captures/{quote(file_name)}" if file_name else None
            entry["number"] = entry.get("main_number") or entry.get("display") or "-"
            entry["model"] = entry.get("car_model_matched") or "-"
            entry["township_name"] = backend.engine.get_township_name(entry.get("region"), entry.get("township"))
            entry["region_display"] = backend.engine.format_region_display(entry.get("region"), entry.get("township"))
            entry["type"] = entry.get("vehicle_type") or "-"
            entry["status"] = entry.get("status") or ("Fail" if entry.get("missing_fields", "-") != "-" else "Success")
            entries.append(entry)
    return list(reversed(entries))[:max(1, min(int(limit), 500))]


@app.get("/log_entries")
def log_entries(limit: int = 100):
    entries = backend.get_log_entries(limit)
    stats = backend.get_event_stats()
    if not entries:
        entries = parse_detection_log_entries(limit)
        stats = {"total": len(entries), "success": sum(1 for entry in entries if entry.get("status") == "Success")}
        stats["fail"] = stats["total"] - stats["success"]
        stats["latest"] = entries[0] if entries else None
    return JSONResponse({"logs": entries, "count": stats["total"], "stats": stats})


def get_capture_items():
    db_items = backend.get_capture_items()
    if db_items:
        return db_items
    captures_dir = BASE_DIR / backend.SAVE_FOLDER
    files = []
    if captures_dir.exists():
        files = sorted(
            (
                file for file in captures_dir.iterdir()
                if file.is_file() and file.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ),
            key=lambda file: file.stat().st_mtime,
            reverse=True,
        )
    items = []
    for file in files:
        stat = file.stat()
        items.append({
            "name": file.name,
            "url": f"/plate_captures/{quote(file.name)}",
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "size_kb": max(1, round(stat.st_size / 1024)),
        })
    return items


@app.get("/captures_data")
def captures_data():
    items = get_capture_items()
    return JSONResponse({"captures": items, "count": len(items)})


@app.get("/captures", response_class=HTMLResponse)
def captures():
    items = get_capture_items()

    cards = []
    for item in items:
        name = escape(item["name"])
        image_url = item["url"]
        cards.append(f"""
            <article class="capture-card">
                <a class="capture-image" href="{image_url}" target="_blank">
                    <img src="{image_url}" alt="{name}" loading="lazy">
                    <span>Open full image</span>
                </a>
                <div class="capture-meta">
                    <strong>{name}</strong>
                    <div><span>{item["captured_at"]}</span><span>{item["size_kb"]} KB</span></div>
                </div>
            </article>
        """)
    gallery = "".join(cards) if cards else """
        <div class="capture-empty">
            <strong>No plate captures yet</strong>
            <span>Detected plate crops will appear here automatically.</span>
        </div>
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Plate Captures - Sentinel LPR</title>
        <link rel="icon" type="image/jpeg" href="/static/icon.jpg?v=1">
        <link rel="stylesheet" href="/static/style.css?v=126-15">
    </head>
    <body class="captures-page">
        <header class="captures-topbar">
            <a class="captures-brand" href="/">
                <img src="/static/Logo.svg" alt="Sentinel LPR">
            </a>
            <a class="btn ghost" href="/">Back to dashboard</a>
        </header>
        <main class="captures-main">
            <div class="captures-heading">
                <div><div class="eyebrow">Monitoring / Captures</div><h1>Plate Captures</h1></div>
                <strong>{len(items)} images</strong>
            </div>
            <section class="capture-gallery">{gallery}</section>
        </main>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.api_route("/clear_logs", methods=["GET", "POST"])
def clear_logs():
    ok = backend.clear_logs()
    return JSONResponse({"success": ok, "message": "Logs cleared." if ok else "Unable to clear logs."})


@app.post("/upload_image")
async def upload_image(
    image: UploadFile = File(...),
    rotation: str = Form("none"),
    mirror: str = Form("false")
):
    try:
        content = await image.read()
        mirror_bool = str(mirror).lower() in ["true", "1", "yes", "on"]
        result = backend.process_uploaded_image(content, rotation=rotation, mirror=mirror_bool)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


@app.post("/upload_video")
async def upload_video(
    video: UploadFile = File(...),
    rotation: str = Form("none"),
    mirror: str = Form("false")
):
    try:
        mirror_bool = str(mirror).lower() in ["true", "1", "yes", "on"]
        tmp_dir = BASE_DIR / backend.SAVE_FOLDER
        tmp_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(video.filename or "").suffix.lower()
        if suffix not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
            suffix = ".mp4"
        tmp_path = tmp_dir / f"uploaded_video_{int(time.time() * 1000)}{suffix}"
        with tmp_path.open('wb') as f:
            shutil.copyfileobj(video.file, f)
        result = backend.process_uploaded_video(str(tmp_path), rotation=rotation, mirror=mirror_bool)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


if __name__ == "__main__":
    # Run with: python server.py OR: uvicorn server:app --host 0.0.0.0 --port 8000
    port = int(os.environ.get("PORT", "8000"))
    ssl_certfile = os.environ.get("SSL_CERTFILE")
    ssl_keyfile = os.environ.get("SSL_KEYFILE")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        ssl_certfile=ssl_certfile if ssl_certfile and ssl_keyfile else None,
        ssl_keyfile=ssl_keyfile if ssl_certfile and ssl_keyfile else None,
    )
