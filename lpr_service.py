import os
import json
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np

import lpr_engine as engine

BASE_DIR = engine.BASE_DIR
SAVE_FOLDER = "captures"
LOG_FILE = "detection_log.txt"
DB_FILE = "mlpd_events.sqlite"
DB_FOLDER = "data"
DB_PATH = os.path.join(BASE_DIR, DB_FOLDER, DB_FILE)
OCR_ENGINE = "easyocr" if engine.OCR_AVAILABLE == "easyocr" else ("paddle" if engine.OCR_AVAILABLE else None)

lock = threading.RLock()
db_lock = threading.RLock()
camera_lock = threading.RLock()
ocr_lock = threading.Lock()
tracking_lock = threading.RLock()
tracking_queue_lock = threading.Lock()
tracking_queue_event = threading.Event()
camera = None
camera_source_label = "Live Camera"
camera_rotation = "none"
camera_mirror = False
latest_frame = None
last_detect = 0.0
last_detection_status = "Waiting for plate detection"
recent_events = deque(maxlen=100)
tracking_queue = deque(maxlen=24)
live_tracks = {}
live_known_numbers = set()
next_track_id = 1
tracking_worker_started = False
latest_data = {
    "region": "-", "township": "-", "number": "-", "color": "-",
    "type": "-", "model": "-", "confidence": 0, "capture_url": None,
    "timestamp": None, "source": "-", "status": "-", "complete": False, "missing_fields": []
}

REQUIRED_RESULT_FIELDS = ("number", "region", "township", "color", "type", "model")


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.join(BASE_DIR, SAVE_FOLDER), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, DB_FOLDER), exist_ok=True)
    with db_lock:
        with db_connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    status TEXT,
                    complete INTEGER DEFAULT 0,
                    number TEXT,
                    region TEXT,
                    township TEXT,
                    color TEXT,
                    vehicle_type TEXT,
                    model TEXT,
                    bottom_text_raw TEXT,
                    main_number TEXT,
                    display TEXT,
                    confidence REAL DEFAULT 0,
                    detection_confidence REAL DEFAULT 0,
                    processing_ms INTEGER DEFAULT 0,
                    missing_fields_json TEXT,
                    capture_file TEXT,
                    capture_path TEXT,
                    capture_url TEXT,
                    raw_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(timestamp, capture_file, number)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_detections_status ON detections(status)")
            conn.commit()


def _safe_json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def save_detection_event(event):
    init_db()
    missing_fields = event.get("missing_fields") or []
    capture_path = event.get("capture_path") or ""
    capture_file = event.get("capture_file") or os.path.basename(capture_path.replace("\\", "/"))
    capture_url = event.get("capture_url") or (f"/plate_captures/{capture_file}" if capture_file else None)
    vehicle_type = event.get("vehicle_type") or event.get("type") or "-"
    complete = 1 if event.get("complete") else 0
    payload = {
        **event,
        "capture_file": capture_file,
        "capture_path": capture_path,
        "capture_url": capture_url,
        "vehicle_type": vehicle_type,
        "type": vehicle_type,
    }
    with db_lock:
        with db_connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO detections (
                    timestamp, source, status, complete, number, region, township, color,
                    vehicle_type, model, bottom_text_raw, main_number, display, confidence,
                    detection_confidence, processing_ms, missing_fields_json, capture_file,
                    capture_path, capture_url, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
                    payload.get("source") or "-",
                    payload.get("status") or ("Success" if complete else "Fail"),
                    complete,
                    payload.get("number") or payload.get("main_number") or payload.get("display") or "-",
                    payload.get("region") or "-",
                    payload.get("township") or "-",
                    payload.get("color") or "-",
                    vehicle_type,
                    payload.get("model") or payload.get("car_model") or "-",
                    payload.get("bottom_text_raw") or payload.get("bottom_text_ocr") or "-",
                    payload.get("main_number") or payload.get("number") or "-",
                    payload.get("display") or payload.get("number") or "-",
                    float(payload.get("confidence") or 0),
                    float(payload.get("detection_confidence") or 0),
                    int(payload.get("processing_ms") or 0),
                    json.dumps(missing_fields, ensure_ascii=False),
                    capture_file,
                    capture_path,
                    capture_url,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()


def detection_row_to_event(row):
    missing_fields = _safe_json_loads(row["missing_fields_json"], [])
    raw = _safe_json_loads(row["raw_json"], {})
    vehicle_type = row["vehicle_type"] or raw.get("type") or "-"
    capture_url = row["capture_url"] or (f"/plate_captures/{row['capture_file']}" if row["capture_file"] else None)
    event = {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "time": row["timestamp"],
        "source": row["source"] or "-",
        "status": row["status"] or "Fail",
        "complete": bool(row["complete"]),
        "number": row["number"] or "-",
        "region": row["region"] or "-",
        "township": row["township"] or "-",
        "color": row["color"] or "-",
        "type": vehicle_type,
        "vehicle_type": vehicle_type,
        "model": row["model"] or "-",
        "car_model_matched": row["model"] or "-",
        "bottom_text_raw": row["bottom_text_raw"] or "-",
        "bottom_text_ocr": row["bottom_text_raw"] or "-",
        "main_number": row["main_number"] or row["number"] or "-",
        "display": row["display"] or row["number"] or "-",
        "confidence": float(row["confidence"] or 0),
        "detection_confidence": float(row["detection_confidence"] or 0),
        "processing_ms": int(row["processing_ms"] or 0),
        "missing_fields": missing_fields,
        "capture_file": row["capture_file"],
        "capture_path": row["capture_path"],
        "file": row["capture_path"] or "",
        "capture_url": capture_url,
        "recorded": True,
    }
    event["township_name"] = engine.get_township_name(event["region"], event["township"])
    event["region_display"] = engine.format_region_display(event["region"], event["township"])
    return {**raw, **event}


def get_log_entries(limit=100):
    init_db()
    limit = max(1, min(int(limit), 500))
    with db_lock:
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM detections ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [detection_row_to_event(row) for row in rows]


def get_capture_items(limit=500):
    init_db()
    limit = max(1, min(int(limit), 1000))
    with db_lock:
        with db_connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM detections
                WHERE capture_file IS NOT NULL AND capture_file != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    items = []
    for row in rows:
        event = detection_row_to_event(row)
        capture_path = event.get("capture_path") or ""
        size_kb = 0
        if capture_path and os.path.exists(capture_path):
            size_kb = max(1, round(os.path.getsize(capture_path) / 1024))
        items.append({
            "id": event["id"],
            "name": event.get("capture_file") or os.path.basename(capture_path.replace("\\", "/")),
            "url": event.get("capture_url"),
            "captured_at": str(event.get("timestamp") or "").replace("T", " "),
            "size_kb": size_kb,
            "status": event.get("status"),
            "number": event.get("number"),
            "region": event.get("region"),
            "township": event.get("township"),
            "color": event.get("color"),
            "model": event.get("model"),
        })
    return items


def get_event_stats():
    init_db()
    with db_lock:
        with db_connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM detections WHERE status = 'Success'").fetchone()[0]
            fail = total - success
            latest_row = conn.execute(
                "SELECT * FROM detections ORDER BY id DESC LIMIT 1"
            ).fetchone()
    latest = detection_row_to_event(latest_row) if latest_row else None
    return {
        "total": int(total or 0),
        "success": int(success or 0),
        "fail": int(fail or 0),
        "latest": latest,
    }


def import_existing_text_logs():
    log_path = os.path.join(BASE_DIR, LOG_FILE)
    if not os.path.exists(log_path):
        return 0
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as file:
            raw = file.read()
    except OSError:
        return 0
    imported = 0
    blocks = [block.strip() for block in raw.split("=" * 60) if block.strip()]
    for block in blocks:
        parsed = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            parsed[normalized] = value.strip()
        if not parsed:
            continue
        file_path = parsed.get("file", "")
        file_name = os.path.basename(file_path.replace("\\", "/"))
        missing_raw = parsed.get("missing_fields", "-")
        missing_fields = [] if missing_raw in {"", "-"} else [part.strip() for part in missing_raw.split(",") if part.strip()]
        status = parsed.get("status") or ("Fail" if missing_fields else "Success")
        event = {
            "timestamp": parsed.get("time") or datetime.now().isoformat(timespec="seconds"),
            "source": parsed.get("source") or "Text Log Import",
            "status": status,
            "complete": status == "Success",
            "number": parsed.get("main_number") or parsed.get("display") or "-",
            "region": parsed.get("region") or "-",
            "township": parsed.get("township") or "-",
            "color": parsed.get("color") or "-",
            "type": parsed.get("vehicle_type") or "-",
            "vehicle_type": parsed.get("vehicle_type") or "-",
            "model": parsed.get("car_model_matched") or "-",
            "bottom_text_raw": parsed.get("bottom_text_ocr") or "-",
            "main_number": parsed.get("main_number") or "-",
            "display": parsed.get("display") or parsed.get("main_number") or "-",
            "confidence": 0,
            "detection_confidence": 0,
            "processing_ms": 0,
            "missing_fields": missing_fields,
            "capture_file": file_name,
            "capture_path": file_path,
            "capture_url": f"/plate_captures/{file_name}" if file_name else None,
        }
        try:
            save_detection_event(event)
            imported += 1
        except Exception as exc:
            print(f"MLPD DB import error: {exc}")
    return imported


try:
    init_db()
    import_existing_text_logs()
except Exception as exc:
    print(f"MLPD DB init error: {exc}")


def get_missing_result_fields(data):
    missing = []
    for field in REQUIRED_RESULT_FIELDS:
        value = str(data.get(field, "")).strip()
        if not value or value in {"-", "Unknown", "unknown"}:
            missing.append(field)
    return missing


def camera_is_ready():
    with camera_lock:
        return camera is not None and camera.isOpened()


def start_camera(source=0, source_label="Live Camera", rotation="none", mirror=False):
    global camera, camera_source_label, camera_rotation, camera_mirror
    stop_camera()
    reset_live_tracking()
    ensure_tracking_worker()
    camera_source_label = source_label
    camera_rotation = rotation
    camera_mirror = mirror
    with camera_lock:
        camera = cv2.VideoCapture(source)
        if not camera.isOpened():
            camera.release()
            camera = None
            return False
    return True


def set_camera_settings(rotation="none", mirror=False):
    global camera_rotation, camera_mirror
    camera_rotation = rotation
    camera_mirror = mirror
    return True


def stop_camera():
    global camera
    with camera_lock:
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass
        camera = None
    reset_live_tracking()
    return True


def reset_live_tracking():
    global next_track_id
    with tracking_lock:
        live_tracks.clear()
        live_known_numbers.clear()
        next_track_id = 1
    with tracking_queue_lock:
        tracking_queue.clear()


def get_tracking_stats():
    with tracking_lock:
        active = len(live_tracks)
        recognized = sum(1 for track in live_tracks.values() if track.get("label"))
    with tracking_queue_lock:
        queued = len(tracking_queue)
    return {"active": active, "recognized": recognized, "queued": queued}


def apply_settings(image, rotation="none", mirror=False):
    if rotation == "90cw":
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == "90ccw":
        image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif rotation == "180":
        image = cv2.rotate(image, cv2.ROTATE_180)
    if mirror:
        image = cv2.flip(image, 1)
    return image


def detect_plate_crop(image, conf_threshold=0.03, padding_ratio=0.10):
    results = engine.model(image, conf=conf_threshold, iou=0.45, imgsz=960, verbose=False)
    best_crop, best_box, best_conf, best_score = None, None, 0.0, 0.0
    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            if int(box.cls[0]) != 1:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            width, height = max(0, x2 - x1), max(0, y2 - y1)
            area = width * height
            aspect_ratio = width / max(height, 1)
            area_ratio = area / max(image.shape[0] * image.shape[1], 1)
            confidence = float(box.conf[0])
            if area < 500 or area_ratio > 0.08 or not 1.0 <= aspect_ratio <= 8.0:
                continue
            score = confidence * (area ** 0.5)
            if score > best_score:
                pad_x = int((x2 - x1) * padding_ratio)
                pad_y = int((y2 - y1) * padding_ratio)
                crop_x1, crop_y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                crop_x2, crop_y2 = min(image.shape[1], x2 + pad_x), min(image.shape[0], y2 + pad_y)
                best_score = score
                best_box = (x1, y1, x2, y2)
                best_crop = image[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                best_conf = confidence
    return best_crop, best_box, best_conf


def detect_plate_candidates(image, conf_threshold=0.08, padding_ratio=0.08, imgsz=640, min_area=350):
    results = engine.model(image, conf=conf_threshold, iou=0.45, imgsz=imgsz, verbose=False)
    candidates = []
    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            if int(box.cls[0]) != 1:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            width, height = max(0, x2 - x1), max(0, y2 - y1)
            area = width * height
            aspect_ratio = width / max(height, 1)
            area_ratio = area / max(image.shape[0] * image.shape[1], 1)
            if area < min_area or area_ratio > 0.10 or not 1.0 <= aspect_ratio <= 8.0:
                continue
            pad_x, pad_y = int(width * padding_ratio), int(height * padding_ratio)
            crop = image[
                max(0, y1 - pad_y):min(image.shape[0], y2 + pad_y),
                max(0, x1 - pad_x):min(image.shape[1], x2 + pad_x),
            ].copy()
            confidence = float(box.conf[0])
            sharpness = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            candidates.append({
                "box": (x1, y1, x2, y2),
                "crop": crop,
                "confidence": confidence,
                "quality": confidence * max(sharpness, 1.0),
            })
    return candidates


def dedupe_plate_candidates(candidates, overlap_threshold=0.45, max_candidates=12):
    kept = []
    for candidate in sorted(candidates, key=lambda item: item["quality"], reverse=True):
        if any(box_iou(candidate["box"], existing["box"]) >= overlap_threshold for existing in kept):
            continue
        kept.append(candidate)
        if len(kept) >= max_candidates:
            break
    return sorted(kept, key=lambda item: (item["box"][1], item["box"][0]))


def box_iou(first, second):
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    return intersection / max(first_area + second_area - intersection, 1)


def update_live_tracks(candidates):
    global next_track_id
    matched_tracks = set()
    matched_candidates = set()
    with tracking_lock:
        matches = []
        for track_id, track in live_tracks.items():
            for index, candidate in enumerate(candidates):
                overlap = box_iou(track["box"], candidate["box"])
                track_x = (track["box"][0] + track["box"][2]) / 2
                track_y = (track["box"][1] + track["box"][3]) / 2
                candidate_x = (candidate["box"][0] + candidate["box"][2]) / 2
                candidate_y = (candidate["box"][1] + candidate["box"][3]) / 2
                distance = ((track_x - candidate_x) ** 2 + (track_y - candidate_y) ** 2) ** 0.5
                match_radius = max(
                    track["box"][2] - track["box"][0],
                    track["box"][3] - track["box"][1],
                    candidate["box"][2] - candidate["box"][0],
                    candidate["box"][3] - candidate["box"][1],
                ) * 1.5
                if overlap >= 0.15 or distance <= match_radius:
                    score = overlap + max(0.0, 1.0 - distance / max(match_radius, 1)) * 0.25
                    matches.append((score, track_id, index))
        for _, track_id, index in sorted(matches, reverse=True):
            if track_id in matched_tracks or index in matched_candidates:
                continue
            track = live_tracks[track_id]
            candidate = candidates[index]
            track["box"] = candidate["box"]
            track["confidence"] = candidate["confidence"]
            track["hits"] += 1
            track["missed"] = 0
            if candidate["quality"] > track["quality"]:
                track["crop"] = candidate["crop"]
                track["quality"] = candidate["quality"]
            matched_tracks.add(track_id)
            matched_candidates.add(index)

        for track_id, track in list(live_tracks.items()):
            if track_id not in matched_tracks:
                track["missed"] += 1
                if track["missed"] > 12:
                    live_tracks.pop(track_id, None)

        for index, candidate in enumerate(candidates):
            if index in matched_candidates:
                continue
            track_id = next_track_id
            next_track_id += 1
            live_tracks[track_id] = {
                **candidate,
                "hits": 1,
                "missed": 0,
                "queued": False,
                "label": "",
                "status": "TRACKING",
            }

        for track_id, track in live_tracks.items():
            crop = track.get("crop")
            readable_size = crop is not None and crop.shape[1] >= 90 and crop.shape[0] >= 28
            if track["hits"] >= 2 and readable_size and not track["queued"]:
                with tracking_queue_lock:
                    if len(tracking_queue) < tracking_queue.maxlen:
                        tracking_queue.append((track_id, crop.copy(), track["confidence"], camera_source_label))
                        track["queued"] = True
                        track["status"] = "OCR QUEUED"
                        tracking_queue_event.set()
        return {track_id: track.copy() for track_id, track in live_tracks.items()}


def tracking_ocr_worker():
    global last_detection_status
    while True:
        tracking_queue_event.wait()
        with tracking_queue_lock:
            task = tracking_queue.popleft() if tracking_queue else None
            if not tracking_queue:
                tracking_queue_event.clear()
        if task is None:
            continue
        track_id, crop, confidence, source = task
        try:
            last_detection_status = f"OCR reading tracked plate #{track_id}..."
            with ocr_lock:
                data = process_plate_crop(crop, source, confidence, known_numbers=live_known_numbers)
            label = data.get("number", "-")
            status = data.get("status", "Fail")
            with tracking_lock:
                if track_id in live_tracks:
                    live_tracks[track_id]["label"] = label if label != "-" else "UNREAD"
                    live_tracks[track_id]["status"] = status.upper()
            last_detection_status = f"Tracking {get_tracking_stats()['active']} plate(s)"
        except Exception as exc:
            with tracking_lock:
                if track_id in live_tracks:
                    live_tracks[track_id]["status"] = "OCR ERROR"
            last_detection_status = f"Tracking OCR failed: {exc}"


def ensure_tracking_worker():
    global tracking_worker_started
    with tracking_queue_lock:
        if tracking_worker_started:
            return
        tracking_worker_started = True
    threading.Thread(target=tracking_ocr_worker, daemon=True, name="plate-tracking-ocr").start()


def detect_plate_color(plate_crop, bottom_text, main_number):
    color, confidence = "unknown", 0.0
    if engine.color_model is not None:
        try:
            resized = cv2.resize(plate_crop, (64, 64))
            result = engine.color_model(resized, verbose=False)[0]
            color = result.names[result.probs.top1]
            confidence = float(result.probs.top1conf)
        except Exception:
            color, confidence = engine.detect_color_fallback(plate_crop)
    else:
        color, confidence = engine.detect_color_fallback(plate_crop)
    override, override_confidence = engine.detect_plate_color_by_text(bottom_text, main_number)
    return (override, override_confidence) if override else (color, confidence)


def process_plate_crop(
    plate_crop,
    source="Detection",
    detection_confidence=0.0,
    preparsed=None,
    known_numbers=None,
):
    started_at = time.perf_counter()
    if plate_crop is None or plate_crop.size == 0:
        raise ValueError("Plate crop is empty.")
    height, width = plate_crop.shape[:2]
    if width < 600:
        scale = 600 / max(width, 1)
        plate_crop = cv2.resize(
            plate_crop,
            (600, max(1, int(height * scale))),
            interpolation=cv2.INTER_LINEAR,
        )
    if preparsed is None:
        (
            region, region_conf, township, township_conf,
            main_number, main_conf, bottom_text, bottom_conf,
        ) = engine.analyze_plate_text_fast(plate_crop)
    else:
        (
            region, region_conf, township, township_conf,
            main_number, main_conf, bottom_text, bottom_conf,
        ) = preparsed
    color, color_conf = detect_plate_color(plate_crop, bottom_text, main_number)
    main_number = engine.normalize_number_for_plate_color(main_number, color)
    matched_model, match_conf, _ = engine.match_car_model_fuzzy(bottom_text)
    model = matched_model if matched_model and match_conf >= 0.70 else "-"
    township_name = engine.get_township_name(region, township)
    region_display = engine.format_region_display(region, township)
    vehicle_type = engine.get_vehicle_type(main_number, color, bottom_text)
    number = main_number or "-"
    plate_data = {
        "region": region or "-", "township": township or "-", "number": number,
        "township_name": township_name or "-", "region_display": region_display,
        "main_number": main_number or "-", "bottom_text_raw": bottom_text or "-",
        "color": color or "-", "type": vehicle_type or "-", "vehicle_type": vehicle_type or "-",
        "model": model or "-", "car_model": model or "-", "display": number,
    }
    missing_fields = get_missing_result_fields(plate_data)
    plate_data["complete"] = not missing_fields
    plate_data["missing_fields"] = missing_fields
    if known_numbers is not None and number != "-":
        if number in known_numbers:
            return {
                **plate_data,
                "status": "Duplicate",
                "source": source,
                "capture_url": None,
                "recorded": False,
            }
        known_numbers.add(number)
    saved_path = engine.save_detection(plate_crop, plate_data)
    confidence = max(region_conf, township_conf, main_conf, bottom_conf, match_conf)
    capture_file = os.path.basename(saved_path)
    event = {
        **{key: plate_data[key] for key in ("region", "township", "number", "color", "type", "model")},
        "township_name": plate_data["township_name"],
        "region_display": plate_data["region_display"],
        "confidence": round(float(confidence), 3),
        "capture_url": f"/plate_captures/{capture_file}",
        "capture_file": capture_file,
        "capture_path": saved_path,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "status": "Success" if plate_data["complete"] else "Fail",
        "complete": plate_data["complete"],
        "missing_fields": missing_fields,
        "processing_ms": round((time.perf_counter() - started_at) * 1000),
        "detection_confidence": round(float(detection_confidence), 3),
        "vehicle_type": plate_data["vehicle_type"],
        "main_number": plate_data["main_number"],
        "bottom_text_raw": plate_data["bottom_text_raw"],
        "display": plate_data["display"],
        "recorded": True,
    }
    try:
        save_detection_event(event)
    except Exception as exc:
        print(f"MLPD DB save error: {exc}")
    with lock:
        latest_data.update(event)
        recent_events.appendleft(event.copy())
    return {**plate_data, **event}


def process_plate_crop_async(plate_crop, source, confidence):
    global last_detection_status
    if not ocr_lock.acquire(blocking=False):
        return
    try:
        last_detection_status = "Plate cropped. OCR processing..."
        data = process_plate_crop(plate_crop, source, confidence)
        if data["complete"]:
            last_detection_status = f"Complete plate read: {data['number']}"
        elif data["number"] != "-":
            last_detection_status = f"Partial plate read: {data['number']}"
        else:
            last_detection_status = "Plate detected, but license plate number was not read"
    except Exception as exc:
        last_detection_status = f"OCR failed: {exc}"
        print(f"MLPD OCR worker error: {exc}")
    finally:
        ocr_lock.release()


def process_frame(frame, source="Live Camera", allow_detection=True):
    global last_detection_status
    displayed = frame.copy()
    try:
        ensure_tracking_worker()
        candidates = detect_plate_candidates(frame)
        tracks = update_live_tracks(candidates) if allow_detection else {}
        if tracks:
            for track_id, track in tracks.items():
                x1, y1, x2, y2 = track["box"]
                recognized = bool(track.get("label"))
                color = (45, 212, 168) if recognized else (0, 210, 255)
                thickness = 3 if recognized else 2
                cv2.rectangle(displayed, (x1, y1), (x2, y2), color, thickness)
                label = track.get("label") or f"PLATE #{track_id}"
                status = track.get("status", "TRACKING")
                text = f"{label}  {status}"
                (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
                label_y = max(text_height + 8, y1 - 5)
                cv2.rectangle(
                    displayed,
                    (x1, label_y - text_height - 8),
                    (min(displayed.shape[1] - 1, x1 + text_width + 10), label_y + 3),
                    color,
                    -1,
                )
                cv2.putText(
                    displayed,
                    text,
                    (x1 + 5, label_y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,
                    (8, 12, 15),
                    1,
                    cv2.LINE_AA,
                )
            stats = get_tracking_stats()
            last_detection_status = (
                f"Live tracking: {stats['active']} active / "
                f"{stats['recognized']} recognized / {stats['queued']} queued"
            )
        else:
            last_detection_status = "Live tracking active - no plates in current frame"
    except Exception as exc:
        print(f"MLPD frame processing error: {exc}")
    return displayed


def generate_frames():
    global latest_frame
    while True:
        with camera_lock:
            active_camera = camera
            success, frame = active_camera.read() if active_camera is not None else (False, None)
        if not success or frame is None:
            frame = np.full((720, 1280, 3), 18, dtype=np.uint8)
            cv2.putText(frame, "Camera stopped - press Start live view", (300, 360), cv2.FONT_HERSHEY_SIMPLEX, 1, (160, 170, 180), 2)
            time.sleep(0.35)
        else:
            frame = apply_settings(frame, camera_rotation, camera_mirror)
            frame = process_frame(frame, camera_source_label)
        with lock:
            latest_frame = frame.copy()
        ok, buffer = cv2.imencode(".jpg", frame)
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"


def process_uploaded_image(file_bytes, rotation="none", mirror=False):
    global last_detection_status
    image = cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image file")
    image = apply_settings(image, rotation, mirror)
    candidates = dedupe_plate_candidates(detect_plate_candidates(image, conf_threshold=0.03))
    if not candidates:
        special = engine.analyze_special_plate_full_image(image)
        if special is None:
            last_detection_status = "No plate detected in uploaded image"
            return {
                "success": False,
                "message": "No license plate detected. OCR was not run.",
                "result": None,
                "capture_url": None,
            }
        data = process_plate_crop(image, "Image File", 0.0, preparsed=special)
    else:
        results = []
        known_numbers = set()
        for index, candidate in enumerate(candidates, start=1):
            last_detection_status = f"OCR processing image plate {index}/{len(candidates)}..."
            data = process_plate_crop(
                candidate["crop"],
                "Image File",
                candidate["confidence"],
                known_numbers=known_numbers,
            )
            if data.get("recorded"):
                data["image_box"] = candidate["box"]
                results.append(data)
        data = min(
            results,
            key=lambda item: (
                len(item.get("missing_fields", REQUIRED_RESULT_FIELDS)),
                -float(item.get("confidence", 0)),
            ),
            default=None,
        )
        if data is None:
            last_detection_status = "Plate detected, but no readable plate was recorded"
            return {
                "success": False,
                "complete": False,
                "message": "Plate detected, but no readable plate was recorded.",
                "missing_fields": REQUIRED_RESULT_FIELDS,
                "result": None,
                "results": [],
                "capture_url": None,
                "plates_detected": 0,
            }
    results = results if "results" in locals() else [data]
    if data["complete"]:
        last_detection_status = f"Complete plate read: {data['number']}"
        message = (
            f"Image complete. {len(results)} plate(s) read."
            if len(results) > 1 else
            "Complete license plate record read successfully."
        )
    elif data["number"] == "-":
        last_detection_status = "Plate detected, but license plate number was not read"
        message = "Incomplete result: license plate number was not read."
    else:
        last_detection_status = f"Partial plate read: {data['number']}"
        message = f"Incomplete result. Missing: {', '.join(data['missing_fields'])}."
    return {
        "success": data["complete"],
        "complete": data["complete"],
        "message": message,
        "missing_fields": data["missing_fields"],
        "result": data,
        "results": results,
        "capture_url": data["capture_url"],
        "plates_detected": len(results),
    }


def crop_signature(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 32), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(gray)


def crops_are_similar(first, second, threshold=24.0):
    return float(np.mean(cv2.absdiff(first, second))) <= threshold


def process_uploaded_video(temp_path, rotation="none", mirror=False, max_samples=120, max_candidates=12):
    global last_detection_status
    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        last_detection_status = "Unable to open uploaded video"
        return {
            "success": False,
            "complete": False,
            "message": "Unable to open uploaded video. Try MP4/H.264 or AVI.",
            "missing_fields": REQUIRED_RESULT_FIELDS,
            "result": None,
            "results": [],
            "capture_url": None,
            "plates_detected": 0,
            "frames_sampled": 0,
            "candidates_found": 0,
        }
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    fps = fps if 1 <= fps <= 240 else 25.0
    total_frames = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    full_video_stride = max(1, (total_frames + max_samples - 1) // max_samples)
    sample_stride = max(1, round(fps * 0.2), full_video_stride)
    frame_count = 0
    sampled_frames = 0
    detected_frames = 0
    candidates = []
    results = []
    known_numbers = set()
    try:
        last_detection_status = "Scanning video for license plates..."
        while cap.isOpened() and sampled_frames < max_samples:
            success, frame = cap.read()
            if not success:
                break
            frame_count += 1
            if (frame_count - 1) % sample_stride != 0:
                continue
            sampled_frames += 1
            frame = apply_settings(frame, rotation, mirror)
            frame_candidates = dedupe_plate_candidates(
                detect_plate_candidates(frame, conf_threshold=0.025, imgsz=960, min_area=180),
                overlap_threshold=0.35,
                max_candidates=6,
            )
            if not frame_candidates:
                continue
            detected_frames += 1
            for frame_candidate in frame_candidates:
                crop = frame_candidate["crop"]
                signature = crop_signature(crop)
                quality = frame_candidate["quality"]
                similar_index = next(
                    (
                        index for index, candidate in enumerate(candidates)
                        if crops_are_similar(signature, candidate["signature"], threshold=18.0)
                    ),
                    None,
                )
                candidate = {
                    "crop": crop.copy(),
                    "signature": signature,
                    "confidence": frame_candidate["confidence"],
                    "quality": quality,
                    "frame": frame_count,
                    "box": frame_candidate["box"],
                }
                if similar_index is None:
                    candidates.append(candidate)
                elif quality > candidates[similar_index]["quality"]:
                    candidates[similar_index] = candidate
                if len(candidates) > max_candidates:
                    candidates.sort(key=lambda item: item["quality"], reverse=True)
                    candidates = candidates[:max_candidates]

        candidates.sort(key=lambda item: item["quality"], reverse=True)
        for index, candidate in enumerate(candidates, start=1):
            last_detection_status = f"OCR processing video plate {index}/{len(candidates)}..."
            data = process_plate_crop(
                candidate["crop"],
                "Video File",
                candidate["confidence"],
                known_numbers=known_numbers,
            )
            if data.get("recorded"):
                data["video_frame"] = candidate["frame"]
                results.append(data)
    finally:
        cap.release()
        if os.path.exists(temp_path):
            for _ in range(5):
                try:
                    os.remove(temp_path)
                    break
                except PermissionError:
                    time.sleep(0.2)
                except OSError:
                    break

    result = min(
        results,
        key=lambda item: (
            len(item.get("missing_fields", REQUIRED_RESULT_FIELDS)),
            -float(item.get("confidence", 0)),
        ),
        default=None,
    )
    complete = bool(result and result.get("complete"))
    if results:
        last_detection_status = f"Video complete: {len(results)} unique plate(s) read"
    else:
        last_detection_status = "No license plate detected in uploaded video"
    return {
        "success": complete,
        "complete": complete,
        "message": (
            f"Video complete. {len(results)} unique plate(s) read."
            if complete else
            f"Video complete. {len(results)} plate(s) read, but no complete record."
            if results else
            "No license plate detected. OCR was not run."
        ),
        "missing_fields": result.get("missing_fields", []) if result else REQUIRED_RESULT_FIELDS,
        "result": result,
        "results": results,
        "capture_url": result.get("capture_url") if result else None,
        "plates_detected": len(results),
        "frames_sampled": sampled_frames,
        "frames_with_detections": detected_frames,
        "candidates_found": len(candidates),
    }


def get_recent_events(limit=50):
    entries = get_log_entries(limit)
    if entries:
        return entries
    with lock:
        return list(recent_events)[:max(1, min(int(limit), 100))]


def clear_logs():
    with open(os.path.join(BASE_DIR, LOG_FILE), "w", encoding="utf-8"):
        pass
    with db_lock:
        with db_connect() as conn:
            conn.execute("DELETE FROM detections")
            conn.commit()
    with lock:
        recent_events.clear()
    return True
