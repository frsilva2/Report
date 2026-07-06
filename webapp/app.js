// Cliente PoC do WFM. Backend em /api (mesma origem quando servido por /app),
// ou ajuste API_BASE para o host do FastAPI.
const API_BASE = location.pathname.startsWith("/app") ? "" : "http://localhost:8000";

let token = null;
let stream = null;
let lastPos = null;
let deadmanPoll = null;
let faceLandmarker = null; // MediaPipe (carregado sob demanda)

const $ = (id) => document.getElementById(id);
const authHeaders = () => ({ Authorization: `Bearer ${token}` });

// ---------- Localização ----------
function watchLocation() {
  if (!navigator.geolocation) { $("geo").textContent = "❌ Geolocalização não suportada"; return; }
  navigator.geolocation.watchPosition(
    (pos) => {
      lastPos = pos.coords;
      $("geo").textContent =
        `📍 ${pos.coords.latitude.toFixed(6)}, ${pos.coords.longitude.toFixed(6)} (±${Math.round(pos.coords.accuracy)} m)`;
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
  } catch (e) { $("result").textContent = "❌ Câmera negada: " + e.message; }
}

function captureSelfie() {
  const v = $("video"), c = $("canvas");
  c.width = v.videoWidth || 320; c.height = v.videoHeight || 240;
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  return new Promise((resolve) => c.toBlob(resolve, "image/jpeg", 0.85));
}

// ---------- MediaPipe: liveness ativa por movimento ----------
async function ensureLandmarker() {
  if (faceLandmarker) return faceLandmarker;
  // Import dinâmico do CDN (precisa de internet no navegador do usuário).
  const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18");
  const fileset = await vision.FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm"
  );
  faceLandmarker = await vision.FaceLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    },
    outputFaceBlendshapes: true,
    numFaces: 1,
    runningMode: "VIDEO",
  });
  return faceLandmarker;
}

function blendshape(res, name) {
  const cats = res.faceBlendshapes?.[0]?.categories || [];
  return cats.find((c) => c.categoryName === name)?.score ?? 0;
}

// Yaw aproximado (graus) a partir dos landmarks: nariz relativo às bordas do rosto.
// Aproximação suficiente para o desafio; ajuste fino no campo se necessário.
function estimateYaw(res) {
  const lm = res.faceLandmarks?.[0];
  if (!lm) return 0;
  const nose = lm[1], right = lm[234], left = lm[454];
  const mid = (left.x + right.x) / 2;
  const half = Math.abs(right.x - left.x) / 2 || 1e-6;
  return ((nose.x - mid) / half) * 60; // ratio [-1..1] -> ~graus
}

// Roda o desafio: mede os extremos das métricas durante a janela e devolve a evidência.
async function runChallenge(actions, windowSeconds) {
  await ensureLandmarker();
  const labels = { blink: "pisque os olhos", turn_left: "vire à esquerda", turn_right: "vire à direita", smile: "sorria" };
  $("challengeBox").classList.remove("hidden");
  $("challengeMsg").textContent = "Faça: " + actions.map((a) => labels[a] || a).join(" → ");

  const ev = { max_blink: 0, min_yaw: 0, max_yaw: 0, max_smile: 0 };
  const video = $("video");
  const endAt = performance.now() + Math.min(windowSeconds, 10) * 1000;

  await new Promise((resolve) => {
    function tick() {
      if (performance.now() >= endAt) return resolve();
      const res = faceLandmarker.detectForVideo(video, performance.now());
      if (res.faceLandmarks?.length) {
        const blink = Math.max(blendshape(res, "eyeBlinkLeft"), blendshape(res, "eyeBlinkRight"));
        const smile = (blendshape(res, "mouthSmileLeft") + blendshape(res, "mouthSmileRight")) / 2;
        const yaw = estimateYaw(res);
        ev.max_blink = Math.max(ev.max_blink, blink);
        ev.max_smile = Math.max(ev.max_smile, smile);
        ev.min_yaw = Math.min(ev.min_yaw, yaw);
        ev.max_yaw = Math.max(ev.max_yaw, yaw);
        const left = Math.ceil((endAt - performance.now()) / 1000);
        $("challengeMsg").textContent =
          `Faça: ${actions.map((a) => labels[a] || a).join(" → ")}  (${left}s)`;
      }
      requestAnimationFrame(tick);
    }
    tick();
  });

  $("challengeBox").classList.add("hidden");
  return ev;
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

  // 1) Pega um desafio de prova de vida e executa o movimento.
  let nonce = null, evidence = null;
  try {
    const ch = await (await fetch(`${API_BASE}/api/checkin/challenge`, {
      method: "POST", headers: authHeaders(),
    })).json();
    nonce = ch.nonce;
    $("result").textContent = "🟢 Prova de vida…";
    evidence = await runChallenge(ch.actions, ch.window_seconds);
  } catch (e) {
    $("result").innerHTML = "❌ Prova de vida indisponível neste navegador: " + e.message;
    return;
  }

  // 2) Captura a selfie e envia com a evidência do desafio.
  $("result").textContent = "⏳ Validando…";
  const selfie = await captureSelfie();
  const fd = new FormData();
  fd.append("site_id", $("siteSelect").value);
  fd.append("type", type);
  fd.append("latitude", lastPos.latitude);
  fd.append("longitude", lastPos.longitude);
  fd.append("accuracy_m", lastPos.accuracy ?? "");
  fd.append("client_timestamp", new Date().toISOString());
  fd.append("is_mock_location", "false"); // no navegador não há detecção de mock
  fd.append("is_rooted", "false");
  fd.append("device_info", navigator.userAgent.slice(0, 200));
  fd.append("challenge_nonce", nonce);
  fd.append("challenge_evidence", JSON.stringify(evidence));
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
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
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
    } else { box.classList.add("hidden"); }
  }, 5000);
}

$("ackBtn").onclick = async () => {
  const cid = $("deadman").dataset.cid;
  await fetch(`${API_BASE}/api/deadman/ack`, {
    method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_id: Number(cid) }),
  });
  $("deadman").classList.add("hidden");
};
