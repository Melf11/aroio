// Live state from aroiod over one WebSocket. Topics replace themselves as a
// whole. Reconnects with backoff; a reboot shows an overlay until it is back.

export const app = $state({
  connected: false,
  everConnected: false,
  rebooting: false,
  rebootSince: 0,
  rebootExpected: (() => { try { return +localStorage.getItem('aroio-reboot-s') || 60; } catch { return 60; } })(),
  showBack: false,
  topics: {
    device: null, player: null, queue: { items: [], index: -1 }, sources: [], dsp: null,
    services: null, network: null, bluetooth: null, update: null, migration: null,
    roomcorr: null, sim: null, system: null,
  },
  toasts: [],
  now: Date.now() / 1000,
});

let ws = null;
let retry = 0;
let toastId = 0;
const announceListeners = new Set();

export function onAnnounce(fn) {
  announceListeners.add(fn);
  return () => announceListeners.delete(fn);
}

export function announce(text, politeness = 'polite') {
  for (const fn of announceListeners) fn(text, politeness);
}

export function toast(text, level = 'info', ms = 4500) {
  const id = ++toastId;
  app.toasts.push({ id, text, level });
  announce(text, level === 'danger' ? 'assertive' : 'polite');
  setTimeout(() => dismiss(id), ms);
}

export function dismiss(id) {
  const i = app.toasts.findIndex((t) => t.id === id);
  if (i >= 0) app.toasts.splice(i, 1);
}

function rebootDone(oldVersion) {
  const seconds = (Date.now() - app.rebootSince) / 1000;
  if (seconds > 5) {
    app.rebootExpected = Math.round(seconds);
    try { localStorage.setItem('aroio-reboot-s', String(app.rebootExpected)); } catch { /* ignore */ }
  }
  app.rebooting = false;
  app.showBack = true;
  setTimeout(() => {
    app.showBack = false;
    // a new version after an update: load the new app
    if (oldVersion && app.topics.device?.version && oldVersion !== app.topics.device.version) location.reload();
  }, 1500);
}

export function connect() {
  if (ws && ws.readyState <= 1) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
  ws.onopen = () => { retry = 0; };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'snapshot') {
      const oldVersion = app.topics.device?.version;
      Object.assign(app.topics, msg.state);
      app.connected = true;
      app.everConnected = true;
      if (app.rebooting) rebootDone(oldVersion);
    } else if (msg.type === 'topic') {
      app.topics[msg.topic] = msg.data;
      if (msg.topic === 'system' && msg.data?.rebooting && !app.rebooting) {
        app.rebooting = true;
        app.rebootSince = Date.now();
      }
      if (msg.topic === 'system' && msg.data && !msg.data.rebooting && app.rebooting) rebootDone(null);
    } else if (msg.type === 'notice') {
      toast(msg.text, msg.level || 'info');
    }
  };
  ws.onclose = () => {
    app.connected = false;
    ws = null;
    const delay = app.rebooting ? 1500 : Math.min(10000, 500 * 2 ** retry++);   // restart: look often
    setTimeout(connect, delay);
  };
  ws.onerror = () => ws?.close();
}

// Re-connect at once when the app comes back to the foreground (iOS suspends sockets).
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && (!ws || ws.readyState > 1)) {
      retry = 0;
      connect();
    }
  });
  // one clock for progress bars, only ticking while visible
  setInterval(() => {
    if (document.visibilityState === 'visible') app.now = Date.now() / 1000;
  }, 500);
}

export function position(player, now) {
  if (!player) return 0;
  let p = player.position;
  if (player.state === 'playing') p += Math.max(0, now - player.position_at);
  const d = player.track?.duration;
  return d ? Math.min(p, d) : p;
}

export const expert = () => !!app.topics.device?.expert_mode;
