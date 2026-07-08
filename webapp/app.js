// WFM Ponto Seguro — cliente mobile-first. Consome a API FastAPI.
// Servido em /app (mesma origem) ou aponte API_BASE para o backend.
const API_BASE = location.pathname.startsWith("/app") ? "" : "http://localhost:8000";

let token = null;
let stream = null;
let lastPos = null;
let faceLandmarker = null;
let busy = false;

const $ = (id) => document.getElementById(id);
const authHeaders = () => ({ Authorization: `Bearer ${token}` });

function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}
function setResult(kind, html) {
  const r = $("result");
  r.className = "result " + kind;
  r.innerHTML = html;
  r.classList.remove("hidden");
}

// ---------- Localização ----------
function watchLocation() {
  if (!navigator.geolocation) { $("geo").className = "geo err"; $("geo").innerHTML = '<span class="dot"></span> GPS indisponível'; return; }
  navigator.geolocation.watchPosition(
    (pos) => {
      lastPos = pos.coords;
      $("geo").className = "geo ok";
      $("geo").innerHTML =
        `<span class="dot"></span> ${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)} · ±${Math.round(pos.coords.accuracy)} m`;
    },
    (err) => { $("geo").className = "geo err"; $("geo").innerHTML = `<span class="dot"></span> ${err.message}`; },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
  );
}

// ---------- Câmera ----------
async function startCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    $("video").srcObject = stream;
  } catch (e) { toast("Câmera negada: " + e.message); }
}
function captureSelfie() {
  const v = $("video"), c = $("canvas");
  c.width = v.videoWidth || 480; c.height = v.videoHeight || 640;
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
}

// ---------- MediaPipe: liveness ativa ----------
async function ensureLandmarker() {
  if (faceLandmarker) return faceLandmarker;
  const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18");
  const fileset = await vision.FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm");
  faceLandmarker = await vision.FaceLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" },
    outputFaceBlendshapes: true, numFaces: 1, runningMode: "VIDEO",
  });
  return faceLandmarker;
}
const bs = (r, n) => r.faceBlendshapes?.[0]?.categories?.find((c) => c.categoryName === n)?.score ?? 0;
function estimateYaw(r) {
  const lm = r.faceLandmarks?.[0]; if (!lm) return 0;
  const nose = lm[1], right = lm[234], left = lm[454];
  const mid = (left.x + right.x) / 2, half = Math.abs(right.x - left.x) / 2 || 1e-6;
  return ((nose.x - mid) / half) * 60;
}
async function runChallenge(actions, windowSeconds) {
  await ensureLandmarker();
  const labels = { blink: "pisque os olhos", turn_left: "vire à esquerda", turn_right: "vire à direita", smile: "sorria" };
  const overlay = $("challengeOverlay");
  overlay.classList.remove("hidden");
  const ev = { max_blink: 0, min_yaw: 0, max_yaw: 0, max_smile: 0 };
  const video = $("video");
  const endAt = performance.now() + Math.min(windowSeconds, 10) * 1000;
  const seq = actions.map((a) => labels[a] || a).join(" → ");
  await new Promise((resolve) => {
    (function tick() {
      if (performance.now() >= endAt) return resolve();
      const r = faceLandmarker.detectForVideo(video, performance.now());
      if (r.faceLandmarks?.length) {
        ev.max_blink = Math.max(ev.max_blink, bs(r, "eyeBlinkLeft"), bs(r, "eyeBlinkRight"));
        ev.max_smile = Math.max(ev.max_smile, (bs(r, "mouthSmileLeft") + bs(r, "mouthSmileRight")) / 2);
        const y = estimateYaw(r); ev.min_yaw = Math.min(ev.min_yaw, y); ev.max_yaw = Math.max(ev.max_yaw, y);
      }
      $("challengeMsg").textContent = seq;
      $("challengeTimer").textContent = `${Math.ceil((endAt - performance.now()) / 1000)}s`;
      requestAnimationFrame(tick);
    })();
  });
  overlay.classList.add("hidden");
  return ev;
}

// ---------- Login ----------
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("loginBtn"); btn.disabled = true; btn.textContent = "Entrando…";
  try {
    const body = new URLSearchParams({ username: $("email").value, password: $("password").value });
    const r = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
    if (!r.ok) { $("loginMsg").textContent = "Credenciais inválidas"; return; }
    token = (await r.json()).access_token;
    const me = await (await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders() })).json();
    $("userName").textContent = me.name;
    $("userRole").textContent = me.role;
    $("avatar").textContent = (me.name[0] || "?").toUpperCase();
    window.CFG = await (await fetch(`${API_BASE}/api/config`)).json();
    $("loginView").classList.add("hidden");
    $("appView").classList.remove("hidden");
    await loadSites(); await startCamera(); watchLocation(); startDeadmanPolling();
  } catch (err) { $("loginMsg").textContent = "Erro de conexão"; }
  finally { btn.disabled = false; btn.textContent = "Entrar"; }
});
$("logoutBtn").onclick = () => location.reload();

async function loadSites() {
  const sites = await (await fetch(`${API_BASE}/api/sites`, { headers: authHeaders() })).json();
  $("siteSelect").innerHTML = sites.map((s) => `<option value="${s.id}">${s.name} · raio ${s.radius_m} m</option>`).join("");
}

// ---------- Check-in / Check-out ----------
async function submitCheck(type) {
  if (busy) return;
  if (!lastPos) { toast("Aguardando GPS…"); return; }
  busy = true;
  const cin = $("checkinBtn"), cout = $("checkoutBtn");
  cin.disabled = cout.disabled = true;
  try {
    // 1) desafio de prova de vida (só se o servidor exigir)
    let nonce = null, evidence = null;
    if (window.CFG?.require_liveness_challenge) {
      try {
        const ch = await (await fetch(`${API_BASE}/api/checkin/challenge`, { method: "POST", headers: authHeaders() })).json();
        nonce = ch.nonce;
        evidence = await runChallenge(ch.actions, ch.window_seconds);
      } catch (e) { setResult("bad", "❌ Prova de vida indisponível: " + e.message); return; }
    }

    // 2) selfie + envio
    setResult("info", "⏳ Validando…");
    const selfie = await captureSelfie();
    const fd = new FormData();
    fd.append("site_id", $("siteSelect").value);
    fd.append("type", type);
    fd.append("latitude", lastPos.latitude);
    fd.append("longitude", lastPos.longitude);
    fd.append("accuracy_m", lastPos.accuracy ?? "");
    fd.append("client_timestamp", new Date().toISOString());
    fd.append("is_mock_location", "false");
    fd.append("is_rooted", "false");
    fd.append("device_info", navigator.userAgent.slice(0, 200));
    if (nonce) fd.append("challenge_nonce", nonce);
    if (evidence) fd.append("challenge_evidence", JSON.stringify(evidence));
    fd.append("selfie", selfie, "selfie.jpg");
    const r = await fetch(`${API_BASE}/api/checkin`, { method: "POST", headers: authHeaders(), body: fd });
    const data = await r.json();
    if (data.status === "approved") {
      setResult("ok", `✅ <b>${type === "checkin" ? "Check-in" : "Check-out"} aprovado</b><br>${Math.round(data.distance_m)} m do posto · liveness ${data.liveness_score?.toFixed(2)} · match ${data.face_match_score?.toFixed(2)}`);
      toast("Registrado ✓");
    } else {
      setResult("bad", `❌ <b>Rejeitado</b><br>${data.reason || data.detail || "erro"}`);
    }
  } finally { busy = false; cin.disabled = cout.disabled = false; }
}
$("checkinBtn").onclick = () => submitCheck("checkin");
$("checkoutBtn").onclick = () => submitCheck("checkout");

// ---------- Pânico ----------
$("panicBtn").onclick = async () => {
  if (!lastPos) { toast("Sem localização ainda."); return; }
  if (!confirm("Enviar alerta de PÂNICO para a central?")) return;
  await fetch(`${API_BASE}/api/panic`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: lastPos.latitude, longitude: lastPos.longitude }) });
  setResult("bad", "🚨 <b>Alerta de pânico enviado à central.</b>");
  toast("🚨 Pânico enviado");
};

// ---------- Homem-morto ----------
function startDeadmanPolling() {
  setInterval(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/deadman/pending`, { headers: authHeaders() });
      const ch = r.ok ? await r.json() : null;
      const modal = $("deadmanModal");
      if (ch && ch.id) {
        modal.dataset.cid = ch.id;
        modal.classList.remove("hidden");
        const left = Math.max(0, Math.round((new Date(ch.deadline_at) - new Date()) / 1000));
        $("deadmanTimer").textContent = `${left}s`;
      } else { modal.classList.add("hidden"); }
    } catch (_) {}
  }, 4000);
}
$("ackBtn").onclick = async () => {
  const cid = $("deadmanModal").dataset.cid;
  await fetch(`${API_BASE}/api/deadman/ack`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_id: Number(cid) }) });
  $("deadmanModal").classList.add("hidden");
  toast("Confirmado ✓");
};

// ---------- Telemetria (bateria/rede) ----------
async function pushTelemetry() {
  if (!token) return;
  let battery = null, charging = null;
  try { const b = await navigator.getBattery?.(); if (b) { battery = Math.round(b.level * 100); charging = b.charging; } } catch (_) {}
  const net = navigator.connection?.effectiveType || (navigator.onLine ? "online" : "offline");
  fetch(`${API_BASE}/api/telemetry`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ battery_level: battery, is_charging: charging, network_type: net }) }).catch(() => {});
}
setInterval(pushTelemetry, 60000);
