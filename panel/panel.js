// Painel da central. Consome /api/admin/* (somente operador/admin).
const API_BASE = location.pathname.startsWith("/panel") ? "" : "http://localhost:8000";
let token = null, map = null, layerSites = null, layerEvents = null, pollTimer = null;

const $ = (id) => document.getElementById(id);
const authHeaders = () => ({ Authorization: `Bearer ${token}` });
const api = (path, opts = {}) => fetch(`${API_BASE}${path}`, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
function toast(m, ms = 2400) { const t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms); }

// ---------- Login ----------
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const b = $("loginBtn"); b.disabled = true; b.textContent = "Entrando…";
  try {
    const body = new URLSearchParams({ username: $("email").value, password: $("password").value });
    const r = await fetch(`${API_BASE}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
    if (!r.ok) { $("loginMsg").textContent = "Credenciais inválidas"; return; }
    token = (await r.json()).access_token;
    const me = await (await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders() })).json();
    if (!["operator", "admin"].includes(me.role)) { $("loginMsg").textContent = "Acesso restrito à central."; token = null; return; }
    $("opName").textContent = `${me.name} · ${me.role}`;
    $("loginView").classList.add("hidden"); $("dashView").classList.remove("hidden");
    initMap(); await refreshAll(); startPolling();
  } catch (_) { $("loginMsg").textContent = "Erro de conexão"; }
  finally { b.disabled = false; b.textContent = "Entrar"; }
});
$("logoutBtn").onclick = () => location.reload();

// ---------- Mapa ----------
function initMap() {
  if (typeof L === "undefined") { $("map").classList.add("hidden"); $("mapFallback").classList.remove("hidden"); return; }
  map = L.map("map", { zoomControl: true }).setView([-23.5614, -46.6558], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
  layerSites = L.layerGroup().addTo(map);
  layerEvents = L.layerGroup().addTo(map);
}
async function renderMap(sites, events) {
  if (!map) return;
  layerSites.clearLayers(); layerEvents.clearLayers();
  const bounds = [];
  for (const s of sites) {
    L.circle([s.latitude, s.longitude], { radius: s.radius_m, color: "#3b82f6", fillOpacity: 0.08 }).addTo(layerSites);
    L.marker([s.latitude, s.longitude]).addTo(layerSites).bindPopup(`<b>${s.name}</b><br>raio ${s.radius_m} m`);
    bounds.push([s.latitude, s.longitude]);
  }
  for (const e of events.slice(0, 40)) {
    if (e.latitude == null) continue;
    const color = e.status === "approved" ? "#22c55e" : "#ef4444";
    L.circleMarker([e.latitude, e.longitude], { radius: 5, color, fillOpacity: 0.9 })
      .addTo(layerEvents).bindPopup(`${e.user} · ${e.type}<br>${e.status}${e.reason ? " · " + e.reason : ""}`);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
}

// ---------- Render ----------
function renderSummary(s) {
  $("kActive").textContent = s.active_shifts;
  $("kPanic").textContent = s.open_panics;
  $("kMissed").textContent = s.missed_deadman;
  $("kCheck").innerHTML = `<span style="color:#22c55e">${s.checkins_24h.approved}</span> / <span style="color:#fca5a5">${s.checkins_24h.rejected}</span>`;
}
function renderAlerts(live) {
  const box = $("alerts");
  const items = [];
  for (const p of live.panics) items.push(`<div class="alert panic"><div class="a-main"><strong>🚨 PÂNICO · ${p.user}</strong><small>${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)} · ${fmt(p.at)}</small></div><button class="btn ghost" onclick="resolvePanic(${p.id})">Resolver</button></div>`);
  for (const m of live.missed_deadman) items.push(`<div class="alert deadman"><div class="a-main"><strong>⏱️ Homem-morto perdido · ${m.user}</strong><small>turno #${m.shift_id} · prazo ${fmt(m.deadline_at)}</small></div></div>`);
  box.innerHTML = items.length ? items.join("") : '<div class="empty">Sem alertas.</div>';
  $("liveDot").style.color = live.panics.length ? "#ef4444" : "#22c55e";
}
function renderEvents(events) {
  const tb = $("eventsTbl").querySelector("tbody");
  tb.innerHTML = events.map((e) => {
    const info = e.status === "approved" ? `liveness ${fmtn(e.liveness)} · match ${fmtn(e.match)}` : (e.reason || "—");
    return `<tr><td>${fmt(e.at)}</td><td>${e.user}</td><td>${e.site}</td><td>${e.type}</td>
      <td><span class="badge ${e.status}">${e.status}</span></td><td>${info}</td></tr>`;
  }).join("");
}
const fmt = (iso) => { try { return new Date(iso).toLocaleString("pt-BR", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }); } catch { return iso; } };
const fmtn = (n) => (n == null ? "—" : Number(n).toFixed(2));

async function refreshAll() {
  const [summary, sites, events, live, users] = await Promise.all([
    api("/api/admin/summary").then((r) => r.json()),
    api("/api/sites").then((r) => r.json()),
    api("/api/admin/events?limit=40").then((r) => r.json()),
    api("/api/admin/live").then((r) => r.json()),
    api("/api/admin/users").then((r) => r.json()),
  ]);
  renderSummary(summary); renderAlerts(live); renderEvents(events); renderMap(sites, events);
  $("shUser").innerHTML = users.filter((u) => u.role === "employee").map((u) => `<option value="${u.id}">${u.name}</option>`).join("");
  $("shSite").innerHTML = sites.map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
}
async function pollLive() {
  const [summary, live] = await Promise.all([
    api("/api/admin/summary").then((r) => r.json()),
    api("/api/admin/live").then((r) => r.json()),
  ]);
  renderSummary(summary); renderAlerts(live);
}
function startPolling() { pollTimer = setInterval(pollLive, 4000); }

// ---------- Ações ----------
window.resolvePanic = async (id) => { await api(`/api/admin/panics/${id}/resolve`, { method: "POST" }); toast("Pânico resolvido"); refreshAll(); };

$("siteForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { name: $("sName").value, latitude: parseFloat($("sLat").value), longitude: parseFloat($("sLon").value), radius_m: parseFloat($("sRad").value) };
  const r = await api("/api/sites", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.ok) { toast("Posto adicionado"); e.target.reset(); $("sRad").value = "150"; refreshAll(); } else { toast("Erro ao adicionar"); }
});
$("shiftForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { user_id: Number($("shUser").value), site_id: Number($("shSite").value),
    scheduled_start: new Date($("shStart").value).toISOString(), scheduled_end: new Date($("shEnd").value).toISOString() };
  const r = await api("/api/shifts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.ok) { toast("Turno agendado"); } else { toast("Erro ao agendar"); }
});
