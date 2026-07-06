// Cliente PoC do WFM. Backend em /api (mesma origem quando servido por /app),
// ou ajuste API_BASE para o host do FastAPI.
const API_BASE = location.pathname.startsWith("/app") ? "" : "http://localhost:8000";

let token = null;
let stream = null;
let lastPos = null;
let deadmanPoll = null;

const $ = (id) => document.getElementById(id);
const authHeaders = () => ({ Authorization: `Bearer ${token}` });

// ---------- Localização ----------
function watchLocation() {
  if (!navigator.geolocation) {
    $("geo").textContent = "❌ Geolocalização não suportada";
    return;
  }
  navigator.geolocation.watchPosition(
    (pos) => {
      lastPos = pos.coords;
      $("geo").textContent =
        `📍 ${pos.coords.latitude.toFixed(6)}, ${pos.coords.longitude.toFixed(6)} ` +
        `(±${Math.round(pos.coords.accuracy)} m)`;
    },
    (err) => { $("geo").textContent = "❌ " + err.message; },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
  );
}

// ---------- Câmera ----------
async function startCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    $("video").srcObject = stream;
  } catch (e) {
    $("result").textContent = "❌ Câmera negada: " + e.message;
  }
}

function captureSelfie() {
  const v = $("video"), c = $("canvas");
  c.width = v.videoWidth || 320;
  c.height = v.videoHeight || 240;
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  return new Promise((resolve) => c.toBlob(resolve, "image/jpeg", 0.85));
}

// ---------- Login ----------
$("loginBtn").onclick = async () => {
  const body = new URLSearchParams({ username: $("email").value, password: $("password").value });
  const r = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
  });
  if (!r.ok) { $("loginMsg").textContent = "❌ Credenciais inválidas"; return; }
  token = (await r.json()).access_token;
  const me = await (await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders() })).json();
  $("who").textContent = `👤 ${me.name} (${me.role})`;
  $("loginCard").classList.add("hidden");
  $("mainCard").classList.remove("hidden");
  await loadSites();
  await startCamera();
  watchLocation();
  startDeadmanPolling();
};

$("logoutBtn").onclick = () => location.reload();

async function loadSites() {
  const sites = await (await fetch(`${API_BASE}/api/sites`, { headers: authHeaders() })).json();
  $("siteSelect").innerHTML = sites
    .map((s) => `<option value="${s.id}">${s.name} (raio ${s.radius_m} m)</option>`).join("");
}

// ---------- Check-in / Check-out ----------
async function submitCheck(type) {
  if (!lastPos) { $("result").textContent = "⏳ Aguardando GPS…"; return; }
  $("result").textContent = "⏳ Validando…";
  const selfie = await captureSelfie();

  const fd = new FormData();
  fd.append("site_id", $("siteSelect").value);
  fd.append("type", type);
  fd.append("latitude", lastPos.latitude);
  fd.append("longitude", lastPos.longitude);
  fd.append("accuracy_m", lastPos.accuracy ?? "");
  fd.append("client_timestamp", new Date().toISOString());
  // No navegador não há detecção de mock — enviamos false. No app nativo isto vem real.
  fd.append("is_mock_location", "false");
  fd.append("is_rooted", "false");
  fd.append("device_info", navigator.userAgent.slice(0, 200));
  fd.append("selfie", selfie, "selfie.jpg");

  const r = await fetch(`${API_BASE}/api/checkin`, { method: "POST", headers: authHeaders(), body: fd });
  const data = await r.json();
  if (data.status === "approved") {
    $("result").innerHTML =
      `✅ <b>Aprovado</b> — ${Math.round(data.distance_m)} m do posto · ` +
      `liveness ${data.liveness_score?.toFixed(2)} · match ${data.face_match_score?.toFixed(2)}`;
  } else {
    $("result").innerHTML = `❌ <b>Rejeitado</b>: ${data.reason || data.detail || "erro"}`;
  }
}

$("checkinBtn").onclick = () => submitCheck("checkin");
$("checkoutBtn").onclick = () => submitCheck("checkout");

// ---------- Pânico ----------
$("panicBtn").onclick = async () => {
  if (!lastPos) { alert("Sem localização ainda."); return; }
  await fetch(`${API_BASE}/api/panic`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ latitude: lastPos.latitude, longitude: lastPos.longitude }),
  });
  $("result").innerHTML = "🚨 <b>Alerta de pânico enviado à central.</b>";
};

// ---------- Homem-morto (polling; no app nativo seria push) ----------
function startDeadmanPolling() {
  deadmanPoll = setInterval(async () => {
    const r = await fetch(`${API_BASE}/api/deadman/pending`, { headers: authHeaders() });
    const ch = r.ok ? await r.json() : null;
    const box = $("deadman");
    if (ch && ch.id) {
      box.classList.remove("hidden");
      box.dataset.cid = ch.id;
      const left = Math.max(0, Math.round((new Date(ch.deadline_at) - new Date()) / 1000));
      $("deadmanTimer").textContent = `⏱️ ${left}s`;
    } else {
      box.classList.add("hidden");
    }
  }, 5000);
}

$("ackBtn").onclick = async () => {
  const cid = $("deadman").dataset.cid;
  await fetch(`${API_BASE}/api/deadman/ack`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_id: Number(cid) }),
  });
  $("deadman").classList.add("hidden");
};
