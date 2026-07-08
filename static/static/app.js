let lastNumber = "";
let currentMode = "webcam";
let streamEnabled = false;
let selectedImageFile = null;
let selectedVideoFile = null;
let eventTotal = 0;
let eventSuccessTotal = 0;
let eventFailTotal = 0;
let detectionInProgress = false;
let imagePreviewUrl = null;
let videoPreviewUrl = null;
let currentUploadController = null;
const seenEventKeys = new Set();
let rawLogEntries = [];
let healthTimer = null;
let dataTimer = null;
let eventsTimer = null;
let eventsPageTimer = null;
let plateSelectionLockedUntil = 0;
const SETTINGS_KEY = "mlpd.settings.v1";
const defaultSettings = {
    theme: "dark",
    accent: "green",
    compact: false,
    refreshInterval: 2000,
    rememberMode: true,
    reduceMotion: false,
    failHighlight: true,
    latestPreview: true
};
let appSettings = { ...defaultSettings };

const $ = id => document.getElementById(id);

function escapeHtml(value) {
    return String(value ?? "-").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    })[char]);
}

function updateClock() {
    const now = new Date();
    $("currentDate").textContent = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    $("currentTime").textContent = now.toLocaleTimeString();
    $("overlayTime").textContent = now.toLocaleTimeString([], { hour12: false });
}

function addLog(time, plate, mode, vehicle, model, status = "Success") {
    $("emptyEvent")?.remove();
    eventTotal += 1;
    if (status === "Success") eventSuccessTotal += 1;
    else eventFailTotal += 1;
    $("eventCount").textContent = `${eventTotal} events`;
    if ($("eventTotalMetric")) $("eventTotalMetric").textContent = eventTotal;
    if ($("eventSuccessMetric")) $("eventSuccessMetric").textContent = eventSuccessTotal;
    if ($("eventFailMetric")) $("eventFailMetric").textContent = eventFailTotal;
    if ($("latestEventTime")) $("latestEventTime").textContent = time;
    if (!$("logTable")) return;
    const normalizedStatus = status === "Success" ? "Success" : "Fail";
    const row = document.createElement("div");
    row.className = `log-row ${normalizedStatus.toLowerCase()}`;
    row.innerHTML = `<span class="trace-id">#${String(eventTotal).padStart(3, "0")}</span><span>${escapeHtml(time)}</span><span>${escapeHtml(mode)}</span><span class="event-status">${normalizedStatus}</span><span>${escapeHtml(plate)}</span><span>${escapeHtml(vehicle)}</span><span>${escapeHtml(model)}</span>`;
    $("logTable").appendChild(row);
}

function loadSettings() {
    try {
        const stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
        appSettings = { ...defaultSettings, ...stored };
    } catch {
        appSettings = { ...defaultSettings };
    }
}

function saveSettings() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(appSettings));
}

function effectiveTheme() {
    if (appSettings.theme !== "system") return appSettings.theme;
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applySettings() {
    document.body.dataset.theme = effectiveTheme();
    document.body.dataset.accent = appSettings.accent;
    document.body.classList.toggle("compact-ui", Boolean(appSettings.compact));
    document.body.classList.toggle("reduce-motion", Boolean(appSettings.reduceMotion));
    document.body.classList.toggle("fail-muted", !appSettings.failHighlight);
    if ($("themeSelect")) $("themeSelect").value = appSettings.theme;
    if ($("accentSelect")) $("accentSelect").value = appSettings.accent;
    if ($("compactToggle")) $("compactToggle").checked = Boolean(appSettings.compact);
    if ($("refreshSelect")) $("refreshSelect").value = String(appSettings.refreshInterval);
    if ($("rememberModeToggle")) $("rememberModeToggle").checked = Boolean(appSettings.rememberMode);
    if ($("reduceMotionToggle")) $("reduceMotionToggle").checked = Boolean(appSettings.reduceMotion);
    if ($("failHighlightToggle")) $("failHighlightToggle").checked = Boolean(appSettings.failHighlight);
    if ($("latestPreviewToggle")) $("latestPreviewToggle").checked = Boolean(appSettings.latestPreview);
}

function readSettingsForm() {
    appSettings = {
        ...appSettings,
        theme: $("themeSelect").value,
        accent: $("accentSelect").value,
        compact: $("compactToggle").checked,
        refreshInterval: Number($("refreshSelect").value || 2000),
        rememberMode: $("rememberModeToggle").checked,
        reduceMotion: $("reduceMotionToggle").checked,
        failHighlight: $("failHighlightToggle").checked,
        latestPreview: $("latestPreviewToggle").checked
    };
}

function showSettingsStatus(message) {
    if (!$("settingsStatus")) return;
    $("settingsStatus").textContent = message;
    window.clearTimeout(showSettingsStatus.timer);
    showSettingsStatus.timer = window.setTimeout(() => {
        if ($("settingsStatus")) $("settingsStatus").textContent = "Settings are saved in this browser.";
    }, 2400);
}

function restartPolling() {
    [healthTimer, dataTimer, eventsTimer, eventsPageTimer].forEach(timer => window.clearInterval(timer));
    const interval = Math.max(1000, Number(appSettings.refreshInterval || 2000));
    healthTimer = window.setInterval(checkHealth, interval);
    dataTimer = window.setInterval(pollData, Math.max(1000, Math.round(interval * 0.75)));
    eventsTimer = window.setInterval(loadEvents, interval);
    eventsPageTimer = window.setInterval(() => { if (!$("eventsView").hidden) loadEventsPage(); }, Math.max(2000, interval));
}

function eventKey(event) {
    return `${event.timestamp || ""}|${event.capture_url || ""}|${event.number || "-"}`;
}

function addEvent(event, fallbackMode = "Detection") {
    const key = eventKey(event);
    if (seenEventKeys.has(key)) return false;
    seenEventKeys.add(key);
    const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    addLog(
        time,
        event.number || "-",
        event.source || fallbackMode,
        event.type || "-",
        displayModel(event),
        event.status || (event.complete ? "Success" : "Fail")
    );
    return true;
}

function formatEventTime(value) {
    if (!value) return "";
    const date = new Date(String(value).replace(" ", "T"));
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString();
}

function displayRegion(data = {}) {
    if (data.region_display && data.region_display !== "-") return data.region_display;
    const region = data.region || "-";
    const township = data.township && data.township !== "-" ? data.township : "";
    if (region === "-") return "-";
    if (township) return `${region}-${township}`;
    return region;
}

function displayTownship(data = {}) {
    const township = data.township && data.township !== "-" ? data.township : "-";
    const townshipName = data.township_name && data.township_name !== "-" ? data.township_name : "";
    return townshipName || township;
}

function displayModel(data = {}) {
    const model = data.model || data.car_model || "-";
    if (!model || model === "-") return "-";
    return model;
}

function updateEventStats(stats = {}) {
    const total = Number(stats.total || 0);
    const success = Number(stats.success || 0);
    const fail = Number(stats.fail || 0);
    eventTotal = total;
    eventSuccessTotal = success;
    eventFailTotal = fail;
    $("eventCount").textContent = `${total} events`;
    if ($("eventTotalMetric")) $("eventTotalMetric").textContent = total;
    if ($("eventSuccessMetric")) $("eventSuccessMetric").textContent = success;
    if ($("eventFailMetric")) $("eventFailMetric").textContent = fail;
    if ($("latestEventTime") && stats.latest?.timestamp) $("latestEventTime").textContent = formatEventTime(stats.latest.timestamp);
    if ($("settingsEventState")) $("settingsEventState").textContent = total;
}

function updatePlateInfo(data) {
    const number = data.number && data.number !== "-" ? data.number : "--- ---";
    $("plateNumber").textContent = number;
    $("infoBox").innerHTML = `
        <div><span>Region</span><strong>${escapeHtml(displayRegion(data))}</strong></div>
        <div><span>Township</span><strong>${escapeHtml(displayTownship(data))}</strong></div>
        <div><span>Color</span><strong>${escapeHtml(data.color)}</strong></div>
        <div><span>Vehicle type</span><strong>${escapeHtml(data.type)}</strong></div>
        <div class="wide"><span>Matched model</span><strong>${escapeHtml(displayModel(data))}</strong></div>`;
    const rawConfidence = Number(data.confidence || 0);
    const confidence = number === "--- ---" ? 0 : Math.round(Math.min(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence, 100));
    $("confidenceValue").textContent = confidence ? `${confidence}%` : "--";
    $("confidenceBar").style.width = `${confidence}%`;
    if (data.capture_url && appSettings.latestPreview) updatePlateImage(data.capture_url);
    if ($("latestEventTime") && data.timestamp) $("latestEventTime").textContent = formatEventTime(data.timestamp);
}

function updatePlateImage(imageUrl) {
    $("plateImage").innerHTML = imageUrl
        ? `<img src="${escapeHtml(imageUrl)}" alt="Last plate capture">`
        : "<span>No plate captured</span>";
}

function clearMultiPlatePanel() {
    if (!$("multiPlatePanel")) return;
    $("multiPlatePanel").hidden = true;
    $("multiPlateList").innerHTML = "";
    $("multiPlateCount").textContent = "0 plates";
    if ($("multiPlateTitle")) $("multiPlateTitle").textContent = "Multi detection";
}

function sortDetectedResults(results = [], mode = "") {
    const items = [...results];
    if (mode === "Image") {
        return items.sort((a, b) => {
            const boxA = Array.isArray(a.image_box) ? a.image_box : [0, 0, 0, 0];
            const boxB = Array.isArray(b.image_box) ? b.image_box : [0, 0, 0, 0];
            return (Number(boxA[1] || 0) - Number(boxB[1] || 0)) || (Number(boxA[0] || 0) - Number(boxB[0] || 0));
        });
    }
    return items.sort((a, b) => Number(a.video_frame || 0) - Number(b.video_frame || 0));
}

function plateTitle(item, index, mode = "") {
    const number = item.number && item.number !== "-" ? item.number : "Unread";
    if (mode === "Video" && item.video_frame !== undefined) {
        return `Plate ${index + 1} - Frame ${item.video_frame} - ${number}`;
    }
    return `Plate ${index + 1} - ${number}`;
}

function latestPreviewLocked() {
    return Date.now() < plateSelectionLockedUntil;
}

function selectPlateResult(item, index) {
    plateSelectionLockedUntil = Date.now() + 60000;
    updatePlateInfo(item);
    if (item.capture_url && appSettings.latestPreview) updatePlateImage(item.capture_url);
    setResultState(item.status || (item.number && item.number !== "-" ? "Success" : "Fail"));
    document.querySelectorAll(".plate-thumb-card").forEach((card, cardIndex) => {
        card.classList.toggle("active", cardIndex === index);
    });
}

function renderMultiPlateAccordion(results = [], mode = "") {
    if (!$("multiPlatePanel")) return;
    if (results.length <= 1) {
        clearMultiPlatePanel();
        return;
    }
    $("multiPlatePanel").hidden = false;
    if ($("multiPlateTitle")) $("multiPlateTitle").textContent = mode === "Video" ? "Video multi detection" : "Image multi detection";
    $("multiPlateCount").textContent = `${results.length} plates`;
    $("multiPlateList").innerHTML = results.map((item, index) => {
        const number = item.number && item.number !== "-" ? item.number : "--- ---";
        const confidence = Math.round(Math.min(Number(item.confidence || 0) <= 1 ? Number(item.confidence || 0) * 100 : Number(item.confidence || 0), 100));
        const status = item.status || (number === "--- ---" ? "Fail" : "Success");
        const badge = mode === "Video" && item.video_frame !== undefined ? `Frame ${item.video_frame}` : `Plate ${index + 1}`;
        const meta = mode === "Video" && item.video_frame !== undefined
            ? `${confidence ? `${confidence}%` : "--"} / ${escapeHtml(item.color)} / frame ${escapeHtml(item.video_frame)}`
            : `${confidence ? `${confidence}%` : "--"} / ${escapeHtml(item.color)}`;
        return `
            <button class="plate-thumb-card ${index === 0 ? "active" : ""} ${status === "Success" ? "success" : "fail"}" type="button" data-plate-index="${index}" title="${escapeHtml(plateTitle(item, index, mode))}">
                <span class="plate-thumb-badge">${escapeHtml(badge)}</span>
                <span class="plate-thumb-image">
                    ${item.capture_url ? `<img src="${escapeHtml(item.capture_url)}" alt="Plate ${index + 1} capture">` : "<em>No crop</em>"}
                </span>
                <strong>${escapeHtml(number)}</strong>
                <small>${meta}</small>
            </button>`;
    }).join("");
    document.querySelectorAll(".plate-thumb-card").forEach(button => {
        button.addEventListener("click", event => {
            event.preventDefault();
            const index = Number(button.dataset.plateIndex || 0);
            selectPlateResult(results[index], index);
        });
    });
}

function showStatus(message, tone = "") {
    $("feedStatus").textContent = message;
    $("feedStatus").classList.toggle("error-text", tone === "error");
}

function setResultState(status = "") {
    const failed = status === "Fail";
    $("feedPreview").classList.toggle("error", failed && appSettings.failHighlight);
    $("plateNumber").classList.toggle("error", failed && appSettings.failHighlight);
    $("infoBox").classList.toggle("error", failed && appSettings.failHighlight);
}

function updateDetectButtonState() {
    const fileSelected = currentMode === "video" ? Boolean(selectedVideoFile) : Boolean(selectedImageFile);
    $("detectBtn").disabled = detectionInProgress || !fileSelected;
    $("detectBtn").textContent = detectionInProgress ? "Detecting..." : "Run detection";
    $("stopBtn").disabled = ["video", "image"].includes(currentMode) ? !detectionInProgress : false;
}

function getOrientationSettings() {
    return {
        rotation: $("rotationSelect").value,
        mirror: $("mirrorCheckbox").checked
    };
}

function orientationTransform() {
    const rotation = $("rotationSelect").value;
    const transforms = [];
    if (rotation === "90cw") transforms.push("rotate(90deg)");
    else if (rotation === "90ccw") transforms.push("rotate(-90deg)");
    else if (rotation === "180") transforms.push("rotate(180deg)");
    if ($("mirrorCheckbox").checked) transforms.push("scaleX(-1)");
    return transforms.join(" ") || "none";
}

function applyOrientationPreview() {
    const transform = orientationTransform();
    ["imagePreview", "videoPreview"].forEach(id => {
        $(id).style.transform = transform;
    });
}

function applyCameraOrientation() {
    applyOrientationPreview();
    if (!streamEnabled || !["webcam", "camera"].includes(currentMode)) return;
    cameraRequest("/camera/settings", 0, "Orientation").then(data => {
        showStatus(data.message);
    }).catch(error => showStatus(error.message || "Unable to apply rotation settings", "error"));
}

function setDetectionBusy(active) {
    detectionInProgress = active;
    $("feedPreview").classList.toggle("active", active || streamEnabled);
    updateDetectButtonState();
}

function setAppView(view) {
    const normalizedView = ["captures", "events", "settings"].includes(view) ? view : "live";
    const isCaptures = normalizedView === "captures";
    const isEvents = normalizedView === "events";
    const isSettings = normalizedView === "settings";
    $("liveView").hidden = isCaptures || isEvents || isSettings;
    $("capturesView").hidden = !isCaptures;
    $("eventsView").hidden = !isEvents;
    $("settingsView").hidden = !isSettings;
    document.querySelectorAll(".nav-item[data-view]").forEach(item => {
        item.classList.toggle("active", item.dataset.view === normalizedView);
    });
    if (isCaptures) loadCaptures();
    if (isEvents) loadEventsPage();
    if (isSettings) updateSettingsSummary();
}

function setMode(mode) {
    currentMode = mode;
    if (appSettings.rememberMode) {
        localStorage.setItem("mlpd.lastMode", mode);
    }
    ["Webcam", "Video", "Image", "Camera"].forEach(name => $("tab" + name).classList.toggle("active", mode === name.toLowerCase()));
    $("videoControls").style.display = mode === "video" ? "flex" : "none";
    $("imageControls").style.display = mode === "image" ? "flex" : "none";
    $("cameraControls").style.display = mode === "camera" ? "flex" : "none";
    $("settingsBox").style.display = "flex";
    $("startBtn").style.display = mode === "webcam" ? "inline-block" : "none";
    $("stopBtn").style.display = ["webcam", "video", "image"].includes(mode) ? "inline-block" : "none";
    $("detectBtn").style.display = ["video", "image"].includes(mode) ? "inline-block" : "none";
    $("connectCameraBtn").style.display = mode === "camera" ? "inline-block" : "none";
    $("disconnectCameraBtn").style.display = mode === "camera" ? "inline-block" : "none";

    const labels = {
        webcam: ["Front Gate", "Camera standing by"],
        video: ["Video Review", "Choose a video to begin"],
        image: ["Image File", "Choose an image to begin"],
        camera: ["Network Camera", "Enter a network camera URL"]
    };
    $("feedTitle").textContent = labels[mode][0];
    showStatus(labels[mode][1]);
    if (mode !== "webcam") setLiveStream(false);
    $("imagePreview").style.display = mode === "image" && selectedImageFile ? "block" : "none";
    $("videoPreview").style.display = mode === "video" && selectedVideoFile ? "block" : "none";
    if ((mode === "image" && selectedImageFile) || (mode === "video" && selectedVideoFile)) $("placeholderBox").style.display = "none";
    updateDetectButtonState();
}

function setLiveStream(active) {
    if (active) {
        $("videoFeed").src = `/video_feed?t=${Date.now()}`;
        $("videoFeed").style.display = "block";
        $("imagePreview").style.display = "none";
        $("videoPreview").style.display = "none";
        $("videoPreview").pause();
        $("placeholderBox").style.display = "none";
        $("feedPreview").classList.add("active");
        $("cameraStatus").textContent = "Live";
        $("cameraStatusIcon").classList.add("online");
        streamEnabled = true;
    } else {
        $("videoFeed").src = "";
        $("videoFeed").style.display = "none";
        if (!((currentMode === "image" && selectedImageFile) || (currentMode === "video" && selectedVideoFile))) $("placeholderBox").style.display = "grid";
        $("feedPreview").classList.remove("active");
        $("cameraStatus").textContent = "Standby";
        $("cameraStatusIcon").classList.remove("online");
        streamEnabled = false;
    }
}

function cameraRequest(path, source, label) {
    const orientation = getOrientationSettings();
    return fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, label, ...orientation })
    }).then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "Camera request failed");
        return data;
    });
}

function uploadFile(path, fieldName, file, signal) {
    const data = new FormData();
    data.append(fieldName, file);
    data.append("rotation", $("rotationSelect").value);
    data.append("mirror", $("mirrorCheckbox").checked ? "true" : "false");
    showStatus(`Analyzing ${file.name}...`);
    return fetch(path, { method: "POST", body: data, signal }).then(async response => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.message || `Detection request failed (${response.status})`);
        return result;
    });
}

function handleUploadResult(data, mode) {
    plateSelectionLockedUntil = 0;
    const result = data.result || {};
    const detectedResults = Array.isArray(data.results) && data.results.length
        ? sortDetectedResults(data.results, mode)
        : (data.result ? [result] : []);
    const addDetectedResults = () => detectedResults.forEach(item => addEvent(item, mode));
    clearMultiPlatePanel();
    if (!data.success) {
        if (data.result) {
            updatePlateInfo(result);
            if (data.capture_url && appSettings.latestPreview) updatePlateImage(data.capture_url);
            if (["Image", "Video"].includes(mode) && detectedResults.length > 1) renderMultiPlateAccordion(detectedResults, mode);
            addDetectedResults();
            lastNumber = result.number || lastNumber;
        }
        setResultState("Fail");
        showStatus(data.message || "Detection failed", "error");
        return;
    }
    const selectedResult = ["Image", "Video"].includes(mode) && detectedResults.length > 1 ? detectedResults[0] : result;
    updatePlateInfo(selectedResult);
    if (selectedResult.capture_url && appSettings.latestPreview) updatePlateImage(selectedResult.capture_url);
    else if (data.capture_url && appSettings.latestPreview) updatePlateImage(data.capture_url);
    if (["Image", "Video"].includes(mode) && detectedResults.length > 1) renderMultiPlateAccordion(detectedResults, mode);
    addDetectedResults();
    lastNumber = selectedResult.number || result.number || lastNumber;
    setResultState("Success");
    showStatus(data.message || "Detection complete");
}

function detectCurrentFile() {
    const file = currentMode === "video" ? selectedVideoFile : selectedImageFile;
    if (!file) return showStatus(`Choose an ${currentMode === "video" ? "video" : "image"} first`);
    if (detectionInProgress) return;
    const mode = currentMode;
    currentUploadController = new AbortController();
    setDetectionBusy(true);
    showStatus(`Detecting plate in ${file.name} with MLPD + PaddleOCR...`);
    uploadFile(currentMode === "video" ? "/upload_video" : "/upload_image", currentMode, file, currentUploadController.signal)
        .then(data => handleUploadResult(data, mode === "video" ? "Video" : "Image"))
        .catch(error => {
            if (error.name === "AbortError") showStatus("Detection stopped");
            else { setResultState("Fail"); showStatus(error.message || "Upload failed", "error"); }
        })
        .finally(() => { currentUploadController = null; setDetectionBusy(false); });
}

function attachEvents() {
    document.querySelectorAll(".nav-item[data-view]").forEach(item => item.addEventListener("click", () => setAppView(item.dataset.view)));
    ["Webcam", "Video", "Image", "Camera"].forEach(name => $("tab" + name).addEventListener("click", () => setMode(name.toLowerCase())));
    $("startBtn").addEventListener("click", () => {
        showStatus("Connecting local camera...");
        cameraRequest("/camera/start", 0, "Live Camera").then(data => {
            setLiveStream(true); showStatus(data.message);
        }).catch(error => { setLiveStream(false); showStatus(error.message); });
    });
    $("stopBtn").addEventListener("click", () => {
        if (["video", "image"].includes(currentMode)) {
            if (currentUploadController) currentUploadController.abort();
            else showStatus("No file detection is running");
            return;
        }
        cameraRequest("/camera/stop", 0, "Live Camera").then(data => {
            setLiveStream(false); showStatus(data.message);
        }).catch(error => showStatus(error.message));
    });
    $("uploadVideoBtn").addEventListener("click", () => {
        $("videoInput").value = "";
        $("videoInput").click();
    });
    $("uploadImageBtn").addEventListener("click", () => {
        $("imageInput").value = "";
        $("imageInput").click();
    });
    $("detectBtn").addEventListener("click", detectCurrentFile);
    $("rotationSelect").addEventListener("change", applyCameraOrientation);
    $("mirrorCheckbox").addEventListener("change", applyCameraOrientation);
    $("resetOrientationBtn").addEventListener("click", () => {
        $("rotationSelect").value = "none";
        $("mirrorCheckbox").checked = false;
        applyCameraOrientation();
        showStatus("Orientation reset");
    });
    $("connectCameraBtn").addEventListener("click", () => {
        const url = $("cameraUrl").value.trim();
        if (!url) return showStatus("Enter a camera URL first");
        showStatus("Connecting network camera...");
        cameraRequest("/camera/start", url, "Network Camera").then(data => {
            setLiveStream(true); showStatus(data.message);
        }).catch(error => { setLiveStream(false); showStatus(error.message); });
    });
    $("disconnectCameraBtn").addEventListener("click", () => {
        showStatus("Disconnecting network camera...");
        cameraRequest("/camera/stop", 0, "Network Camera").then(data => {
            setLiveStream(false); showStatus(data.message);
        }).catch(error => showStatus(error.message));
    });
    $("openCapturesBtn2").addEventListener("click", () => setAppView("captures"));
    $("refreshCapturesBtn").addEventListener("click", loadCaptures);
    $("refreshEventsBtn").addEventListener("click", loadEventsPage);
    $("openLogsBtn2").addEventListener("click", () => setAppView("events"));
    $("saveSettingsBtn").addEventListener("click", () => {
        readSettingsForm();
        saveSettings();
        applySettings();
        restartPolling();
        if (appSettings.rememberMode) localStorage.setItem("mlpd.lastMode", currentMode);
        showSettingsStatus("Settings applied.");
    });
    $("resetSettingsBtn").addEventListener("click", () => {
        appSettings = { ...defaultSettings };
        saveSettings();
        applySettings();
        restartPolling();
        showSettingsStatus("Settings reset to defaults.");
    });
    ["themeSelect", "accentSelect", "compactToggle", "refreshSelect", "rememberModeToggle", "reduceMotionToggle", "failHighlightToggle", "latestPreviewToggle"].forEach(id => {
        $(id).addEventListener("change", () => {
            readSettingsForm();
            saveSettings();
            applySettings();
            if (id === "refreshSelect") restartPolling();
        });
    });
    $("closeLogModalBtn").addEventListener("click", closeLogDetail);
    $("logDetailModal").addEventListener("click", event => { if (event.target.id === "logDetailModal") closeLogDetail(); });
    window.addEventListener("keydown", event => { if (event.key === "Escape" && !$("logDetailModal").hidden) closeLogDetail(); });
    $("clearLogsBtn")?.addEventListener("click", () => fetch("/clear_logs", { method: "POST" }).then(() => {
        document.querySelectorAll(".log-row:not(.header)").forEach(row => row.remove());
        if ($("logTable") && !$("emptyEvent")) $("logTable").insertAdjacentHTML("beforeend", '<div class="empty-event" id="emptyEvent">Event log cleared. Monitoring is active.</div>');
        seenEventKeys.clear(); eventTotal = 0; eventSuccessTotal = 0; eventFailTotal = 0;
        $("eventCount").textContent = "0 events";
        if ($("eventTotalMetric")) $("eventTotalMetric").textContent = "0";
        if ($("eventSuccessMetric")) $("eventSuccessMetric").textContent = "0";
        if ($("eventFailMetric")) $("eventFailMetric").textContent = "0";
        showStatus("Event log cleared");
    }));
    $("imageInput").addEventListener("change", event => {
        selectedImageFile = event.target.files[0];
        if (!selectedImageFile) return;
        $("imageFileName").textContent = selectedImageFile.name;
        if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
        imagePreviewUrl = URL.createObjectURL(selectedImageFile);
        $("imagePreview").src = imagePreviewUrl;
        $("imagePreview").style.display = "block";
        $("videoPreview").style.display = "none";
        $("placeholderBox").style.display = "none";
        applyOrientationPreview();
        setResultState();
        showStatus("Image ready for detection");
        updateDetectButtonState();
    });
    $("videoInput").addEventListener("change", event => {
        selectedVideoFile = event.target.files[0];
        if (!selectedVideoFile) return;
        $("videoFileName").textContent = selectedVideoFile.name;
        if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
        videoPreviewUrl = URL.createObjectURL(selectedVideoFile);
        $("videoPreview").src = videoPreviewUrl;
        $("videoPreview").style.display = "block";
        $("imagePreview").style.display = "none";
        $("placeholderBox").style.display = "none";
        applyOrientationPreview();
        setResultState();
        showStatus("Video ready for detection");
        updateDetectButtonState();
    });
}

function checkHealth() {
    fetch("/health").then(response => response.json()).then(data => {
        $("sidebarHealthTitle").textContent = "System Online";
        $("sidebarHealth").textContent = `${data.engine} / ${data.camera_ready ? "Camera connected" : "Services ready"}`;
        $("sidebarHealthDot").classList.remove("offline");
        $("serverStatusText").textContent = "Online";
        $("serverStatusIcon").classList.add("online");
        $("ocrStatus").textContent = data.ocr_engine || "Unavailable";
        $("cameraStatus").textContent = data.camera_ready ? "Connected" : "Standby";
        $("cameraStatusIcon").classList.toggle("online", data.camera_ready);
        $("trackingCount").textContent = `${data.active_tracks || 0} tracks / ${data.recognized_tracks || 0} read`;
        if ($("settingsBackendState")) $("settingsBackendState").textContent = "Online";
        if ($("settingsOcrState")) $("settingsOcrState").textContent = data.ocr_engine || "Unavailable";
        if ($("settingsCameraState")) $("settingsCameraState").textContent = data.camera_ready ? "Connected" : "Standby";
        if (data.detection_status && streamEnabled) showStatus(data.detection_status);
    }).catch(() => {
        $("sidebarHealthTitle").textContent = "System Offline";
        $("sidebarHealth").textContent = "Connection lost";
        $("sidebarHealthDot").classList.add("offline");
        $("serverStatusText").textContent = "Offline";
        $("serverStatusIcon").classList.remove("online");
        $("cameraStatus").textContent = "Offline";
        $("cameraStatusIcon").classList.remove("online");
        $("trackingCount").textContent = "0 tracks / 0 read";
        if ($("settingsBackendState")) $("settingsBackendState").textContent = "Offline";
        if ($("settingsOcrState")) $("settingsOcrState").textContent = "-";
        if ($("settingsCameraState")) $("settingsCameraState").textContent = "Offline";
    });
}

function updateSettingsSummary() {
    $("settingsEventState").textContent = eventTotal;
    $("settingsCameraState").textContent = $("cameraStatus").textContent || "Standby";
    $("settingsBackendState").textContent = $("serverStatusText").textContent || "Checking";
    $("settingsOcrState").textContent = $("ocrStatus").textContent || "-";
}

function pollData() {
    fetch("/data").then(response => response.json()).then(data => {
        if (latestPreviewLocked()) return;
        updatePlateInfo(data);
        if (!detectionInProgress && data.number && data.number !== "-" && data.number !== lastNumber) {
            const status = data.status || (data.complete ? "Success" : "Fail");
            setResultState(status);
            lastNumber = data.number;
        }
    }).catch(() => {});
}

function loadEvents() {
    fetch("/events?limit=20").then(response => response.json()).then(data => {
        const events = [...(data.events || [])].reverse();
        events.forEach(event => addEvent(event));
        if (data.stats) updateEventStats(data.stats);
        if (events.length && !latestPreviewLocked()) {
            const latest = events[events.length - 1];
            lastNumber = latest.number || "";
            updatePlateInfo(latest);
            setResultState(latest.status || (latest.complete ? "Success" : "Fail"));
        }
    }).catch(() => {});
}

function renderEventsPage(logs, stats = null) {
    rawLogEntries = logs;
    const total = stats ? Number(stats.total || 0) : logs.length;
    const success = stats ? Number(stats.success || 0) : logs.filter(event => event.status === "Success").length;
    const fail = stats ? Number(stats.fail || 0) : total - success;
    $("eventsPageCount").textContent = `${total} events`;
    $("eventsPageTotalMetric").textContent = total;
    $("eventsPageSuccessMetric").textContent = success;
    $("eventsPageFailMetric").textContent = fail;
    if (stats) updateEventStats(stats);
    if (!logs.length) {
        $("eventsConsole").innerHTML = `
            <div class="capture-empty">
                <strong>No raw logs yet</strong>
                <span>Saved detection log entries will appear here automatically.</span>
            </div>`;
        return;
    }
    $("eventsConsole").innerHTML = `
        <div class="raw-log-list">
            <div class="raw-log-row header"><span>#</span><span>Time</span><span>Status</span><span>Plate</span><span>Region</span><span>Type</span><span>Model</span></div>
            ${logs.map((event, index) => {
        const status = event.status === "Success" ? "Success" : "Fail";
        const time = event.time || "-";
        const rowNumber = total - index;
        return `
            <button class="raw-log-row ${status.toLowerCase()}" data-log-index="${index}">
                <span class="trace-id">#${String(rowNumber).padStart(4, "0")}</span>
                <span>${escapeHtml(time)}</span>
                <span class="event-status">${status}</span>
                <span class="raw-plate">${escapeHtml(event.number || "-")}</span>
                <span>${escapeHtml(displayRegion(event))}</span>
                <span>${escapeHtml(event.type || "-")}</span>
                <span>${escapeHtml(displayModel(event))}</span>
            </button>`;
    }).join("")}
        </div>`;
    document.querySelectorAll(".raw-log-row[data-log-index]").forEach(row => {
        row.addEventListener("click", () => openLogDetail(Number(row.dataset.logIndex)));
    });
}

function openLogDetail(index) {
    const entry = rawLogEntries[index];
    if (!entry) return;
    const status = entry.status === "Success" ? "Success" : "Fail";
    $("logDetailTitle").textContent = entry.number || "Detection Log";
    $("logDetailBody").innerHTML = `
        <div class="log-detail-top ${status.toLowerCase()}">
            <div><span class="trace-id">#${String(rawLogEntries.length - index).padStart(4, "0")}</span><strong>${escapeHtml(entry.number || "-")}</strong></div>
            <span class="event-status">${status}</span>
        </div>
        <div class="log-detail-layout">
            <div class="log-detail-image">
                ${entry.capture_url ? `<img src="${escapeHtml(entry.capture_url)}" alt="Plate capture">` : "<span>No capture image</span>"}
            </div>
            <div class="log-detail-grid">
                ${[
                    ["Time", entry.time],
                    ["File", entry.file],
                    ["Region", displayRegion(entry)],
                    ["Township", displayTownship(entry)],
                    ["Plate Number", entry.number],
                    ["Bottom OCR", entry.bottom_text_ocr || entry.bottom_text_raw],
                    ["Car Model", displayModel(entry)],
                    ["Color", entry.color],
                    ["Vehicle Type", entry.type],
                    ["Display", entry.display],
                    ["Missing Fields", entry.missing_fields],
                ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></div>`).join("")}
            </div>
        </div>
        ${entry.capture_url ? `<a class="event-console-link" href="${escapeHtml(entry.capture_url)}" target="_blank">Open capture image</a>` : ""}`;
    $("logDetailModal").hidden = false;
}

function closeLogDetail() {
    $("logDetailModal").hidden = true;
}

function loadEventsPage() {
    $("refreshEventsBtn").disabled = true;
    return fetch(`/log_entries?limit=200&t=${Date.now()}`).then(response => response.json()).then(data => {
        renderEventsPage(data.logs || [], data.stats || null);
    }).catch(() => {
        $("eventsConsole").innerHTML = `
            <div class="capture-empty">
                <strong>Unable to load raw logs</strong>
                <span>Please check the server connection.</span>
            </div>`;
    }).finally(() => {
        $("refreshEventsBtn").disabled = false;
    });
}

function renderCaptures(captures) {
    $("captureCount").textContent = `${captures.length} images`;
    if (!captures.length) {
        $("captureGallery").innerHTML = `
            <div class="capture-empty">
                <strong>No plate captures yet</strong>
                <span>Detected plate crops will appear here automatically.</span>
            </div>`;
        return;
    }
    $("captureGallery").innerHTML = captures.map(item => `
        <article class="capture-card">
            <a class="capture-image" href="${escapeHtml(item.url)}" target="_blank">
                <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.name)}" loading="lazy">
                <span>Open full image</span>
            </a>
            <div class="capture-meta">
                <strong>${escapeHtml(item.name)}</strong>
                <div><span>${escapeHtml(item.captured_at)}</span><span>${escapeHtml(item.size_kb)} KB</span></div>
            </div>
        </article>`).join("");
}

function loadCaptures() {
    return fetch("/captures_data").then(response => response.json()).then(data => {
        renderCaptures(data.captures || []);
    }).catch(() => {
        $("captureGallery").innerHTML = `
            <div class="capture-empty">
                <strong>Unable to load captures</strong>
                <span>Please check the server connection.</span>
            </div>`;
    });
}

window.addEventListener("DOMContentLoaded", () => {
    loadSettings();
    applySettings();
    attachEvents();
    updateClock();
    setInterval(updateClock, 1000);
    const savedMode = appSettings.rememberMode ? localStorage.getItem("mlpd.lastMode") : null;
    setMode(["webcam", "video", "image", "camera"].includes(savedMode) ? savedMode : "webcam");
    setAppView("live");
    updatePlateInfo({});
    checkHealth();
    loadEvents();
    restartPolling();
});
