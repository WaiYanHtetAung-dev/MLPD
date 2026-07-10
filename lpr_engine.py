# video_plate_reader_ffmpeg_only.py
# Using FFmpeg as backend for OpenCV
# Supports: Video, Webcam, and Single Image input
# Car model matching from car_models.txt with fuzzy matching
# FIXED: Main number format - second character must be A-Z (no O, convert to Q)
# FIXED: Township code - 1 or 2 digits only
# FIXED: Bottom text reading - reads entire bottom area
# FIXED: Pattern matching order - specific patterns first

import cv2
import numpy as np
from ultralytics import YOLO
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import threading
import re
import time
import sys
import uuid
from datetime import datetime
from difflib import get_close_matches, SequenceMatcher

# =========================================================
# CONFIGURATION
# =========================================================
BG_DARK = "#e2e2f0"
BG_MEDIUM = "#1a1a2e"
BG_LIGHT = "#37466e"
ACCENT = "#e94560"
SUCCESS = "#00cc88"
WARNING = "#ffaa00"
DANGER = "#ff4444"
TEXT_LIGHT = "#eeeeee"
TEXT_DIM = "#8a8a9e"

# =========================================================
# MODEL PATHS
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAR_PLATE_MODEL_PATH = os.path.join(BASE_DIR, "plate_detector.pt")
CAR_TXT_PATH = os.path.join(BASE_DIR, "car_models.txt")
REGION_RULES_PATH = os.path.join(BASE_DIR, "region-rules.txt")
MYANMAR_REGION_RULES_PATH = os.path.join(BASE_DIR, "myanmar-region-plate-rules.txt")


def find_color_model(base_dir):
    for root, _, files in os.walk(base_dir):
        if "best.pt" in files:
            return os.path.join(root, "best.pt")
    return os.path.join(base_dir, "myanmar_plate_color_v4", "weights", "best.pt")


COLOR_MODEL_PATH = find_color_model(os.path.join(BASE_DIR, "color_classifier"))

SAVE_FOLDER = os.path.join(BASE_DIR, "captures")
LOG_FILE = os.path.join(BASE_DIR, "detection_log.txt")
RUNTIME_TEMP = os.path.join(BASE_DIR, ".mlpd-runtime")

if not os.path.exists(SAVE_FOLDER):
    os.makedirs(SAVE_FOLDER)
os.makedirs(RUNTIME_TEMP, exist_ok=True)

# =========================================================
# LOAD CAR MODELS FROM car_models.txt
# =========================================================
CAR_MODELS = []
CAR_MODELS_ORIGINAL = []

def load_car_models_from_txt(txt_path):
    """Load car models from car_models.txt for matching"""
    car_models_list = []
    car_models_original = []
    
    if not os.path.exists(txt_path):
        print(f"⚠️ car_models.txt file not found: {txt_path}")
        return car_models_list, car_models_original
    
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    car_models_original.append(line)
                    model_clean = re.sub(r'\s+', ' ', line).upper()
                    car_models_list.append(model_clean)
        
        print(f"✅ Loaded {len(car_models_list)} car models from car_models.txt")
        
    except Exception as e:
        print(f"⚠️ Error loading car_models.txt: {e}")
    
    return car_models_list, car_models_original

CAR_MODELS, CAR_MODELS_ORIGINAL = load_car_models_from_txt(CAR_TXT_PATH)

# Runtime plate rules are kept in code so detection does not depend on a text/CSV file.
PLATE_RULES = {
    "PRIVATE": {"type": "Private", "background": "black"},
    "HIRE,TRUCK": {"type": "Hire / Truck", "background": "red"},
    "RELIGIOUS": {"type": "Religious", "background": "yellow"},
    "INDUSTRIAL ZONE": {"type": "Industrial Zone", "background": "red"},
    "TAXI": {"type": "Taxi", "background": "red"},
    "UN": {"type": "UN", "background": "white"},
    "EMBASSY": {"type": "Embassy", "background": "white"},
    "INTERNATIONAL ORGANIZATION": {"type": "International Organization", "background": "white"},
    "TOURING VEHICLE": {"type": "Touring Vehicle", "background": "blue"},
    "HEARSE": {"type": "Hearse", "background": "red"},
}

PRIVATE_NUMBER_PATTERN = re.compile(r"^[1-9][A-Z]-\d{3,5}$")
TAXI_NUMBER_PATTERN = re.compile(r"^([A-Z])\1-\d{3,5}$")
TWO_LETTER_NUMBER_PATTERN = re.compile(r"^[A-Z]{2}-\d{3,5}$")
SPECIAL_NUMBER_PATTERN = re.compile(r"^(CD\s?\d{1,2}-\d{1,2}|UN\s?\d{1,2}-\d{1,2}|IO-\d{3,5}|RLG-\d{3,5}|HSE-\d{3,5})$")
PRIVATE_PREFIX_OCR_REPAIRS = {
    "B": "8",
    "S": "5",
    "G": "6",
    "Z": "2",
    "I": "1",
    "L": "1",
}


def normalize_number_for_plate_color(plate_number, plate_color):
    number = (plate_number or "").upper().strip()
    color = (plate_color or "").lower().strip()
    if not number:
        return ""
    if SPECIAL_NUMBER_PATTERN.match(number) or re.match(r"^\d{3,5}$", number):
        return number
    if PRIVATE_NUMBER_PATTERN.match(number):
        return number
    two_letter_match = TWO_LETTER_NUMBER_PATTERN.match(number)
    if not two_letter_match:
        return number
    first_letter, second_letter = number[0], number[1]
    repaired_digit = PRIVATE_PREFIX_OCR_REPAIRS.get(first_letter)
    if repaired_digit and first_letter != second_letter:
        return f"{repaired_digit}{second_letter}-{number.split('-', 1)[1]}"
    if TAXI_NUMBER_PATTERN.match(number):
        return number if color == "red" else ""
    return ""

# =========================================================
# IMPROVED FUZZY MATCHING WITH SEQUENCE MATCHING
# =========================================================

def calculate_ngram_similarity(text1, text2, n=2):
    """Calculate n-gram similarity between two strings"""
    if not text1 or not text2:
        return 0
    
    grams1 = set([text1[i:i+n] for i in range(len(text1)-n+1)])
    grams2 = set([text2[i:i+n] for i in range(len(text2)-n+1)])
    
    if not grams1 or not grams2:
        return 0
    
    intersection = grams1.intersection(grams2)
    union = grams1.union(grams2)
    
    return len(intersection) / len(union) if union else 0

def calculate_word_similarity(text1, text2):
    """Calculate word-by-word similarity with weights"""
    words1 = text1.split()
    words2 = text2.split()
    
    if not words1 or not words2:
        return 0
    
    matches = 0
    total_weight = 0
    
    for i, w1 in enumerate(words1):
        weight = 1.0 / (i + 1)
        total_weight += weight
        
        best_match_score = 0
        for w2 in words2:
            if w1 == w2:
                best_match_score = 1.0
                break
            elif w1 in w2 or w2 in w1:
                ratio = min(len(w1), len(w2)) / max(len(w1), len(w2))
                best_match_score = max(best_match_score, ratio * 0.8)
            else:
                ratio = SequenceMatcher(None, w1, w2).ratio()
                best_match_score = max(best_match_score, ratio * 0.6)
        
        matches += best_match_score * weight
    
    return matches / total_weight if total_weight > 0 else 0


MODEL_OCR_REPAIRS = str.maketrans({
    "4": "A",
    "5": "S",
    "8": "B",
})

MODEL_DIGIT_REPAIRS = str.maketrans({
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "T": "7",
    "B": "8",
    "S": "5",
    "A": "4",
})


def normalize_model_ocr_text(text):
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", str(text).upper())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.translate(MODEL_OCR_REPAIRS)


def compact_model_text(text):
    return re.sub(r"[^A-Z0-9]", "", normalize_model_ocr_text(text))


def digit_aware_model_text(text):
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", str(text).upper())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.translate(MODEL_DIGIT_REPAIRS)


def numeric_model_tokens(text):
    tokens = digit_aware_model_text(text).split()
    return [token for token in tokens if re.search(r"\d", token)]


def numeric_model_score(ocr_text, model_text):
    model_tokens = numeric_model_tokens(model_text)
    if not model_tokens:
        return 1.0
    ocr_tokens = numeric_model_tokens(ocr_text)
    if not ocr_tokens:
        return 0.0
    scores = []
    for model_token in model_tokens:
        best = max(SequenceMatcher(None, ocr_token, model_token).ratio() for ocr_token in ocr_tokens)
        scores.append(best)
    return sum(scores) / len(scores)


def adjust_model_score_for_numbers(score, bottom_text, model_text):
    number_score = numeric_model_score(bottom_text, model_text)
    if number_score >= 0.9:
        return min(score + 0.08, 0.95)
    if number_score >= 0.7:
        return score
    if number_score <= 0.25:
        return score * 0.62
    return score * 0.82


def best_compact_window_score(ocr_compact, model_compact):
    if not ocr_compact or not model_compact:
        return 0
    model_len = len(model_compact)
    if len(ocr_compact) <= model_len + 2:
        return SequenceMatcher(None, ocr_compact, model_compact).ratio()

    best_score = 0
    min_len = max(4, model_len - 3)
    max_len = min(len(ocr_compact), model_len + 5)
    for size in range(min_len, max_len + 1):
        for start in range(0, len(ocr_compact) - size + 1):
            window = ocr_compact[start:start + size]
            score = SequenceMatcher(None, window, model_compact).ratio()
            if score > best_score:
                best_score = score
    return best_score


def sequential_model_word_score(ocr_words, model_words):
    if not ocr_words or not model_words:
        return 0
    score_total = 0
    last_index = -1
    for model_word in model_words:
        best_score = 0
        best_index = -1
        for index, ocr_word in enumerate(ocr_words):
            if index <= last_index:
                continue
            score = SequenceMatcher(None, ocr_word, model_word).ratio()
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0:
            last_index = best_index
        score_total += best_score
    return score_total / len(model_words)


def match_car_model_fuzzy(bottom_text):
    """Match bottom text with car models from car_models.txt using improved fuzzy matching"""
    if not bottom_text or not CAR_MODELS:
        return "", 0, ""
    
    bottom_text_clean = normalize_model_ocr_text(bottom_text)
    bottom_compact = compact_model_text(bottom_text)
    
    if len(bottom_text_clean) < 3:
        return "", 0, ""
    
    best_match = ""
    best_match_original = ""
    best_confidence = 0
    best_match_details = ""
    
    # Method 1: Exact match
    for i, model in enumerate(CAR_MODELS):
        if bottom_text_clean == model:
            print(f"[CAR MATCH] Exact match: '{model}'")
            return CAR_MODELS_ORIGINAL[i], 0.95, model
    
    # Method 2: Model is contained in bottom_text
    for i, model in enumerate(CAR_MODELS):
        if model in bottom_text_clean:
            len_diff = abs(len(model) - len(bottom_text_clean))
            if len_diff <= 3 or len(model) >= len(bottom_text_clean) - 2:
                confidence = len(model) / max(len(bottom_text_clean), 1)
                confidence = min(confidence * 1.1, 0.85)
                confidence = adjust_model_score_for_numbers(confidence, bottom_text_clean, model)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = model
                    best_match_original = CAR_MODELS_ORIGINAL[i]
                    best_match_details = f"Containment (len_diff={len_diff})"
    
    # Method 3: Bottom text is contained in model
    if best_confidence < 0.5:
        for i, model in enumerate(CAR_MODELS):
            if bottom_text_clean in model:
                len_diff = abs(len(model) - len(bottom_text_clean))
                if len_diff <= 5:
                    confidence = len(bottom_text_clean) / max(len(model), 1) * 0.8
                    confidence = adjust_model_score_for_numbers(confidence, bottom_text_clean, model)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = model
                        best_match_original = CAR_MODELS_ORIGINAL[i]
                        best_match_details = f"Model contains text (len_diff={len_diff})"
    
    # Method 4: Local noisy OCR matching against model-length windows
    bottom_words = bottom_text_clean.split()
    for i, model in enumerate(CAR_MODELS):
        model_clean = normalize_model_ocr_text(model)
        model_words = model_clean.split()
        model_compact = compact_model_text(model_clean)
        if len(model_compact) < 4:
            continue
        window_score = best_compact_window_score(bottom_compact, model_compact)
        word_score = sequential_model_word_score(bottom_words, model_words)
        combined_score = (window_score * 0.65) + (word_score * 0.35)
        if bottom_words and model_words and SequenceMatcher(None, bottom_words[0], model_words[0]).ratio() >= 0.72:
            combined_score += 0.05
        if len(model_words) >= 2 and any(
            len(ocr_word) >= 3 and len(model_word) >= 3 and ocr_word[:3] == model_word[:3]
            for model_word in model_words[1:]
            for ocr_word in bottom_words[1:]
        ):
            combined_score += 0.08
        combined_score = adjust_model_score_for_numbers(combined_score, bottom_text_clean, model_clean)
        if combined_score > best_confidence and combined_score >= 0.58:
            best_confidence = min(combined_score, 0.88)
            best_match = model_clean
            best_match_original = CAR_MODELS_ORIGINAL[i]
            best_match_details = f"Local OCR window={window_score:.2f}, words={word_score:.2f}"

    # Method 5: Word-by-word matching
    if best_confidence < 0.65:
        for i, model in enumerate(CAR_MODELS):
            model_clean = model
            model_words = model_clean.split()
            
            word_score = calculate_word_similarity(bottom_text_clean, model_clean)
            bi_gram = calculate_ngram_similarity(bottom_text_clean, model_clean, 2)
            tri_gram = calculate_ngram_similarity(bottom_text_clean, model_clean, 3)
            
            combined_score = (word_score * 0.5) + (bi_gram * 0.25) + (tri_gram * 0.25)
            
            if bottom_words and model_words:
                if bottom_words[0] == model_words[0]:
                    combined_score += 0.1
            combined_score = adjust_model_score_for_numbers(combined_score, bottom_text_clean, model_clean)
            
            if combined_score > best_confidence and combined_score > 0.4:
                best_confidence = combined_score
                best_match = model_clean
                best_match_original = CAR_MODELS_ORIGINAL[i]
                best_match_details = f"Word score={word_score:.2f}, Bi-gram={bi_gram:.2f}, Tri-gram={tri_gram:.2f}"
    
    # Method 6: Fuzzy matching using difflib
    if best_confidence < 0.55 and len(bottom_text_clean) > 3:
        best_ratio = 0
        best_idx = -1
        
        for i, model in enumerate(CAR_MODELS):
            ratio = SequenceMatcher(None, bottom_text_clean, model).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        
        if best_idx >= 0 and best_ratio > 0.55:
            len_diff = abs(len(CAR_MODELS[best_idx]) - len(bottom_text_clean))
            if len_diff <= 4:
                confidence = min(best_ratio * 0.9, 0.75)
                confidence = adjust_model_score_for_numbers(confidence, bottom_text_clean, CAR_MODELS[best_idx])
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = CAR_MODELS[best_idx]
                    best_match_original = CAR_MODELS_ORIGINAL[best_idx]
                    best_match_details = f"SequenceMatcher ratio={best_ratio:.2f}"
    
    if best_match_original and best_confidence >= 0.25:
        print(f"[CAR MATCH] '{bottom_text_clean}' → '{best_match_original}' (conf: {best_confidence:.1%}, method: {best_match_details or 'fallback'})")
        return best_match_original, best_confidence, best_match

    print(f"[CAR MATCH] No good match for '{bottom_text_clean}' (best conf: {best_confidence:.1%})")
    return "", 0, ""

# =========================================================
# MYANMAR REGION RULES
# =========================================================
DEFAULT_REGION_RANGES = {
    "AYY": (1, 26), "BGO": (1, 28), "CHN": (1, 9), "KYH": (1, 7),
    "KCN": (1, 18), "KYN": (1, 7), "MGY": (1, 25), "MDY": (1, 28),
    "MON": (1, 10), "NPW": (1, 8), "RKE": (1, 17), "SGG": (1, 37),
    "SHN": (1, 55), "TNI": (1, 10), "YGN": (1, 45),
}
REGION_OCR_REPAIRS = str.maketrans({"0": "O", "1": "I", "5": "S", "6": "G", "8": "B"})
TOWNSHIP_OCR_REPAIRS = str.maketrans({"I": "1", "L": "1"})
REGION_ALIASES = {
    "AYY": "AYY", "A4Y": "AYY", "BGO": "BGO", "BG0": "BGO", "8GO": "BGO",
    "CHN": "CHN", "GHN": "CHN", "KYH": "KYH", "KCN": "KCN", "KYN": "KYN",
    "MGY": "MGY", "MDY": "MDY", "MON": "MON", "M0N": "MON", "NPW": "NPW",
    "RKE": "RKE", "SGG": "SGG", "SHN": "SHN", "TNI": "TNI", "YGN": "YGN",
}


def _normalize_region_token(text):
    token = re.sub(r"[^A-Z0-9]", "", str(text).upper())
    if len(token) == 3:
        token = token.translate(REGION_OCR_REPAIRS)
    return REGION_ALIASES.get(token, token)


def load_region_rules():
    ranges = dict(DEFAULT_REGION_RANGES)
    details = {}

    if os.path.exists(MYANMAR_REGION_RULES_PATH):
        try:
            with open(MYANMAR_REGION_RULES_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "|" not in line:
                        continue
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) < 3 or parts[0].lower().startswith("stateorregion"):
                        continue
                    region_name, code, range_text = parts[:3]
                    match = re.match(r"^(\d+)\s*-\s*(\d+)$", range_text)
                    if not match:
                        continue
                    code = _normalize_region_token(code)
                    ranges[code] = (int(match.group(1)), int(match.group(2)))
                    details.setdefault(code, {"name": region_name, "townships": {}})
                    details[code]["name"] = region_name
        except Exception as e:
            print(f"Warning: unable to load myanmar-region-plate-rules.txt: {e}")

    if os.path.exists(REGION_RULES_PATH):
        try:
            with open(REGION_RULES_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.lower().startswith("state/region"):
                        continue
                    match = re.match(r"^(.+?)\s{2,}([A-Z0-9]{3})\s+(\d{1,2})\s+([A-Z0-9]{3}-\d{1,2})\s+(.+)$", line)
                    if not match:
                        continue
                    region_name, code, number, plate_rule, township = match.groups()
                    code = _normalize_region_token(code)
                    number_int = int(number)
                    current_min, current_max = ranges.get(code, (number_int, number_int))
                    ranges[code] = (min(current_min, number_int), max(current_max, number_int))
                    details.setdefault(code, {"name": region_name.strip(), "townships": {}})
                    details[code]["name"] = region_name.strip()
                    details[code]["townships"][number_int] = {
                        "plate_rule": plate_rule,
                        "township": township.strip(),
                    }
        except Exception as e:
            print(f"Warning: unable to load region-rules.txt: {e}")

    return ranges, details


REGION_RANGES, REGION_DETAILS = load_region_rules()
REGIONS = set(REGION_RANGES.keys())
print(f"Loaded {len(REGIONS)} region rules and {sum(len(v.get('townships', {})) for v in REGION_DETAILS.values())} township rules")


def is_valid_township(region_code, township_num):
    try:
        number = int(str(township_num).lstrip("0") or "0")
    except (TypeError, ValueError):
        return False
    min_num, max_num = REGION_RANGES.get(region_code, (1, 99))
    return min_num <= number <= max_num


def get_township_name(region_code, township_num):
    region = _normalize_region_token(region_code)
    number = normalize_township_number(township_num)
    if not region or not number:
        return ""
    details = REGION_DETAILS.get(region, {}).get("townships", {})
    township = details.get(int(number), {}).get("township") if number.isdigit() else ""
    return township or ""


def format_region_display(region_code, township_num=None):
    region = _normalize_region_token(region_code)
    if not region or region == "-":
        return "-"
    township = normalize_township_number(township_num)
    if township:
        return f"{region}-{township}"
    return region


def normalize_township_number(township_num):
    try:
        return str(int(str(township_num).lstrip("0") or "0"))
    except (TypeError, ValueError):
        return ""


def normalize_township_ocr_text(text, region_code=None):
    compact = re.sub(r"[^A-Z0-9]", "", str(text).upper()).translate(TOWNSHIP_OCR_REPAIRS)
    if region_code and len(compact) >= 3:
        matched_region, score = score_region_candidate(compact[:3])
        if matched_region == region_code and score >= 0.66:
            compact = region_code + compact[3:]
    return compact


def score_region_candidate(text):
    cleaned = re.sub(r"[^A-Z0-9]", "", str(text).upper())
    if not cleaned:
        return "", 0

    best_region = ""
    best_score = 0
    for size in (3, 4, 5):
        for index in range(0, max(1, len(cleaned) - size + 1)):
            candidate = cleaned[index:index + size]
            if len(candidate) < 3:
                continue
            normalized = _normalize_region_token(candidate[:3])
            if normalized in REGIONS:
                score = 1.0 if candidate[:3] in REGION_ALIASES or candidate[:3] == normalized else 0.92
                region = normalized
            else:
                looks_like_plate_prefix = len(cleaned) <= 5 or bool(re.match(r"\d{1,2}", cleaned[index + 3:index + 5]))
                if not looks_like_plate_prefix:
                    continue
                scored = [(region, SequenceMatcher(None, normalized[:3], region).ratio()) for region in REGIONS]
                region, score = max(scored, key=lambda item: item[1])
            if score > best_score:
                best_region = region
                best_score = score

    if not best_region and 3 <= len(cleaned) <= 5:
        candidate = cleaned[:3]
        normalized = _normalize_region_token(candidate[:3])
        if normalized in REGIONS:
            score = 1.0 if candidate[:3] in REGION_ALIASES or candidate[:3] == normalized else 0.92
            best_region = normalized
            best_score = score
        else:
            scored = [(region, SequenceMatcher(None, normalized[:3], region).ratio()) for region in REGIONS]
            best_region, best_score = max(scored, key=lambda item: item[1])

    return (best_region, best_score) if best_score >= 0.66 else ("", 0)


def extract_region_township_from_text(text, confidence=1.0):
    region, region_score = score_region_candidate(text)
    if not region:
        return "", 0, "", 0

    region_conf = float(confidence) * region_score
    compact = normalize_township_ocr_text(text, region)
    region_pos = compact.find(region)
    if region_pos < 0:
        for index in range(0, max(1, len(compact) - 2)):
            matched_region, score = score_region_candidate(compact[index:index + 3])
            if matched_region == region and score >= 0.66:
                compact = compact[:index] + region + compact[index + 3:]
                region_pos = index
                break

    township, township_conf = "", 0
    if region_pos >= 0:
        after_region = compact[region_pos + len(region):]
        match = re.match(r"(\d{1,2})", after_region)
        if match:
            candidate = normalize_township_number(match.group(1))
            if is_valid_township(region, candidate):
                township = candidate
                township_conf = region_conf

    return region, region_conf, township, township_conf

# =========================================================
# OCR SETUP
# =========================================================
os.environ['PADDLE_DEBUG'] = '0'
os.environ['FLAGS_logtostderr'] = '0'
os.environ['PADDLE_HOME'] = os.path.join(BASE_DIR, ".paddle")
os.environ['XDG_CACHE_HOME'] = os.path.join(BASE_DIR, ".cache")
os.environ['USERPROFILE'] = BASE_DIR
os.environ['TEMP'] = os.path.join(BASE_DIR, ".runtime-temp")
os.environ['TMP'] = os.environ['TEMP']
os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'BOS')
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('FLAGS_json_format_model', '0')
os.environ.setdefault('PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT', '0')
os.environ.setdefault('PADDLE_PDX_DISABLE_MKLDNN_MODEL_BL', '1')
os.environ.setdefault('PADDLE_PDX_USE_PIR_TRT', '0')
os.environ.setdefault('FLAGS_use_onednn', '0')
os.environ.setdefault('FLAGS_use_mkldnn', '0')
os.environ.setdefault('FLAGS_enable_pir_api', '0')
os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')
os.makedirs(os.environ['PADDLE_HOME'], exist_ok=True)
os.makedirs(os.environ['XDG_CACHE_HOME'], exist_ok=True)
os.makedirs(os.environ['TEMP'], exist_ok=True)

OCR_AVAILABLE = False
ocr = None
easyocr_reader = None
OCR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- "
USE_PADDLE_OCR = os.environ.get("MLPD_USE_PADDLE_OCR", "1").lower() in {"1", "true", "yes", "on"}
PADDLE_FAST_MODE = os.environ.get("MLPD_PADDLE_FAST_MODE", "1").lower() in {"1", "true", "yes", "on"}
PADDLE_MODEL_DIR = os.path.join(BASE_DIR, ".paddlex", "official_models")
PADDLE_DET_MODEL_NAME = os.environ.get("MLPD_PADDLE_DET_MODEL_NAME", "").strip()
PADDLE_REC_MODEL_NAME = os.environ.get("MLPD_PADDLE_REC_MODEL_NAME", "en_PP-OCRv5_mobile_rec")


def clean_ocr_text(text, keep_space=True):
    """Normalize OCR output without turning model/region letters into digits."""
    pattern = r"[^A-Z0-9\s-]" if keep_space else r"[^A-Z0-9-]"
    cleaned = re.sub(pattern, "", str(text).upper())
    return re.sub(r"\s+", " ", cleaned).strip()


def get_ocr_preprocess_methods(scope="general"):
    """
    Keep Paddle on the fastest useful path by default.
    EasyOCR still gets a broader retry set because it tends to need more help.
    """
    if OCR_AVAILABLE == "easyocr":
        if scope in {"bottom", "region", "township"}:
            return ("standard", "enhance", "adaptive", "sharpen", "invert")
        return ("standard", "enhance", "adaptive", "sharpen")

    if PADDLE_FAST_MODE:
        return ("standard",)

    if scope == "bottom":
        return ("standard", "enhance")
    return ("standard", "enhance")


def pick_existing_paddle_model(model_names):
    for model_name in model_names:
        if not model_name:
            continue
        model_dir = os.path.join(PADDLE_MODEL_DIR, model_name)
        if os.path.isdir(model_dir):
            return model_name, model_dir
    return "", None


def read_easyocr(image):
    """Run EasyOCR with plate-specific settings and a safe fallback."""
    global easyocr_reader
    if easyocr_reader is None:
        try:
            import easyocr as easyocr_module
            easyocr_dir = os.path.join(BASE_DIR, ".easyocr")
            os.makedirs(easyocr_dir, exist_ok=True)
            easyocr_reader = easyocr_module.Reader(
                ['en'],
                gpu=False,
                model_storage_directory=easyocr_dir,
                user_network_directory=easyocr_dir,
                download_enabled=False,
            )
            print("✅ EasyOCR fallback ready!")
        except Exception as exc:
            print(f"⚠️ EasyOCR fallback unavailable: {exc}")
            return []
    try:
        return easyocr_reader.readtext(
            image,
            allowlist=OCR_ALLOWLIST,
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            width_ths=0.9,
            contrast_ths=0.05,
            adjust_contrast=0.7,
            text_threshold=0.45,
            low_text=0.25,
            link_threshold=0.35,
        )
    except TypeError:
        return easyocr_reader.readtext(image, allowlist=OCR_ALLOWLIST)


def use_easyocr_fallback(reason=""):
    global OCR_AVAILABLE
    if OCR_AVAILABLE == "easyocr":
        return True
    try:
        read_easyocr(np.zeros((8, 8, 3), dtype=np.uint8))
        if easyocr_reader is not None:
            OCR_AVAILABLE = "easyocr"
            if reason:
                print(f"⚠️ Switching OCR backend to EasyOCR: {reason}")
            return True
    except Exception:
        return False
    return False


def extract_ocr_detections(image, method="standard"):
    """Return OCR detections as dictionaries with text, confidence, and optional box."""
    if not OCR_AVAILABLE or image is None or image.size == 0:
        return []

    h, w = image.shape[:2]
    if w < 720:
        scale = 720 / max(w, 1)
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    methods_to_try = [method]
    if OCR_AVAILABLE == "easyocr" and method == "standard":
        methods_to_try += ["enhance", "adaptive", "sharpen", "invert"]
    elif OCR_AVAILABLE != "easyocr" and method == "standard" and not PADDLE_FAST_MODE:
        methods_to_try.append("enhance")

    detections = []
    for method_name in methods_to_try:
        processed = preprocess_for_ocr(image, method_name)
        if OCR_AVAILABLE == "easyocr":
            for detection in read_easyocr(processed):
                box, text, confidence = detection
                detections.append({
                    "text": text,
                    "confidence": float(confidence),
                    "box": box,
                    "method": method_name,
                })
            continue

        try:
            paddle_input = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR) if processed.ndim == 2 else processed
            result = ocr.predict(paddle_input) if hasattr(ocr, "predict") else ocr.ocr(paddle_input)
        except Exception as exc:
            print(f"OCR backend error ({method_name}): {exc}")
            if use_easyocr_fallback(str(exc)):
                for detection in read_easyocr(processed):
                    box, text, confidence = detection
                    detections.append({
                        "text": text,
                        "confidence": float(confidence),
                        "box": box,
                        "method": method_name,
                    })
            continue

        for item in result or []:
            item_data = item.json if hasattr(item, "json") else item
            if isinstance(item_data, dict) and "res" in item_data:
                item_data = item_data["res"]
            if isinstance(item_data, dict):
                texts = item_data.get("rec_texts", [])
                scores = item_data.get("rec_scores", [])
                boxes = item_data.get("rec_boxes", [])
                for index, (text, conf) in enumerate(zip(texts, scores)):
                    box = boxes[index] if index < len(boxes) else None
                    detections.append({
                        "text": text,
                        "confidence": float(conf),
                        "box": box,
                        "method": method_name,
                    })
            elif isinstance(item_data, list):
                for line in item_data:
                    if line and len(line) > 1:
                        box = line[0] if len(line) > 0 else None
                        text, conf = line[1][0], line[1][1]
                        detections.append({
                            "text": text,
                            "confidence": float(conf),
                            "box": box,
                            "method": method_name,
                        })

    return detections

try:
    if not USE_PADDLE_OCR:
        raise RuntimeError("PaddleOCR disabled by default; using EasyOCR backend")
    if sys.platform.startswith("win") and sys.version_info >= (3, 14):
        raise RuntimeError("PaddleOCR is unavailable on Windows Python 3.14+")
    from paddleocr import PaddleOCR
    print("Initializing PaddleOCR...")
    try:
        paddle_models = PADDLE_MODEL_DIR
        det_candidates = []
        if PADDLE_DET_MODEL_NAME:
            det_candidates.append(PADDLE_DET_MODEL_NAME)
        if PADDLE_FAST_MODE:
            det_candidates.extend(["PP-OCRv5_mobile_det", "PP-OCRv5_server_det"])
        else:
            det_candidates.extend(["PP-OCRv5_server_det", "PP-OCRv5_mobile_det"])
        det_candidates = list(dict.fromkeys(det_candidates))
        det_model_name, det_model_dir = pick_existing_paddle_model(det_candidates)
        rec_model_name, rec_model_dir = pick_existing_paddle_model([PADDLE_REC_MODEL_NAME, "en_PP-OCRv5_mobile_rec"])
        if not rec_model_name:
            rec_model_name = PADDLE_REC_MODEL_NAME
        paddle_kwargs = dict(
            lang='en',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_recognition_model_name=rec_model_name,
            text_recognition_model_dir=rec_model_dir,
        )
        if det_model_dir:
            paddle_kwargs.update(
                text_detection_model_name=det_model_name,
                text_detection_model_dir=det_model_dir,
            )
        ocr = PaddleOCR(
            **paddle_kwargs,
        )
    except TypeError:
        ocr = PaddleOCR(lang='en', show_log=False, use_angle_cls=False, use_gpu=False)
    OCR_AVAILABLE = True
    print("✅ PaddleOCR ready!")
except Exception as e:
    print(f"⚠️ PaddleOCR not available: {e}")
    try:
        import easyocr
        easyocr_dir = os.path.join(BASE_DIR, ".easyocr")
        os.makedirs(easyocr_dir, exist_ok=True)
        ocr = easyocr.Reader(
            ['en'],
            gpu=False,
            model_storage_directory=easyocr_dir,
            user_network_directory=easyocr_dir,
        )
        OCR_AVAILABLE = "easyocr"
        print("✅ EasyOCR ready!")
    except Exception as easyocr_error:
        print(f"⚠️ No OCR available: {easyocr_error}")

# =========================================================
# LOAD MODELS
# =========================================================
print("\nLoading YOLO model...")
model = YOLO(CAR_PLATE_MODEL_PATH)
print("✅ Model loaded!")

color_model = None
try:
    color_model = YOLO(COLOR_MODEL_PATH)
    print("✅ Color model loaded!")
except Exception as e:
    print(f"⚠️ Color model not loaded: {e}")

# =========================================================
# IMPROVED OCR WITH PREPROCESSING FOR REGION TEXT
# =========================================================

def preprocess_for_ocr(image, method="standard"):
    """Apply preprocessing to improve OCR accuracy for small text"""
    if image is None or image.size == 0:
        return image
    
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    
    if method == "standard":
        return gray
    elif method == "enhance":
        gray = cv2.equalizeHist(gray)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
    elif method == "sharpen":
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        _, binary = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
    elif method == "adaptive":
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 9
        )
    elif method == "invert":
        enhanced = cv2.equalizeHist(gray)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return binary
    
    return gray

def simple_ocr_enhanced(image, method="standard"):
    """Enhanced OCR with preprocessing options"""
    if not OCR_AVAILABLE or image is None or image.size == 0:
        return "", 0

    try:
        best_text = ""
        best_conf = 0
        for detection in extract_ocr_detections(image, method):
            text = detection.get("text", "")
            conf = float(detection.get("confidence", 0))
            if conf > best_conf and len(text) >= 2:
                best_text = text
                best_conf = conf
                print(f"[OCR {detection.get('method', method)}] Found: '{text}' (conf: {conf:.2%})")

        cleaned = clean_ocr_text(best_text)
        print(f"[OCR FINAL] Best text: '{cleaned}' (conf: {best_conf:.2%})")
        return cleaned, best_conf
    except Exception as e:
        print(f"OCR error: {e}")
        return "", 0

def simple_ocr(image):
    return simple_ocr_enhanced(image, "standard")


def get_ocr_candidates(image, method="standard"):
    """Return every OCR line so plate-number parsing does not lose a lower-confidence line."""
    if not OCR_AVAILABLE or image is None or image.size == 0:
        return []
    candidates = []

    try:
        for detection in extract_ocr_detections(image, method):
            cleaned = clean_ocr_text(detection.get("text", ""))
            confidence = float(detection.get("confidence", 0))
            if cleaned:
                candidates.append((cleaned, confidence))
    except Exception as exc:
        print(f"OCR candidate error: {exc}")

    return candidates


def get_positioned_ocr_lines(image, method="standard"):
    """Return OCR lines with normalized vertical positions for three-line plates."""
    if not OCR_AVAILABLE or image is None or image.size == 0:
        return []
    lines = []
    for detection in extract_ocr_detections(image, method):
        cleaned = clean_ocr_text(detection.get("text", ""))
        if not cleaned:
            continue
        box = detection.get("box")
        y_center = 0.5
        if box is not None:
            try:
                y_center = (float(box[1]) + float(box[3])) / 2 / max(image.shape[0], 1)
            except Exception:
                y_center = 0.5
        lines.append((cleaned, float(detection.get("confidence", 0)), y_center))
    return lines


def merge_same_row_ocr_lines(lines, tolerance=0.06):
    """Merge OCR tokens that Paddle returns separately on the same plate row."""
    rows = []
    for text, confidence, y_center in sorted(lines, key=lambda item: item[2]):
        row = next((item for item in rows if abs(item["y"] - y_center) <= tolerance), None)
        if row is None:
            rows.append({"texts": [text], "confidence": confidence, "y": y_center})
        else:
            row["texts"].append(text)
            row["confidence"] = max(row["confidence"], confidence)
            row["y"] = (row["y"] + y_center) / 2
    return [(" ".join(row["texts"]), row["confidence"], row["y"]) for row in rows]


def collect_positioned_ocr_lines(image, methods=("standard", "enhance", "adaptive", "sharpen")):
    """Collect OCR rows from several preprocess variants and remove duplicates."""
    methods = get_ocr_preprocess_methods("positioned")
    collected = []
    seen = set()
    for method in methods:
        for text, confidence, y_center in get_positioned_ocr_lines(image, method):
            key = (re.sub(r"[^A-Z0-9]", "", text.upper()), round(y_center, 1))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            collected.append((text, confidence, y_center))
    return collected


def extract_main_number(text):
    """Extract and contextually repair a plate number from one OCR line."""
    cleaned = re.sub(r"\s+", "", text.upper())
    numeric_map = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1"})

    special_patterns = [
        (r"CD(\d{1,2})-?(\d{1,2})", lambda m: f"CD {m.group(1)}-{m.group(2)}"),
        (r"UN(\d{1,2})-?(\d{1,2})", lambda m: f"UN {m.group(1)}-{m.group(2)}"),
        (r"(IO|RLG|HSE)-?([0-9OQIL]{4})", lambda m: f"{m.group(1)}-{m.group(2).translate(numeric_map)}"),
    ]
    for pattern, formatter in special_patterns:
        match = re.search(pattern, cleaned)
        if match:
            return formatter(match)

    match = re.search(r"([1-9OQIL])([A-Z0-9])[-\s]?([0-9OQIL]{4})", cleaned)
    if match:
        prefix = match.group(1).translate(numeric_map)
        letter = match.group(2)
        suffix = match.group(3).translate(numeric_map)
        if prefix.startswith("0"):
            return ""
        if letter.isdigit():
            letter = {"0": "Q", "1": "A", "2": "B", "3": "C", "4": "D",
                      "5": "E", "6": "F", "7": "G", "8": "H", "9": "I"}[letter]
        return f"{prefix}{letter}-{suffix}"

    match = re.search(r"([A-Z]{2})-?([0-9OQIL]{4})", cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2).translate(numeric_map)}"
    return ""


def analyze_plate_text_fast(plate_img):
    """Read top region, middle number, and bottom model as separate plate lines."""
    positioned = merge_same_row_ocr_lines(collect_positioned_ocr_lines(plate_img))
    candidates = [(text, confidence) for text, confidence, _ in positioned]
    middle_candidates = [
        (text, confidence) for text, confidence, y_center in positioned
        if 0.30 <= y_center <= 0.76
    ]
    main_matches = [
        (extract_main_number(text), confidence, text)
        for text, confidence in middle_candidates
        if confidence >= 0.25 and extract_main_number(text)
    ]
    combined_middle = " ".join(text for text, _ in middle_candidates)
    combined_number = extract_main_number(combined_middle)
    if combined_number:
        main_matches.append((combined_number, max((confidence for _, confidence in middle_candidates), default=0), combined_middle))

    if not main_matches:
        height = plate_img.shape[0]
        middle = plate_img[int(height * 0.20):int(height * 0.82), :]
        fallback = []
        for method in ("standard", "enhance", "adaptive", "sharpen"):
            fallback.extend(get_ocr_candidates(middle, method))
        candidates.extend(fallback)
        combined_fallback = " ".join(text for text, _ in fallback)
        main_matches = [
            (extract_main_number(text), confidence, text)
            for text, confidence in fallback
            if confidence >= 0.25 and extract_main_number(text)
        ]
        combined_number = extract_main_number(combined_fallback)
        if combined_number:
            main_matches.append((combined_number, max((confidence for _, confidence in fallback), default=0), combined_fallback))
        if not main_matches:
            enhanced = []
            for method in ("enhance", "adaptive", "sharpen"):
                enhanced.extend(get_ocr_candidates(middle, method))
            prefix = next((re.search(r"([1-9][A-Z])", text.replace(" ", "")) for text, _ in fallback if re.search(r"([1-9][A-Z])", text.replace(" ", ""))), None)
            digits = next((re.search(r"(\d{4})", text.replace(" ", "")) for text, _ in enhanced if re.search(r"(\d{4})", text.replace(" ", ""))), None)
            if prefix and digits:
                rebuilt = f"{prefix.group(1)}-{digits.group(1)}"
                main_matches.append((rebuilt, 0.60, rebuilt))

    main_number, main_conf = ("", 0)
    if main_matches:
        main_number, main_conf, _ = max(main_matches, key=lambda item: item[1])

    region, township, region_conf, township_conf = "", "", 0, 0
    top_candidates = [(text, confidence) for text, confidence, y_center in positioned if y_center <= 0.48]
    for text, confidence in top_candidates:
        matched_region, matched_region_conf, matched_township, matched_township_conf = extract_region_township_from_text(text, confidence)
        if matched_region and matched_region_conf > region_conf:
            region, region_conf = matched_region, matched_region_conf
            township, township_conf = matched_township, matched_township_conf
        elif matched_region == region and matched_township and matched_township_conf > township_conf:
            township, township_conf = matched_township, matched_township_conf

    if not region:
        region, region_conf = read_region_code(plate_img)
    if region and not township:
        township, township_conf = read_township_from_region(plate_img, region)
    if not region and top_candidates:
        top_text = " ".join(text for text, _ in top_candidates)
        matched_region, matched_region_conf, matched_township, matched_township_conf = extract_region_township_from_text(top_text, max((confidence for _, confidence in top_candidates), default=0))
        if matched_region:
            region, region_conf = matched_region, matched_region_conf
            township, township_conf = matched_township, matched_township_conf
    if region and not township:
        township, township_conf = read_township_from_region(plate_img, region)

    bottom_text, bottom_conf = "", 0
    bottom_candidates = [(text, confidence) for text, confidence, y_center in positioned if y_center >= 0.58]
    for text, confidence in bottom_candidates:
        if extract_main_number(text):
            continue
        if re.match(r"^(RLG|HSE|IO|CD|UN)[-\s]?[0-9OQIL]*$", text.upper()):
            continue
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        if region and compact.startswith(region[:2]):
            continue
        letters = len(re.findall(r"[A-Z]", text.upper()))
        if confidence >= 0.35 and letters >= 3 and not re.search(r"\d{3,}", text) and (
            letters > len(re.findall(r"[A-Z]", bottom_text)) or confidence > bottom_conf
        ):
            bottom_text = re.sub(r"[^A-Z0-9\s]", "", text.upper()).strip()
            bottom_conf = confidence

    if not bottom_text:
        fallback_bottom, fallback_conf = read_bottom_text(plate_img)
        if fallback_conf > bottom_conf:
            bottom_text, bottom_conf = fallback_bottom, fallback_conf

    print(
        f"[FAST OCR] region={region}-{township}, main={main_number}, "
        f"bottom='{bottom_text}', positioned_lines={len(positioned)}"
    )
    return region, region_conf, township, township_conf, main_number, main_conf, bottom_text, bottom_conf


def analyze_special_plate_full_image(image):
    """Fallback for clearly readable CD/RLG/UN/IO/HSE plates missed by YOLO."""
    lines = merge_same_row_ocr_lines(collect_positioned_ocr_lines(image))
    special = []
    for text, confidence, y_center in lines:
        number = extract_main_number(text)
        if number.startswith(("CD ", "UN ", "IO-", "RLG-", "HSE-")) and confidence >= 0.45:
            special.append((number, confidence, y_center))
    if not special:
        return None

    main_number, main_conf, main_y = max(special, key=lambda item: item[1])
    region, region_conf, township, township_conf = "", 0, "", 0
    for text, confidence, _ in lines:
        matched_region, matched_region_conf, matched_township, matched_township_conf = extract_region_township_from_text(text, confidence)
        if matched_region and matched_region_conf > region_conf:
            region, region_conf = matched_region, matched_region_conf
            township, township_conf = matched_township, matched_township_conf
        elif matched_region == region and matched_township and matched_township_conf > township_conf:
            township, township_conf = matched_township, matched_township_conf

    bottom_text, bottom_conf = "", 0
    for text, confidence, y_center in lines:
        if y_center <= main_y or y_center - main_y > 0.15 or extract_main_number(text):
            continue
        if len(re.findall(r"[A-Z]", text.upper())) >= 3 and confidence > bottom_conf:
            bottom_text, bottom_conf = text, confidence
    return region, region_conf, township, township_conf, main_number, main_conf, bottom_text, bottom_conf


# =========================================================
# PLATE COLOR DETECTION
# =========================================================

def detect_plate_color_by_text(bottom_text, main_number):
    text = f"{bottom_text} {main_number}".upper()

    special_rules = [
        (r"CD\s?\d{1,2}-\d{1,2}", "EMBASSY"),
        (r"UN\s?\d{1,2}-\d{1,2}", "UN"),
        (r"IO-\d{3,5}", "INTERNATIONAL ORGANIZATION"),
        (r"RLG-\d{3,5}", "RELIGIOUS"),
        (r"HSE-\d{3,5}", "HEARSE"),
    ]
    for pattern, rule_name in special_rules:
        if re.search(pattern, text):
            rule = PLATE_RULES.get(rule_name)
            if rule:
                return rule["background"], 0.95
    
    return None, 0

def detect_plate_color(plate_img):
    if plate_img is None or plate_img.size == 0:
        return "unknown", 0
    
    color = "unknown"
    confidence = 0
    
    if color_model is not None:
        try:
            resized = cv2.resize(plate_img, (64, 64))
            results = color_model(resized, verbose=False)
            probs = results[0].probs
            color = results[0].names[probs.top1]
            confidence = probs.top1conf.item()
            print(f"[COLOR MODEL] Detected: {color} ({confidence:.2%})")
        except:
            color, confidence = detect_color_fallback(plate_img)
    else:
        color, confidence = detect_color_fallback(plate_img)
    
    try:
        bottom_text, _ = read_bottom_text(plate_img)
        main_number, _ = read_main_number(plate_img)
        override_color, _ = detect_plate_color_by_text(bottom_text, main_number)
        if override_color:
            print(f"[COLOR OVERRIDE] {color} -> {override_color}")
            return override_color, 0.95
    except:
        pass
    
    return color, confidence

def detect_color_fallback(plate_img):
    hsv = cv2.cvtColor(plate_img, cv2.COLOR_BGR2HSV)
    
    color_ranges = {
        'black': ([0, 0, 0], [180, 255, 80]),
        'white': ([0, 0, 200], [180, 30, 255]),
        'yellow': ([20, 80, 80], [35, 255, 255]),
        'blue': ([100, 80, 80], [130, 255, 255]),
        'red': ([0, 80, 80], [10, 255, 255]),
    }
    
    best_color = "unknown"
    best_count = 0
    
    for color_name, (lower, upper) in color_ranges.items():
        lower = np.array(lower)
        upper = np.array(upper)
        mask = cv2.inRange(hsv, lower, upper)
        
        if color_name == 'red':
            lower2 = np.array([160, 80, 80])
            upper2 = np.array([180, 255, 255])
            mask2 = cv2.inRange(hsv, lower2, upper2)
            mask = cv2.bitwise_or(mask, mask2)
        
        count = cv2.countNonZero(mask)
        if count > best_count:
            best_count = count
            best_color = color_name
    
    total_pixels = plate_img.shape[0] * plate_img.shape[1]
    confidence = min(best_count / total_pixels, 0.95)
    return best_color, confidence

# =========================================================
# MAIN NUMBER READING - FIXED (correct pattern order)
# =========================================================

def fix_main_number_format(number_text):
    """
    Fix Myanmar license plate main number format
    Second character must be A-Z (no O, convert to Q)
    """
    if not number_text:
        return ""
    
    original = number_text.strip()
    print(f"[FIX INPUT] '{original}'")
    
    # Special patterns first
    if 'CD' in original:
        match = re.search(r'CD\s?(\d{1,2})[-]?\s?(\d{1,2})', original)
        if match:
            return f"CD {match.group(1)}-{match.group(2)}"
    
    if 'UN' in original:
        match = re.search(r'UN\s?(\d{1,2})[-]?\s?(\d{1,2})', original)
        if match:
            return f"UN {match.group(1)}-{match.group(2)}"
    
    if 'IO' in original:
        match = re.search(r'IO[-]?(\d{3,4})', original)
        if match:
            return f"IO-{match.group(1)}"
    
    if 'RLG' in original:
        match = re.search(r'RLG[-]?(\d{3,4})', original)
        if match:
            return f"RLG-{match.group(1)}"
    
    if 'HSE' in original:
        match = re.search(r'HSE[-]?(\d{3,4})', original)
        if match:
            return f"HSE-{match.group(1)}"
    
    # Fix common OCR errors
    fixed = original
    
    # Pattern: digit + digit + hyphen + digits (e.g., "40-8429" -> "4Q-8429")
    pattern = r'^(\d)(\d)-(\d{3,5})$'
    match = re.match(pattern, fixed)
    if match:
        first_digit = match.group(1)
        second_char = match.group(2)
        rest = match.group(3)
        
        if second_char == '0':
            second_char = 'Q'
            print(f"[FIX] '0' -> 'Q'")
        elif second_char == 'O':
            second_char = 'Q'
            print(f"[FIX] 'O' -> 'Q'")
        elif second_char.isdigit():
            digit_map = {'1':'A', '2':'B', '3':'C', '4':'D', '5':'E', 
                        '6':'F', '7':'G', '8':'H', '9':'I'}
            if second_char in digit_map:
                original_char = second_char
                second_char = digit_map[second_char]
                print(f"[FIX] '{original_char}' -> '{second_char}'")
        
        result = f"{first_digit}{second_char}-{rest}"
        print(f"[FIX RESULT] '{original}' -> '{result}'")
        return result
    
    # Pattern: digit + letter + hyphen + digits (correct format, validate letter)
    pattern_correct = r'^(\d{1,2})([A-Z])-(\d{3,5})$'
    match = re.match(pattern_correct, fixed)
    if match:
        prefix = match.group(1)
        letter = match.group(2)
        suffix = match.group(3)
        
        if letter == 'O':
            letter = 'Q'
            print(f"[FIX] Letter 'O' -> 'Q'")
        
        result = f"{prefix}{letter}-{suffix}"
        if result != original:
            print(f"[FIX RESULT] '{original}' -> '{result}'")
        return result
    
    # Pattern: digit + letter + digits (no hyphen)
    pattern_no_hyphen = r'^(\d{1,2})([A-Z])(\d{3,5})$'
    match = re.match(pattern_no_hyphen, fixed)
    if match:
        prefix = match.group(1)
        letter = match.group(2)
        suffix = match.group(3)
        
        if letter == 'O':
            letter = 'Q'
        
        result = f"{prefix}{letter}-{suffix}"
        print(f"[FIX RESULT] '{original}' -> '{result}'")
        return result
    
    # Pattern: digit + digit + digits (no hyphen, e.g., "408429")
    pattern_digit_digit = r'^(\d{1,2})(\d)(\d{3,5})$'
    match = re.match(pattern_digit_digit, fixed)
    if match:
        prefix = match.group(1)
        second_char = match.group(2)
        suffix = match.group(3)
        
        if second_char == '0':
            second_char = 'Q'
        elif second_char == 'O':
            second_char = 'Q'
        elif second_char.isdigit():
            digit_map = {'1':'A', '2':'B', '3':'C', '4':'D', '5':'E', 
                        '6':'F', '7':'G', '8':'H', '9':'I'}
            if second_char in digit_map:
                second_char = digit_map[second_char]
        
        result = f"{prefix}{second_char}-{suffix}"
        print(f"[FIX RESULT] '{original}' -> '{result}'")
        return result
    
    # If hyphen exists but not matching pattern, try to fix second character
    if '-' in fixed:
        parts = fixed.split('-')
        if len(parts) == 2 and len(parts[0]) == 2:
            first_part = parts[0]
            second_part = parts[1]
            if first_part[1] == '0' or first_part[1] == 'O':
                first_part = first_part[0] + 'Q'
                result = f"{first_part}-{second_part}"
                print(f"[FIX RESULT] '{original}' -> '{result}'")
                return result
    
    print(f"[FIX RESULT] '{original}' (no change)")
    return original

def read_main_number(plate_img):
    """Read the middle plate line and select a valid number from all OCR lines."""
    h, w = plate_img.shape[:2]
    
    regions_to_try = [
        (int(h * 0.20), int(h * 0.80)),
        (int(h * 0.25), int(h * 0.75)),
        (int(h * 0.15), int(h * 0.85)),
        (int(h * 0.28), int(h * 0.78)),
        (0, h),
    ]

    valid_candidates = []
    for y1, y2 in regions_to_try:
        middle = plate_img[y1:y2, :]
        for method in get_ocr_preprocess_methods("main_number"):
            for text, confidence in get_ocr_candidates(middle, method):
                number = extract_main_number(text)
                if number:
                    if confidence >= 0.80:
                        print(f"[MAIN NUMBER] '{text}' -> '{number}' (conf: {confidence:.2%})")
                        return number, confidence
                    valid_candidates.append((number, confidence, text))

    if valid_candidates:
        number, confidence, raw_text = max(valid_candidates, key=lambda item: item[1])
        print(f"[MAIN NUMBER] '{raw_text}' -> '{number}' (conf: {confidence:.2%})")
        return number, confidence

    print("[MAIN NUMBER] No valid plate-number pattern detected")
    return "", 0

# =========================================================
# IMPROVED REGION AND TOWNSHIP DETECTION
# =========================================================

def read_region_code(plate_img):
    """Read Myanmar region code using the region rule files as the source of truth."""
    h, w = plate_img.shape[:2]
    
    portions = [
        (0, int(h * 0.35)),
        (0, int(h * 0.30)),
        (0, int(h * 0.40)),
        (int(h * 0.05), int(h * 0.40)),
        (int(h * 0.10), int(h * 0.45)),
    ]
    
    best_region = ""
    best_conf = 0
    
    for y1, y2 in portions:
        region_img = plate_img[y1:y2, :]
        
        for preprocess_method in get_ocr_preprocess_methods("region"):
            text, conf = simple_ocr_enhanced(region_img, preprocess_method)
            
            print(f"[REGION OCR] y1={y1}, y2={y2}, method={preprocess_method}: '{text}' (conf: {conf:.2%})")
            
            region, match_score = score_region_candidate(text)
            combined_conf = conf * match_score
            if region and combined_conf > best_conf:
                best_conf = combined_conf
                best_region = region
                print(f"[REGION DETECTED] Rule match: '{text}' -> '{region}' (score: {match_score:.2%})")
            
            if best_region and best_conf > 0.5:
                break
        
        if best_region and best_conf > 0.5:
            break
    
    return best_region, best_conf

def read_township_from_region(plate_img, region_code):
    """
    Read a township number only when it matches the selected region's rule range.
    """
    if not region_code or plate_img is None:
        return "", 0

    region_code = _normalize_region_token(region_code)
    if region_code not in REGIONS:
        matched_region, score = score_region_candidate(region_code)
        if not matched_region or score < 0.66:
            return "", 0
        region_code = matched_region
    
    h, w = plate_img.shape[:2]
    
    areas = [
        (0, int(h * 0.5)),
        (0, int(h * 0.45)),
        (int(h * 0.05), int(h * 0.5)),
        (int(h * 0.10), int(h * 0.55)),
        (0, int(h * 0.35)),
        (int(h * 0.02), int(h * 0.48)),
    ]
    
    best_township = ""
    best_conf = 0
    
    for y1, y2 in areas:
        top_part = plate_img[y1:y2, :]
        
        for preprocess_method in get_ocr_preprocess_methods("township"):
            text, conf = simple_ocr_enhanced(top_part, preprocess_method)
            text_upper = text.upper().strip()
            print(f"[TOWNSHIP OCR DETAIL] y1={y1}, y2={y2}, method={preprocess_method}: '{text_upper}' (conf: {conf:.2%})")
            
            cleaned_text = normalize_township_ocr_text(text_upper, region_code)
            text_for_township = re.sub(r"[^A-Z0-9\s-]", "", text_upper).translate(TOWNSHIP_OCR_REPAIRS)

            def accept_township(township_num, label, multiplier):
                nonlocal best_township, best_conf
                normalized_num = normalize_township_number(township_num)
                if not normalized_num or not is_valid_township(region_code, normalized_num):
                    print(f"[TOWNSHIP REJECTED] {label}: '{township_num}' outside {region_code} rule range")
                    return False
                candidate_conf = conf * multiplier
                if candidate_conf > best_conf:
                    best_township = normalized_num
                    best_conf = candidate_conf
                    print(f"[TOWNSHIP DETECTED] {label}: {region_code}-{normalized_num}")
                return True
            
            # Method 1: region code + numbers (no separator) - e.g., "BGO27"
            pattern1 = rf'{region_code}(\d{{1,2}})'
            match = re.search(pattern1, cleaned_text)
            if match:
                township_num = match.group(1)
                if accept_township(township_num, "Pattern 1", 0.98):
                    continue
            
            # Method 2: region code + space/hyphen + numbers - e.g., "BGO 27", "BGO-27"
            pattern2 = rf'{region_code}[\s-](\d{{1,2}})'
            match = re.search(pattern2, text_for_township)
            if match:
                township_num = match.group(1)
                if accept_township(township_num, "Pattern 2", 1.0):
                    continue
            
            # Method 3: First 2 letters of region + numbers (fuzzy)
            if len(region_code) >= 2:
                region_prefix = region_code[:2]
                pattern3 = rf'{region_prefix}[A-Z0-9]?[\s-]?(\d{{1,2}})'
                match = re.search(pattern3, text_for_township)
                if match:
                    matched_text = match.group(0)
                    matched_region, region_score = score_region_candidate(matched_text)
                    if matched_region == region_code and region_score >= 0.66:
                        township_num = match.group(1)
                        if accept_township(township_num, "Pattern 3", 0.9):
                            continue
            
            # Method 4: Region present, look for closest number
            matched_region, region_score = score_region_candidate(text_upper)
            if matched_region == region_code and region_score >= 0.70:
                pos = max(cleaned_text.find(region_code), 0)
                after_region = cleaned_text[pos + len(region_code):] if region_code in cleaned_text else cleaned_text
                number_match = re.search(r'(\d{1,2})', after_region)
                if number_match:
                    township_num = number_match.group(1)
                    if len(after_region) < 20 or number_match.start() < 15:
                        if accept_township(township_num, "Pattern 4", 0.85):
                            continue
            
            # Method 5: Any 1-2 digit number in the top area
            if matched_region == region_code and region_score >= 0.75:
                all_numbers = re.findall(r'(\d{1,2})', cleaned_text)
                for township_num in all_numbers:
                    if accept_township(township_num, "Pattern 5", 0.75):
                        break
    
    if best_township:
        print(f"[TOWNSHIP FINAL] Code: {best_township}, Confidence: {best_conf:.2%}")
    else:
        print(f"[TOWNSHIP FINAL] No township code detected for region '{region_code}'")
    
    return best_township, best_conf

# =========================================================
# BOTTOM TEXT READING
# =========================================================

def read_bottom_text(plate_img):
    """Read bottom text from license plate - reads entire bottom area"""
    h, w = plate_img.shape[:2]

    search_windows = [
        (0.48, 1.00),
        (0.55, 1.00),
        (0.62, 1.00),
    ]
    methods = get_ocr_preprocess_methods("bottom")
    best_text = ""
    best_conf = 0.0

    for y1_ratio, y2_ratio in search_windows:
        bottom = plate_img[int(h * y1_ratio):int(h * y2_ratio), :]
        if bottom.size == 0:
            continue
        for method in methods:
            for text, conf in get_ocr_candidates(bottom, method):
                cleaned = re.sub(r'[^A-Z0-9\s]', '', text.upper()).strip()
                if not cleaned:
                    continue
                alpha_count = len(re.findall(r"[A-Z]", cleaned))
                digit_count = len(re.findall(r"\d", cleaned))
                score = float(conf)
                if alpha_count >= 3:
                    score += 0.08
                if 2 <= len(cleaned) <= 30:
                    score += 0.03
                if digit_count == 0:
                    score += 0.02
                if score > best_conf and (alpha_count >= 3 or len(cleaned) >= 4):
                    best_text = cleaned
                    best_conf = min(score, 0.99)

    print(f"[BOTTOM TEXT OCR] Cleaned: '{best_text}', Conf: {best_conf:.2%}")
    return best_text, best_conf

def get_vehicle_type(plate_number, plate_color, bottom_text=""):
    plate_number = plate_number or ""
    color = plate_color.lower()
    plate_number = normalize_number_for_plate_color(plate_number, color)

    if re.match(r'^CD\s?\d{1,2}-\d{1,2}$', plate_number):
        return PLATE_RULES.get("EMBASSY", {}).get("type", "Embassy")
    elif re.match(r'^UN\s?\d{1,2}-\d{1,2}$', plate_number):
        return PLATE_RULES.get("UN", {}).get("type", "UN")
    elif re.match(r'^IO-\d{3,5}$', plate_number):
        return PLATE_RULES.get("INTERNATIONAL ORGANIZATION", {}).get("type", "International Organization")
    elif re.match(r'^RLG-\d{3,5}$', plate_number):
        return PLATE_RULES.get("RELIGIOUS", {}).get("type", "Religious")
    elif re.match(r'^HSE-\d{3,5}$', plate_number):
        return PLATE_RULES.get("HEARSE", {}).get("type", "Hearse")
    if re.match(r'^\d{3,5}$', plate_number):
        return "Motorcycle"

    if not plate_number:
        if color == "red" and re.search(r"\bI[\s-]?ZONE\b", bottom_text.upper()):
            return PLATE_RULES.get("INDUSTRIAL ZONE", {}).get("type", "Industrial Zone")
        return "Unknown"

    if color == "black":
        return PLATE_RULES.get("PRIVATE", {}).get("type", "Private")
    if color == "yellow":
        return PLATE_RULES.get("RELIGIOUS", {}).get("type", "Religious")
    if color == "blue":
        return PLATE_RULES.get("TOURING VEHICLE", {}).get("type", "Touring Vehicle")
    if color == "white":
        return PLATE_RULES.get("EMBASSY", {}).get("type", "Embassy")
    if color == "mahogany":
        return PLATE_RULES.get("HEARSE", {}).get("type", "Hearse")
    if color == "red":
        if re.search(r"\bI[\s-]?ZONE\b", bottom_text.upper()):
            return PLATE_RULES.get("INDUSTRIAL ZONE", {}).get("type", "Industrial Zone")
        if TAXI_NUMBER_PATTERN.match(plate_number):
            return PLATE_RULES.get("TAXI", {}).get("type", "Taxi")
        return PLATE_RULES.get("HIRE,TRUCK", {}).get("type", "Hire,truck")
    return "Unknown"

def save_detection(plate_img, plate_data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"{SAVE_FOLDER}/plate_{timestamp}.jpg"
    if not cv2.imwrite(filename, plate_img):
        raise OSError(f"Unable to save plate crop: {filename}")
    
    log_entry = f"""
{'='*60}
TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
FILE: {filename}
REGION: {plate_data.get('region', 'N/A')}
TOWNSHIP: {plate_data.get('township', 'N/A')}
MAIN NUMBER: {plate_data.get('main_number', 'N/A')}
BOTTOM TEXT (OCR): {plate_data.get('bottom_text_raw', 'N/A')}
CAR MODEL (MATCHED): {plate_data.get('car_model', 'N/A')}
COLOR: {plate_data.get('color', 'N/A')}
VEHICLE TYPE: {plate_data.get('vehicle_type', 'N/A')}
DISPLAY: {plate_data.get('display', 'N/A')}
STATUS: {'Success' if plate_data.get('complete', True) else 'Fail'}
MISSING FIELDS: {', '.join(plate_data.get('missing_fields', [])) or '-'}
{'='*60}
"""
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_entry)
    return filename

def rotate_frame(frame, rotation_option):
    if rotation_option == "90° Clockwise":
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation_option == "90° Counter-Clockwise":
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif rotation_option == "180°":
        return cv2.rotate(frame, cv2.ROTATE_180)
    return frame

def resize_to_fit(frame, max_w=750, max_h=550):
    h, w = frame.shape[:2]
    if w <= max_w and h <= max_h:
        return frame
    ratio = min(max_w / w, max_h / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    return cv2.resize(frame, (new_w, new_h))

# =========================================================
# SCROLLABLE FRAME
# =========================================================

class ScrollableFrame(tk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        
        self.canvas = tk.Canvas(self, bg=BG_DARK, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=BG_DARK)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def get_frame(self):
        return self.scrollable_frame

# =========================================================
# MAIN GUI CLASS
# =========================================================

class MyanmarPlateDetector:
    def __init__(self, root):
        self.root = root
        self.root.title("🇲🇲 Myanmar License Plate Detection System")
        self.root.geometry("1300x800")
        self.root.configure(bg=BG_DARK)
        self.root.minsize(1100, 700)
        
        self.main_scroll = ScrollableFrame(self.root)
        self.main_scroll.pack(fill=tk.BOTH, expand=True)
        self.main_frame = self.main_scroll.get_frame()
        
        self.cap = None
        self.running = False
        self.video_source = "webcam"
        self.video_path = None
        self.detect_cooldown = 2.0
        self.last_detect = 0
        
        self.flip_video = tk.BooleanVar(value=False)
        self.rotation_option = tk.StringVar(value="No Rotation")
        
        self.current_image_path = None
        
        self.setup_ui()
        
    def setup_ui(self):
        main_container = tk.Frame(self.main_frame, bg=BG_DARK)
        main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        title_frame = tk.Frame(main_container, bg=BG_MEDIUM, height=70)
        title_frame.pack(fill=tk.X, pady=(0, 15))
        title_frame.pack_propagate(False)
        
        tk.Label(title_frame, text="🇲🇲 MYANMAR LICENSE PLATE DETECTION SYSTEM",
                font=('Arial', 18, 'bold'), bg=BG_MEDIUM, fg=ACCENT).pack(expand=True)
        tk.Label(title_frame, text="Real-time Vehicle & Plate Recognition | Image Support",
                font=('Arial', 9), bg=BG_MEDIUM, fg=TEXT_DIM).pack()
        
        mode_frame = tk.Frame(main_container, bg=BG_MEDIUM)
        mode_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.mode = tk.StringVar(value="live")
        
        live_btn = tk.Button(mode_frame, text="📹 LIVE DETECTION (Video/Webcam)", 
                            command=lambda: self.set_mode("live"),
                            font=('Arial', 10, 'bold'), bg=BG_LIGHT, fg=TEXT_LIGHT,
                            padx=20, pady=5, cursor="hand2")
        live_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        image_btn = tk.Button(mode_frame, text="🖼️ SINGLE IMAGE DETECTION", 
                              command=lambda: self.set_mode("image"),
                              font=('Arial', 10, 'bold'), bg=BG_LIGHT, fg=TEXT_LIGHT,
                              padx=20, pady=5, cursor="hand2")
        image_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # LIVE MODE CONTROLS
        self.live_frame = tk.Frame(main_container, bg=BG_MEDIUM)
        
        row1 = tk.Frame(self.live_frame, bg=BG_MEDIUM)
        row1.pack(fill=tk.X, padx=15, pady=10)
        
        tk.Label(row1, text="📹 VIDEO SOURCE:", font=('Arial', 10, 'bold'),
                bg=BG_MEDIUM, fg=TEXT_LIGHT).pack(side=tk.LEFT, padx=(0, 15))
        
        self.webcam_rb = tk.Radiobutton(row1, text="Webcam", variable=self.video_source,
                                        value="webcam", bg=BG_MEDIUM, fg=TEXT_LIGHT,
                                        selectcolor=BG_MEDIUM, activebackground=BG_MEDIUM)
        self.webcam_rb.pack(side=tk.LEFT, padx=5)
        
        self.file_rb = tk.Radiobutton(row1, text="Video File", variable=self.video_source,
                                      value="file", bg=BG_MEDIUM, fg=TEXT_LIGHT,
                                      selectcolor=BG_MEDIUM, activebackground=BG_MEDIUM)
        self.file_rb.pack(side=tk.LEFT, padx=15)
        
        self.browse_btn = tk.Button(row1, text="📁 Browse", command=self.select_video,
                                   font=('Arial', 9), bg=BG_LIGHT, fg=TEXT_LIGHT,
                                   padx=15, pady=3, cursor="hand2")
        self.browse_btn.pack(side=tk.LEFT, padx=5)
        
        self.file_label = tk.Label(row1, text="No file selected", font=('Arial', 9),
                                   bg=BG_MEDIUM, fg=TEXT_DIM)
        self.file_label.pack(side=tk.LEFT, padx=10)
        
        row2 = tk.Frame(self.live_frame, bg=BG_MEDIUM)
        row2.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        tk.Label(row2, text="🔄 IMAGE SETTINGS:", font=('Arial', 10, 'bold'),
                bg=BG_MEDIUM, fg=TEXT_LIGHT).pack(side=tk.LEFT, padx=(0, 15))
        
        tk.Label(row2, text="Rotation:", bg=BG_MEDIUM, fg=TEXT_DIM).pack(side=tk.LEFT, padx=(0, 5))
        rotate_cb = ttk.Combobox(row2, textvariable=self.rotation_option,
                                 values=["No Rotation", "90° Clockwise", "90° Counter-Clockwise", "180°"],
                                 state="readonly", width=18)
        rotate_cb.pack(side=tk.LEFT, padx=5)
        
        self.flip_cb = tk.Checkbutton(row2, text="🪞 Mirror Image", variable=self.flip_video,
                                      bg=BG_MEDIUM, fg=TEXT_LIGHT, selectcolor=BG_MEDIUM,
                                      activebackground=BG_MEDIUM)
        self.flip_cb.pack(side=tk.LEFT, padx=20)
        
        row3 = tk.Frame(self.live_frame, bg=BG_MEDIUM)
        row3.pack(fill=tk.X, padx=15, pady=(0, 15))
        
        self.start_btn = tk.Button(row3, text="▶ START DETECTION", command=self.start_detection,
                                  font=('Arial', 11, 'bold'), bg=SUCCESS, fg=BG_DARK,
                                  padx=30, pady=8, cursor="hand2")
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = tk.Button(row3, text="⏹ STOP DETECTION", command=self.stop_detection,
                                 font=('Arial', 11, 'bold'), bg=DANGER, fg='white',
                                 padx=30, pady=8, cursor="hand2", state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=15)
        
        # IMAGE MODE CONTROLS
        self.image_frame = tk.Frame(main_container, bg=BG_MEDIUM)
        
        img_row1 = tk.Frame(self.image_frame, bg=BG_MEDIUM)
        img_row1.pack(fill=tk.X, padx=15, pady=10)
        
        self.select_image_btn = tk.Button(img_row1, text="📸 SELECT IMAGE", command=self.select_image_file,
                                         font=('Arial', 11, 'bold'), bg=SUCCESS, fg=BG_DARK,
                                         padx=30, pady=8, cursor="hand2")
        self.select_image_btn.pack(side=tk.LEFT, padx=5)
        
        self.detect_image_btn = tk.Button(img_row1, text="🔍 DETECT PLATE", command=self.detect_single_image,
                                         font=('Arial', 11, 'bold'), bg=ACCENT, fg='white',
                                         padx=30, pady=8, cursor="hand2", state=tk.DISABLED)
        self.detect_image_btn.pack(side=tk.LEFT, padx=15)
        
        self.image_name_label = tk.Label(img_row1, text="No image selected", font=('Arial', 9),
                                         bg=BG_MEDIUM, fg=TEXT_DIM)
        self.image_name_label.pack(side=tk.LEFT, padx=10)
        
        self.image_progress = ttk.Progressbar(self.image_frame, mode='indeterminate', length=300)
        self.image_progress.pack(pady=5)
        
        self.status_label = tk.Label(main_container, text="● READY", font=('Arial', 10, 'bold'),
                                     bg=BG_DARK, fg=SUCCESS)
        self.status_label.pack(fill=tk.X, pady=(0, 10))
        
        content_frame = tk.Frame(main_container, bg=BG_DARK)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        video_frame = tk.LabelFrame(content_frame, text="📷 INPUT FEED",
                                   font=('Arial', 11, 'bold'), bg=BG_MEDIUM,
                                   fg=ACCENT, bd=2, relief=tk.GROOVE)
        video_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.video_label = tk.Label(video_frame, bg=BG_DARK, text="Ready\n\nSelect source and press START",
                                    font=('Arial', 14), fg=TEXT_DIM)
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        right_panel = tk.Frame(content_frame, bg=BG_DARK, width=350)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_panel.pack_propagate(False)
        
        capture_frame = tk.LabelFrame(right_panel, text="📸 LAST CAPTURED PLATE",
                                     font=('Arial', 11, 'bold'), bg=BG_MEDIUM,
                                     fg=ACCENT, bd=2, relief=tk.GROOVE)
        capture_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.capture_img = tk.Label(capture_frame, bg=BG_DARK, text="No capture yet",
                                    font=('Arial', 11), fg=TEXT_DIM)
        self.capture_img.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        info_frame = tk.LabelFrame(right_panel, text="📋 PLATE INFORMATION",
                                  font=('Arial', 11, 'bold'), bg=BG_MEDIUM,
                                  fg=ACCENT, bd=2, relief=tk.GROOVE)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
        info_container = tk.Frame(info_frame, bg=BG_MEDIUM)
        info_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        info_scroll = tk.Scrollbar(info_container, orient=tk.VERTICAL)
        self.info_text = tk.Text(info_container, font=('Consolas', 10), bg=BG_DARK,
                                 fg=SUCCESS, relief=tk.FLAT, height=8,
                                 wrap=tk.WORD, yscrollcommand=info_scroll.set)
        info_scroll.config(command=self.info_text.yview)
        self.info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        info_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        log_frame = tk.LabelFrame(right_panel, text="📋 DETECTION LOG",
                                 font=('Arial', 11, 'bold'), bg=BG_MEDIUM,
                                 fg=ACCENT, bd=2, relief=tk.GROOVE)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        log_container = tk.Frame(log_frame, bg=BG_MEDIUM)
        log_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        log_scroll = tk.Scrollbar(log_container, orient=tk.VERTICAL)
        self.log_text = tk.Text(log_container, font=('Consolas', 9), bg=BG_DARK,
                                fg=TEXT_DIM, relief=tk.FLAT, wrap=tk.WORD,
                                yscrollcommand=log_scroll.set)
        log_scroll.config(command=self.log_text.yview)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        bottom_frame = tk.Frame(main_container, bg=BG_DARK)
        bottom_frame.pack(fill=tk.X, pady=(15, 0))
        
        btn_bg = BG_LIGHT
        
        tk.Button(bottom_frame, text="🗑 CLEAR LOG", command=self.clear_log,
                 font=('Arial', 10, 'bold'), bg=btn_bg, fg=TEXT_LIGHT,
                 padx=20, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=5)
        
        tk.Button(bottom_frame, text="📂 OPEN CAPTURES", command=self.open_folder,
                 font=('Arial', 10, 'bold'), bg=btn_bg, fg=TEXT_LIGHT,
                 padx=20, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=5)
        
        tk.Button(bottom_frame, text="📄 OPEN LOG FILE", command=self.open_log,
                 font=('Arial', 10, 'bold'), bg=btn_bg, fg=TEXT_LIGHT,
                 padx=20, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=5)
        
        car_model_count = len(CAR_MODELS)
        model_status = f"● Car Models Loaded: {car_model_count}" if car_model_count > 0 else "● No car models loaded"
        
        self.status_bar = tk.Label(bottom_frame, text=f"{model_status} | Select mode and source",
                                   font=('Arial', 9), bg=BG_DARK, fg=TEXT_DIM, anchor=tk.W)
        self.status_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=10)
        
        self.set_mode("live")
    
    def set_mode(self, mode):
        self.mode = mode
        if mode == "live":
            self.live_frame.pack(fill=tk.X, pady=(0, 15))
            self.image_frame.pack_forget()
            self.status_bar.config(text="● Live mode | Select source (Webcam/Video) and press START")
        else:
            self.live_frame.pack_forget()
            self.image_frame.pack(fill=tk.X, pady=(0, 15))
            self.status_bar.config(text="● Image mode | Select an image and press DETECT PLATE")
        
        self.stop_detection()
    
    def select_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.webm")])
        if path:
            self.video_path = path
            short_name = os.path.basename(path)[:35]
            self.file_label.config(text=short_name)
            self.video_source = "file"
            self.file_rb.select()
    
    def select_image_file(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp *.tiff")])
        if path:
            self.current_image_path = path
            short_name = os.path.basename(path)[:35]
            self.image_name_label.config(text=short_name)
            self.detect_image_btn.config(state=tk.NORMAL)
            
            img = cv2.imread(path)
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_rgb)
            img_pil.thumbnail((700, 520))
            photo = ImageTk.PhotoImage(img_pil)
            self.video_label.config(image=photo, text='')
            self.video_label.image = photo
    
    def detect_single_image(self):
        if not self.current_image_path:
            messagebox.showerror("Error", "Please select an image first")
            return
        
        self.detect_image_btn.config(state=tk.DISABLED)
        self.select_image_btn.config(state=tk.DISABLED)
        self.image_progress.start()
        self.status_label.config(text="● PROCESSING", fg=WARNING)
        self.status_bar.config(text="● Processing image...")
        
        threading.Thread(target=self._process_single_image, daemon=True).start()
    
    def _process_single_image(self):
        try:
            img = cv2.imread(self.current_image_path)
            if img is None:
                raise Exception("Could not load image")
            
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            results = model(img, conf=0.15, iou=0.45, verbose=False)
            
            bbox = None
            conf = 0
            
            for result in results:
                if result.boxes is not None:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        box_conf = float(box.conf[0])
                        width = x2 - x1
                        height = y2 - y1
                        cls_id = int(box.cls[0])
                        
                        if width > 40 and height > 12 and width < 2000:
                            if cls_id == 1:
                                bbox = (x1, y1, x2, y2)
                                conf = box_conf
                                print(f"[DETECTION] Plate found with confidence: {conf:.2%}")
                                break
                    if bbox:
                        break
            
            if bbox is None:
                self.root.after(0, self._image_detection_error, "No license plate detected!")
                return
            
            x1, y1, x2, y2 = bbox
            
            margin = 5
            x1 = max(0, x1 - margin)
            y1 = max(0, y1 - margin)
            x2 = min(img.shape[1], x2 + margin)
            y2 = min(img.shape[0], y2 + margin)
            
            plate_crop = img[y1:y2, x1:x2].copy()
            
            region, region_conf = read_region_code(plate_crop)
            
            township = ""
            township_conf = 0
            if region:
                township, township_conf = read_township_from_region(plate_crop, region)
            
            main_number, main_conf = read_main_number(plate_crop)
            bottom_text_raw, bottom_conf = read_bottom_text(plate_crop)
            
            color, color_conf = detect_plate_color(plate_crop)
            main_number = normalize_number_for_plate_color(main_number, color)
            
            matched_car_model, match_confidence, _ = match_car_model_fuzzy(bottom_text_raw)
            
            if matched_car_model and match_confidence > 0.3:
                car_model_display = matched_car_model
            else:
                car_model_display = bottom_text_raw
            
            vehicle_type = get_vehicle_type(main_number, color)
            
            if region and township and main_number:
                display = f"{region}-{township} {main_number}".strip()
            elif region and main_number:
                display = f"{region} {main_number}".strip()
            elif main_number:
                display = main_number
            elif bottom_text_raw:
                display = bottom_text_raw
            else:
                display = "?"
            
            plate_data = {
                'region': region,
                'township': township,
                'main_number': main_number,
                'bottom_text_raw': bottom_text_raw,
                'car_model': car_model_display,
                'color': color,
                'vehicle_type': vehicle_type,
                'display': display
            }
            
            saved_path = save_detection(plate_crop, plate_data)
            
            cv2.rectangle(img_rgb, (x1, y1), (x2, y2), (0, 255, 255), 3)
            cv2.putText(img_rgb, display, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(img_rgb, f"{vehicle_type} | {car_model_display}", 
                       (x1, y2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            
            img_pil = Image.fromarray(img_rgb)
            img_pil.thumbnail((700, 520))
            photo = ImageTk.PhotoImage(img_pil)
            
            township_display = township if township else 'Not detected'
            township_conf_display = f"{township_conf:.2%}" if township else "0%"
            
            results_text = f"""
{'='*50}
MYANMAR PLATE DETECTION RESULTS
{'='*50}

✅ Plate detected! (Confidence: {conf:.1%})

📍 REGION: {region if region else 'Not detected'} ({region_conf:.2%})
🏘️ TOWNSHIP: {township_display} ({township_conf_display})
🔢 MAIN NUMBER: {main_number if main_number else 'Not detected'} ({main_conf:.2%})
📝 BOTTOM TEXT (OCR): {bottom_text_raw if bottom_text_raw else 'Not detected'} ({bottom_conf:.2%})
🚗 CAR MODEL (MATCHED): {car_model_display} ({match_confidence:.1%})
🎨 PLATE COLOR: {color.upper()} ({color_conf:.1%})
🚗 VEHICLE TYPE: {vehicle_type}

{'='*50}
📋 FINAL DISPLAY: {display}
💾 SAVED: {os.path.basename(saved_path)}
{'='*50}
"""
            
            self.root.after(0, self._image_detection_success, photo, plate_crop, plate_data, results_text)
            
        except Exception as e:
            import traceback
            self.root.after(0, self._image_detection_error, f"Error: {str(e)}\n{traceback.format_exc()}")
    
    def _image_detection_success(self, photo, plate_crop, plate_data, results_text):
        self.video_label.config(image=photo, text='')
        self.video_label.image = photo
        self.update_captured_display(plate_crop, plate_data)
        self.add_log(f"✅ Image: {plate_data['display']} | {plate_data['vehicle_type']} | {plate_data['car_model']}")
        self.add_log(results_text)
        self.image_progress.stop()
        self.status_label.config(text="● COMPLETE", fg=SUCCESS)
        self.status_bar.config(text=f"● Detected: {plate_data['display']} | Model: {plate_data['car_model']}")
        self.detect_image_btn.config(state=tk.NORMAL)
        self.select_image_btn.config(state=tk.NORMAL)
    
    def _image_detection_error(self, error_msg):
        self.image_progress.stop()
        self.status_label.config(text="● ERROR", fg=DANGER)
        self.status_bar.config(text=f"● Error: {error_msg[:50]}")
        self.detect_image_btn.config(state=tk.NORMAL)
        self.select_image_btn.config(state=tk.NORMAL)
        messagebox.showerror("Detection Error", error_msg)
    
    def open_folder(self):
        os.startfile(os.path.abspath(SAVE_FOLDER))
    
    def open_log(self):
        if os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
        else:
            messagebox.showinfo("Info", "No log file yet")
    
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.capture_img.config(image='', text='No capture yet')
        self.info_text.delete(1.0, tk.END)
        self.status_bar.config(text="● Log cleared")
        self.add_log("Log cleared")
    
    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        for line in str(message).split('\n'):
            if line.strip():
                self.log_text.insert(tk.END, f"[{timestamp}] {line}\n")
        self.log_text.see(tk.END)
    
    def update_info_panel(self, data):
        self.info_text.delete(1.0, tk.END)
        info = f"""
╔════════════════════════════════════════════╗
║         PLATE DETAILS                      ║
╠════════════════════════════════════════════╣
║ REGION       : {data.get('region', 'N/A'):<25} ║
║ TOWNSHIP     : {data.get('township', 'N/A'):<25} ║
║ MAIN NUMBER  : {data.get('main_number', 'N/A'):<25} ║
║ BOTTOM TEXT  : {data.get('bottom_text_raw', 'N/A'):<25} ║
║ CAR MODEL    : {data.get('car_model', 'N/A'):<25} ║
║ COLOR        : {data.get('color', 'N/A'):<25} ║
║ VEHICLE TYPE : {data.get('vehicle_type', 'N/A'):<25} ║
║ DISPLAY      : {data.get('display', 'N/A'):<25} ║
╚════════════════════════════════════════════╝
"""
        self.info_text.insert(1.0, info)
    
    def update_captured_display(self, img, data):
        try:
            h, w = img.shape[:2]
            max_size = 200
            if h > max_size or w > max_size:
                scale = max_size / max(h, w)
                img = cv2.resize(img, (int(w*scale), int(h*scale)))
            
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.capture_img.config(image=photo, text='')
            self.capture_img.image = photo
            self.update_info_panel(data)
        except Exception as e:
            print(f"Display error: {e}")
    
    def start_detection(self):
        if self.running:
            return
        
        if self.mode != "live":
            messagebox.showinfo("Info", "Switch to LIVE mode first")
            return
        
        if self.video_source == "webcam":
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        else:
            if not self.video_path:
                messagebox.showerror("Error", "Please select a video file first")
                return
            self.cap = cv2.VideoCapture(self.video_path)
        
        if not self.cap.isOpened():
            messagebox.showerror("Error", "Cannot open video source")
            return
        
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text="● DETECTING", fg=WARNING)
        self.status_bar.config(text="● Detection active | Auto-saving captures")
        self.add_log("Detection started")
        
        threading.Thread(target=self.process_video, daemon=True).start()
    
    def stop_detection(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text="● STOPPED", fg=DANGER)
        self.status_bar.config(text="● Detection stopped")
        if self.mode == "live":
            self.add_log("Detection stopped")
    
    def process_video(self):
        frame_count = 0
        
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                if self.video_source != "webcam":
                    self.root.after(0, self.stop_detection)
                    self.root.after(0, lambda: self.add_log("Video finished"))
                break
            
            processed = rotate_frame(frame, self.rotation_option.get())
            if self.flip_video.get():
                processed = cv2.flip(processed, 1)
            
            display = resize_to_fit(processed, max_w=700, max_h=520)
            
            frame_count += 1
            current_time = time.time()
            
            if frame_count % 3 == 0:
                small = cv2.resize(processed, (640, 480))
                results = model(small, conf=0.15, iou=0.45, verbose=False)
                
                for result in results:
                    if result.boxes is not None:
                        for box in result.boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                            cls_id = int(box.cls[0])
                            
                            sx = processed.shape[1] / 640
                            sy = processed.shape[0] / 480
                            ox1, oy1 = int(x1 * sx), int(y1 * sy)
                            ox2, oy2 = int(x2 * sx), int(y2 * sy)
                            
                            dsx = display.shape[1] / processed.shape[1]
                            dsy = display.shape[0] / processed.shape[0]
                            dx1, dy1 = int(ox1 * dsx), int(oy1 * dsy)
                            dx2, dy2 = int(ox2 * dsx), int(oy2 * dsy)
                            
                            if cls_id == 0:
                                cv2.rectangle(display, (dx1, dy1), (dx2, dy2), (255, 0, 0), 2)
                                cv2.putText(display, "Car", (dx1, dy1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                            
                            elif cls_id == 1:
                                cv2.rectangle(display, (dx1, dy1), (dx2, dy2), (0, 255, 255), 3)
                                
                                if current_time - self.last_detect >= self.detect_cooldown:
                                    self.last_detect = current_time
                                    plate_crop = processed[oy1:oy2, ox1:ox2].copy()
                                    if plate_crop.size > 0 and plate_crop.shape[0] > 15 and plate_crop.shape[1] > 40:
                                        self.process_plate(plate_crop, display, (dx1, dy1, dx2, dy2))
            
            rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
            img = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.root.after(0, lambda i=img: self.update_video(i))
        
        self.running = False
    
    def process_plate(self, plate_crop, display_frame, bbox):
        px1, py1, px2, py2 = bbox
        
        try:
            region, region_conf = read_region_code(plate_crop)
            
            township = ""
            township_conf = 0
            if region:
                township, township_conf = read_township_from_region(plate_crop, region)
            
            main_number, main_conf = read_main_number(plate_crop)
            bottom_text_raw, bottom_conf = read_bottom_text(plate_crop)
            
            color, color_conf = detect_plate_color(plate_crop)
            main_number = normalize_number_for_plate_color(main_number, color)
            
            matched_car_model, match_confidence, _ = match_car_model_fuzzy(bottom_text_raw)
            
            if matched_car_model and match_confidence > 0.3:
                car_model_display = matched_car_model
            else:
                car_model_display = bottom_text_raw
            
            vehicle_type = get_vehicle_type(main_number, color)
            
            if region and township and main_number:
                display_text = f"{region}-{township} {main_number}".strip()
            elif region and main_number:
                display_text = f"{region} {main_number}".strip()
            elif main_number:
                display_text = main_number
            elif bottom_text_raw:
                display_text = bottom_text_raw
            else:
                display_text = "?"
            
            plate_data = {
                'region': region,
                'township': township,
                'main_number': main_number,
                'bottom_text_raw': bottom_text_raw,
                'car_model': car_model_display,
                'color': color,
                'vehicle_type': vehicle_type,
                'display': display_text
            }
            
            saved_path = save_detection(plate_crop, plate_data)
            
            cv2.rectangle(display_frame, (px1, py1), (px2, py2), (0, 255, 255), 3)
            cv2.putText(display_frame, display_text, (px1, py1-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
            cv2.putText(display_frame, f"{vehicle_type} | {car_model_display}", 
                       (px1, py2+18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            
            self.root.after(0, lambda: self.add_log(f"✅ {display_text} | {vehicle_type} | Model: {car_model_display} | {color}"))
            self.root.after(0, lambda: self.status_bar.config(text=f"● Captured: {display_text} | Model: {car_model_display}"))
            self.root.after(0, lambda: self.update_captured_display(plate_crop, plate_data))
            
        except Exception as e:
            print(f"Plate processing error: {e}")
    
    def update_video(self, photo):
        self.video_label.config(image=photo, text='')
        self.video_label.image = photo
    
    def on_closing(self):
        self.stop_detection()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MyanmarPlateDetector(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
