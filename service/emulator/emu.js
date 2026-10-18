// Tablo emulator: does what the firmware will do (tablo-software.md §3–§5, §9).
// Speaks the device protocol to the service, keeps the base frame, draws the
// clock, date and status bar itself, inverts tiles instantly on key presses.
"use strict";

const W = 800, H = 480, ROW = W / 8, PAYLOAD = ROW * H, HEADER = 20;
const FW = "emu-0.1";
const params = new URLSearchParams(location.search);
const TOKEN = params.get("token") || "dev-device-token";
const DEVICE = params.get("device") || "tablo-emu";

const MDI = {
  wifi: 0xf0925, wifiOff: 0xf092e,
  cloud: 0xf0163, cloudOff: 0xf0164,
  home: 0xf06a1, homeOff: 0xf1a47,
};

const DEFAULT_CONFIG = {
  tz_name: "Europe/Moscow",
  semester_start: "2026-09-01",
  zones: { clock: [0, 0, 184, 100], status: [600, 0, 200, 24], buttons: [0, 428, 800, 52], tile_width: 100 },
  long_press_ms: 600,
  full_refresh: { at: "04:00", max_partials: 200 },
  offline_after_s: 120,
  diag_ttl_s: 30,
};

const st = {
  cfg: DEFAULT_CONFIG,
  health: { ha: false, synced_at: null },
  ws: null,
  connected: false,
  offlineSince: Date.now(),
  backoffIdx: 0,
  seq: 0,
  base: null,          // Uint8Array payload of the last base frame
  baseCrc: null,
  baseId: null,
  pendingBase: null,   // base frame that arrived during an overlay
  overlay: null,       // {payload, timer}
  diag: null,          // {timer}
  pending: new Map(),  // tile index -> timeout id (local inversion waiting for button_result)
  held: null,          // {tile, long, timer, swallow, key}
  partials: 0,
  lastFullDay: null,
  startedAt: Date.now(),
  lastFrameAt: null,
  displayed: new Uint8Array(W * H),
};

// ---------- DOM ----------
const screen = document.getElementById("screen");
const sctx = screen.getContext("2d");
const off = document.createElement("canvas");
off.width = W; off.height = H;
const octx = off.getContext("2d", { willReadFrequently: true });
const $ = (id) => document.getElementById(id);
const opt = { offline: $("opt-offline"), rects: $("opt-rects"), paper: $("opt-paper"), scale: $("opt-scale") };

function applyScale() {
  // Upscale only by whole numbers so every screen pixel stays a crisp square; a 1-bit image shrunk
  // pixel by pixel loses one-pixel strokes, so below 1:1 the browser smooths it instead.
  const avail = (document.documentElement.clientWidth - 32) / (W + 36);
  const fit = avail >= 1 ? Math.min(2, Math.floor(avail)) : avail;
  const s = opt.scale.value === "fit" ? fit : parseFloat(opt.scale.value);
  const exact = s >= 1 && Number.isInteger(s);
  screen.style.imageRendering = exact ? "pixelated" : "auto";
  $("scale-hint").hidden = s >= 1;
  screen.style.width = `${W * s}px`;
  $("keys").style.width = `${W * s}px`;
  $("device").style.setProperty("--pad", `${Math.round(18 * s)}px`);
}
opt.scale.addEventListener("change", applyScale);
window.addEventListener("resize", applyScale);
opt.paper.addEventListener("change", () => paint());
opt.offline.addEventListener("change", () => {
  if (opt.offline.checked) { if (st.ws) st.ws.close(); }
  else connect();
});

function log(dir, text) {
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()} ${dir} ${text}`;
  const ol = $("log");
  ol.prepend(li);
  while (ol.children.length > 80) ol.lastChild.remove();
}

// ---------- CRC32 (same as zlib.crc32) ----------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// ---------- time ----------
function nowParts() {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: st.cfg.tz_name, hour12: false, weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", year: "numeric",
  });
  const p = Object.fromEntries(f.formatToParts(new Date()).map((x) => [x.type, x.value]));
  const hh = p.hour === "24" ? "00" : p.hour;
  return { ...p, hour: hh, hhmm: `${hh}:${p.minute}` };
}
function semesterWeek(p) {
  const today = Date.UTC(+p.year, new Date(`${p.month} 1 2000`).getMonth(), +p.day);
  const [y, m, d] = st.cfg.semester_start.split("-").map(Number);
  const start = new Date(Date.UTC(y, m - 1, d));
  const monday = start.getTime() - ((start.getUTCDay() + 6) % 7) * 86400000;
  return Math.floor((today - monday) / (7 * 86400000)) + 1;
}

// ---------- buffers ----------
function bitsInto(buf, payload) {
  for (let i = 0; i < PAYLOAD; i++) {
    const byte = payload[i];
    if (!byte) continue;
    const base = (i / ROW | 0) * W + (i % ROW) * 8;
    for (let b = 0; b < 8; b++) if (byte & (0x80 >> b)) buf[base + b] = 1;
  }
}
function fillRect(buf, [x, y, w, h], v) {
  for (let yy = y; yy < y + h; yy++) buf.fill(v, yy * W + x, yy * W + x + w);
}
function invertRect(buf, [x, y, w, h]) {
  for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) buf[yy * W + xx] ^= 1;
}
function tileRect(i) {
  const [bx, by, , bh] = st.cfg.zones.buttons;
  const tw = st.cfg.zones.tile_width;
  return [bx + i * tw, by + 2, tw, bh - 2];
}
function tileChanged(a, b, i) {
  const [x, y, w, h] = tileRect(i);
  for (let yy = y; yy < y + h; yy++) {
    for (let bx = x >> 3; bx < (x + w + 7) >> 3; bx++) if (a[yy * ROW + bx] !== b[yy * ROW + bx]) return true;
  }
  return false;
}

// Draw with the 2D canvas, then cut to pure black/white into buf (like a 1-bit display driver).
function drawZone(buf, rect, fn, invert = false) {
  const [x, y, w, h] = rect;
  octx.save();
  octx.fillStyle = invert ? "#000" : "#fff";
  octx.fillRect(x, y, w, h);
  octx.fillStyle = invert ? "#fff" : "#000";
  octx.beginPath(); octx.rect(x, y, w, h); octx.clip();
  fn(octx);
  octx.restore();
  const data = octx.getImageData(x, y, w, h).data;
  for (let yy = 0; yy < h; yy++) {
    for (let xx = 0; xx < w; xx++) buf[(y + yy) * W + x + xx] = data[(yy * w + xx) * 4] < 128 ? 1 : 0;
  }
}

// ---------- pixel fonts: the same text files as the service (§6.3), and later the firmware ----------
const PIXEL = {};  // clock: digits of the clock zone, date: Inter Medium 16

function parsePixelFont(text) {
  const lines = text.split("\n");
  const pf = { glyphs: new Map() };
  let i = 0;
  for (; i < lines.length && !lines[i].startsWith("glyph "); i++) {
    const [k, v] = lines[i].split(" ");
    if (k === "ascent" || k === "descent") pf[k] = Number(v);
  }
  while (i < lines.length) {
    const ch = String.fromCodePoint(parseInt(lines[i].split(" ")[1], 16));
    const f = lines[i + 1].split(" ");
    const g = { rows: [] };
    for (let j = 0; j < f.length; j += 2) g[f[j]] = Number(f[j + 1]);
    for (i += 2; i < lines.length && lines[i] && !lines[i].startsWith("glyph "); i++) g.rows.push(lines[i]);
    pf.glyphs.set(ch, g);
    while (i < lines.length && !lines[i]) i++;
  }
  return pf;
}

async function loadPixelFonts() {
  const load = async (name) => parsePixelFont(await (await fetch(`/fonts/pixel/${name}.txt`)).text());
  try {
    [PIXEL.clock, PIXEL.date] = await Promise.all([load("clock-64"), load("Inter-Medium-16")]);
  } catch (err) {
    log("!", `pixel fonts not loaded, drawing with Inter: ${err}`);
  }
}

// Text from a pixel font straight into buf, clipped to rect; x is the pen, baseline the y of the baseline.
function drawPixelText(buf, rect, pf, x, baseline, text) {
  const [rx, ry, rw, rh] = rect;
  const top = baseline - pf.ascent;
  for (const ch of text) {
    const g = pf.glyphs.get(ch) || pf.glyphs.get(" ");
    g.rows.forEach((row, r) => {
      const y = top + g.top + r;
      if (y < ry || y >= ry + rh) return;
      for (let c = 0; c < row.length; c++) {
        const xx = x + g.left + c;
        if (row[c] === "#" && xx >= rx && xx < rx + rw) buf[y * W + xx] = 1;
      }
    });
    x += g.advance;
  }
}

// ---------- firmware-drawn parts ----------
function serviceOffline() {
  return !st.connected && Date.now() - st.offlineSince > st.cfg.offline_after_s * 1000;
}

function drawFirmwareZones(buf) {
  const p = nowParts();
  const [cx, cy] = st.cfg.zones.clock;
  const date = `${p.weekday}, ${p.month} ${p.day} · wk ${semesterWeek(p)}`;
  drawZone(buf, st.cfg.zones.clock, (c) => {
    if (PIXEL.clock) return;  // drawn from the pixel fonts below
    c.font = "700 64px InterEmu";
    c.fillText(p.hhmm, cx + 6, cy + 66);
    c.font = "500 16px InterEmu";
    c.fillText(date, cx + 8, cy + 90);
  });
  if (PIXEL.clock) {
    // Digits of one width: "HH:MM" is always 174 px and fits the 184 px zone.
    drawPixelText(buf, st.cfg.zones.clock, PIXEL.clock, cx + 6, cy + 66, p.hhmm);
    drawPixelText(buf, st.cfg.zones.clock, PIXEL.date, cx + 8, cy + 90, date);
  }

  const zs = st.cfg.zones.status;
  const [sx, sy, sw] = zs;
  if (serviceOffline()) {
    const since = new Intl.DateTimeFormat("en-GB", { timeZone: st.cfg.tz_name, hour: "2-digit", minute: "2-digit" })
      .format(new Date(st.offlineSince));
    drawZone(buf, zs, (c) => {
      c.font = "600 15px InterEmu"; c.textAlign = "right";
      c.fillText(`offline since ${since}`, sx + sw - 8, sy + 17);
    }, true);
    return;
  }
  drawZone(buf, zs, (c) => {
    c.textAlign = "right";
    let x = sx + sw - 4;
    if (st.health.synced_at) {
      c.font = "500 15px InterEmu";
      const t = `synced ${st.health.synced_at}`;
      c.fillText(t, x, sy + 17);
      x -= c.measureText(t).width + 8;
    }
    c.font = "17px MDIEmu";
    for (const code of [st.connected && st.health.ha ? MDI.home : MDI.homeOff,
                        st.connected ? MDI.cloud : MDI.cloudOff, MDI.wifi]) {
      const g = String.fromCodePoint(code);
      c.fillText(g, x, sy + 19);
      x -= c.measureText(g).width + 5;
    }
  });
}

function drawDiag(buf) {
  const up = Math.floor((Date.now() - st.startedAt) / 1000);
  const lines = [
    ["Diagnostics", ""],
    ["IP", "emulator"],
    ["Wi-Fi", "-55 dBm"],
    ["Uptime", `${Math.floor(up / 3600)}h ${Math.floor(up / 60) % 60}m ${up % 60}s`],
    ["Firmware", FW],
    ["Free heap", "n/a (emulator)"],
    ["Service", st.connected ? "connected" : `offline since ${new Date(st.offlineSince).toLocaleTimeString()}`],
    ["Home Assistant", st.connected ? (st.health.ha ? "ok" : "down") : "unknown"],
    ["Last frame", st.lastFrameAt ? `${new Date(st.lastFrameAt).toLocaleTimeString()} · id ${st.baseId}` : "none"],
    ["Partial updates", String(st.partials)],
  ];
  drawZone(buf, [0, 0, W, H], (c) => {
    lines.forEach(([k, v], i) => {
      if (i === 0) { c.font = "700 34px InterEmu"; c.fillText(k, 40, 64); return; }
      c.font = "600 22px InterEmu"; c.fillText(k, 40, 90 + i * 36);
      c.font = "400 22px InterEmu"; c.fillText(v, 280, 90 + i * 36);
    });
  });
}

// ---------- compose & present ----------
function compose() {
  const buf = new Uint8Array(W * H);
  if (st.overlay) {
    bitsInto(buf, st.overlay.payload);
  } else if (st.diag) {
    drawDiag(buf);
  } else {
    if (st.base) bitsInto(buf, st.base);
    drawFirmwareZones(buf);
    for (const tile of st.pending.keys()) invertRect(buf, tileRect(tile));
    if (st.held && st.held.tile != null && !st.held.swallow) {
      const r = tileRect(st.held.tile);
      if (!st.pending.has(st.held.tile)) invertRect(buf, r);
      if (st.held.long) {
        // Long press armed: frame instead of fill (§4.1).
        const [x, y, w, h] = r;
        invertRect(buf, [x + 4, y + 4, w - 8, h - 8]);
        fillRect(buf, [x, y, w, 4], 1); fillRect(buf, [x, y + h - 4, w, 4], 1);
        fillRect(buf, [x, y, 4, h], 1); fillRect(buf, [x + w - 4, y, 4, h], 1);
      }
    }
  }
  return buf;
}

let rectFlash = null;
function present(full = false) {
  const buf = compose();
  if (full) {
    st.displayed = buf; st.partials = 0;
    fullRefreshAnimation();
    return;
  }
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) {
    const o = y * W;
    for (let x = 0; x < W; x++) {
      if (buf[o + x] !== st.displayed[o + x]) {
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return;
  st.displayed = buf;
  st.partials++;
  if (opt.rects.checked) {
    rectFlash = [x0, y0, x1 - x0 + 1, y1 - y0 + 1];
    setTimeout(() => { rectFlash = null; paint(); }, 450);
  }
  paint();
  if (st.partials >= st.cfg.full_refresh.max_partials) present(true);
  updateInfo();
}

function paint(override) {
  const paper = opt.paper.checked;
  const ink = paper ? [34, 34, 32] : [0, 0, 0];
  const bg = paper ? [226, 224, 216] : [255, 255, 255];
  const img = sctx.createImageData(W, H);
  const src = override || st.displayed;
  for (let i = 0; i < W * H; i++) {
    const c = src[i] ? ink : bg;
    img.data[i * 4] = c[0]; img.data[i * 4 + 1] = c[1]; img.data[i * 4 + 2] = c[2]; img.data[i * 4 + 3] = 255;
  }
  sctx.putImageData(img, 0, 0);
  if (rectFlash && !override) {
    sctx.strokeStyle = "rgba(220,60,40,0.9)"; sctx.lineWidth = 2;
    sctx.strokeRect(rectFlash[0] + 1, rectFlash[1] + 1, rectFlash[2] - 2, rectFlash[3] - 2);
  }
}

function fullRefreshAnimation() {
  const black = new Uint8Array(W * H).fill(1), white = new Uint8Array(W * H);
  const steps = [black, white, black, null];
  steps.forEach((s, i) => setTimeout(() => (s ? paint(s) : paint()), i * 220));
  setTimeout(updateInfo, steps.length * 220);
}

function updateInfo() {
  $("frameinfo").textContent =
    `frame ${st.baseId ?? "—"} · crc ${st.baseCrc?.toString(16) ?? "—"} · partial updates since full: ${st.partials}`;
}

// ---------- protocol ----------
function send(obj) {
  if (st.ws && st.ws.readyState === WebSocket.OPEN) {
    st.ws.send(JSON.stringify(obj));
    if (obj.type !== "status") log("→", JSON.stringify(obj));
    return true;
  }
  return false;
}

function onFrame(buffer) {
  const dv = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  if (buffer.byteLength !== HEADER + PAYLOAD || magic !== "TBLF") { log("!", "bad frame"); return; }
  const kind = dv.getUint8(5), ttl = dv.getUint16(6, true), id = dv.getUint32(8, true), crc = dv.getUint32(12, true);
  const payload = new Uint8Array(buffer, HEADER).slice();
  if (crc32(payload) !== crc) { log("!", `frame ${id} crc mismatch`); return; }
  log("←", `frame #${id} ${kind ? `overlay ttl ${ttl}s` : "base"}`);
  st.lastFrameAt = Date.now();

  if (kind === 1) {
    closeLocalScreens();
    st.overlay = { payload, timer: setTimeout(() => endOverlay("ttl"), ttl * 1000) };
  } else if (st.overlay || st.diag) {
    st.pendingBase = { payload, crc, id };
  } else {
    acceptBase(payload, crc, id);
  }
  present();
  send({ type: "frame_ack", frame_id: id });
}

function acceptBase(payload, crc, id) {
  // A tile that changed in the new frame has its real state now: drop the local inversion (§4.2).
  if (st.base) {
    for (const [tile, t] of st.pending) {
      if (tileChanged(st.base, payload, tile)) { clearTimeout(t.id); st.pending.delete(tile); }
    }
  }
  st.base = payload; st.baseCrc = crc; st.baseId = id;
}

function closeLocalScreens() {
  if (st.diag) { clearTimeout(st.diag.timer); st.diag = null; }
  if (st.overlay) { clearTimeout(st.overlay.timer); st.overlay = null; }
}

function endOverlay(reason) {
  if (!st.overlay) return;
  closeLocalScreens();
  send({ type: "overlay_closed", reason });
  if (st.pendingBase) { acceptBase(st.pendingBase.payload, st.pendingBase.crc, st.pendingBase.id); st.pendingBase = null; }
  present();
}

function endDiag() {
  closeLocalScreens();
  if (st.pendingBase) { acceptBase(st.pendingBase.payload, st.pendingBase.crc, st.pendingBase.id); st.pendingBase = null; }
  present();
}

function onMessage(msg) {
  log("←", JSON.stringify(msg));
  switch (msg.type) {
    case "config": st.cfg = { ...DEFAULT_CONFIG, ...msg, zones: { ...DEFAULT_CONFIG.zones, ...msg.zones } }; break;
    case "health": st.health = msg; break;
    case "button_result": {
      for (const [tile, t] of st.pending) {
        if (t.seq === msg.seq) { clearTimeout(t.id); st.pending.delete(tile); }
      }
      break;
    }
    case "full_refresh": present(true); return;
  }
  present();
}

const BACKOFF = [1, 2, 4, 8, 16, 30];
function connect() {
  if (opt.offline.checked) return;
  if (st.ws && st.ws.readyState <= WebSocket.OPEN) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?device=${encodeURIComponent(DEVICE)}&token=${encodeURIComponent(TOKEN)}`);
  ws.binaryType = "arraybuffer";
  st.ws = ws;
  ws.onopen = () => {
    st.connected = true; st.backoffIdx = 0;
    setBadge("connected", "ok");
    send({ type: "hello", fw: FW, device: DEVICE, last_crc: st.baseCrc, rssi: -55,
           uptime_s: Math.floor((Date.now() - st.startedAt) / 1000) });
    present();
  };
  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      try { onMessage(JSON.parse(e.data)); } catch (err) { log("!", `bad message: ${err}`); }
    } else onFrame(e.data);
  };
  ws.onclose = () => {
    if (st.ws !== ws) return;
    if (st.connected) st.offlineSince = Date.now();
    st.connected = false;
    setBadge(opt.offline.checked ? "offline (simulated)" : "reconnecting…", "bad");
    present();
    const delay = BACKOFF[Math.min(st.backoffIdx++, BACKOFF.length - 1)];
    setTimeout(connect, delay * 1000);
  };
}
function setBadge(text, cls) { const b = $("conn"); b.textContent = text; b.className = `badge ${cls}`; }

// ---------- buttons ----------
function keyDown(tile, key) {
  if (st.held) return;
  const swallow = !!(st.overlay || st.diag);
  st.held = { tile, key, long: false, swallow };
  st.held.timer = setTimeout(() => { if (st.held) { st.held.long = true; present(); } }, st.cfg.long_press_ms);
  markKey(tile, true);
  present();
}

function keyUp(tile) {
  const h = st.held;
  if (!h || h.tile !== tile) return;
  clearTimeout(h.timer);
  st.held = null;
  markKey(tile, false);
  const press = h.long ? "long" : "short";

  if (h.swallow) {
    // Any key closes an overlay or diagnostics and does nothing else (§5).
    if (st.overlay) endOverlay("button"); else endDiag();
    return;
  }
  const id = tile + 1;
  if (id === 8) {
    send({ type: "button", id, press, seq: ++st.seq, local: true });
    if (press === "short") present(true);
    else {
      st.diag = { timer: setTimeout(endDiag, st.cfg.diag_ttl_s * 1000) };
      present();
    }
    return;
  }
  const seq = ++st.seq;
  if (send({ type: "button", id, press, seq })) {
    const timeout = setTimeout(() => { st.pending.delete(tile); present(); }, 12000);
    st.pending.set(tile, { seq, id: timeout });
  } else {
    // Service unreachable: flip the tile and flip it back, so the press visibly did not go through (§4.2).
    const timeout = setTimeout(() => { st.pending.delete(tile); present(); }, 1500);
    st.pending.set(tile, { seq, id: timeout });
  }
  present();
}

function markKey(tile, down) { $("keys").children[tile]?.classList.toggle("down", down); }

function setupKeys() {
  const keys = $("keys");
  for (let i = 0; i < 8; i++) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = String(i + 1);
    b.setAttribute("aria-label", `Button ${i + 1}`);
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); keyDown(i); });
    b.addEventListener("pointerup", () => keyUp(i));
    b.addEventListener("pointercancel", () => keyUp(i));
    keys.append(b);
  }
  window.addEventListener("keydown", (e) => {
    if (e.repeat || e.target.closest("select,input")) return;
    const n = Number(e.key);
    if (n >= 1 && n <= 8) keyDown(n - 1, e.key);
  });
  window.addEventListener("keyup", (e) => {
    const n = Number(e.key);
    if (n >= 1 && n <= 8) keyUp(n - 1);
  });
}

// ---------- demo data switches (service side, §15) ----------
const API_TOKEN = params.get("api_token") || "dev-api-token";
const DEMO_LABELS = { weather: "weather", deadlines: "deadlines", grades: "grades", news: "news", classes: "classes", ha: "fake HA" };

async function setupDemo() {
  const row = $("demo-row");
  let demo;
  try {
    demo = await (await fetch("/api/demo")).json();
  } catch (err) {
    row.lastChild.textContent = `unavailable: ${err}`;
    return;
  }
  row.lastChild.remove();
  for (const [key, label] of Object.entries(DEMO_LABELS)) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!demo[key];
    box.addEventListener("change", async () => {
      const resp = await fetch("/api/demo", {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${API_TOKEN}` },
        body: JSON.stringify({ [key]: box.checked }),
      }).catch((err) => ({ ok: false, statusText: String(err) }));
      if (!resp.ok) {
        box.checked = !box.checked;
        log("!", `demo switch failed: ${resp.status ?? ""} ${resp.statusText} (pass ?api_token=… in the address)`);
      }
    });
    const l = document.createElement("label");
    l.append(box, ` ${label}`);
    row.append(l);
  }
}

// ---------- clock, status, scheduled full refresh ----------
let lastMinute = null;
function tick() {
  const p = nowParts();
  if (p.hhmm !== lastMinute) {
    lastMinute = p.hhmm;
    const today = `${p.year}-${p.month}-${p.day}`;
    if (p.hhmm === st.cfg.full_refresh.at && st.lastFullDay !== today) {
      st.lastFullDay = today;
      present(true);
    } else present();
  } else if (!st.connected) {
    present(); // the offline bar appears after offline_after_s
  }
}

async function start() {
  applyScale();
  setupKeys();
  const faces = [
    new FontFace("InterEmu", "url(/fonts/Inter-Regular.ttf)", { weight: "400" }),
    new FontFace("InterEmu", "url(/fonts/Inter-Medium.ttf)", { weight: "500" }),
    new FontFace("InterEmu", "url(/fonts/Inter-SemiBold.ttf)", { weight: "600" }),
    new FontFace("InterEmu", "url(/fonts/Inter-Bold.ttf)", { weight: "700" }),
    new FontFace("MDIEmu", "url(/mdi/materialdesignicons-webfont.ttf)"),
  ];
  await Promise.all([...faces.map((f) => f.load().then(() => document.fonts.add(f))), loadPixelFonts()]);
  present(true);
  connect();
  setupDemo();
  setInterval(tick, 1000);
  setInterval(() => send({
    type: "status", rssi: -55, uptime_s: Math.floor((Date.now() - st.startedAt) / 1000),
    heap: 0, partials_since_full: st.partials, ip: "emulator",
  }), 60000);
}
start();
