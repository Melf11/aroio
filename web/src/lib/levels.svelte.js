// One shared WebSocket for all level meters (/api/v1/levels), open only while
// at least one meter is on screen and the app is visible.

export const levels = $state({ peak: [-100, -100], rms: [-100, -100], at: 0, live: false });

let ws = null, users = 0, retry = null;

function open() {
  if (ws || users === 0 || document.visibilityState !== 'visible') return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/api/v1/levels`);
  ws.onmessage = (ev) => {
    const v = JSON.parse(ev.data);
    levels.peak = v.peak;
    levels.rms = v.rms;
    levels.at = performance.now();
    levels.live = true;
  };
  ws.onclose = () => {
    ws = null;
    levels.live = false;
    clearTimeout(retry);
    if (users > 0) retry = setTimeout(open, 2000);
  };
  ws.onerror = () => ws?.close();
}

function close() {
  clearTimeout(retry);
  const w = ws;
  ws = null;
  w?.close();
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => (document.visibilityState === 'visible' ? open() : close()));
}

export function useLevels() {
  users++;
  open();
  return () => {
    users--;
    if (users === 0) close();
  };
}
