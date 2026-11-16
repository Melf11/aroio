// Aroio demo for GitHub Pages: the simulated Aroio (aroiod --sim) runs as Python in the
// browser (Pyodide). The app's fetch() and WebSocket calls to /api/v1 go to it; the app
// itself is the unchanged one. Only in the "demo" build (vite build --mode demo).

import backendSource from './backend.py?raw';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const BASE = import.meta.env.BASE_URL;

function loader(text) {
  let el = document.getElementById('demo-loader');
  if (!el) {
    el = document.createElement('div');
    el.id = 'demo-loader';
    el.setAttribute('role', 'status');
    el.innerHTML = `<img src="${BASE}icons/logo.svg" alt="" width="64" height="64"><p></p><p class="small">Der simulierte Aroio läuft als Python direkt in deinem Browser. Beim ersten Mal werden dafür etwa 20 MB geladen.</p>`;
    document.body.append(el);
  }
  el.querySelector('p').textContent = text;
  return el;
}

function bar() {
  const el = document.createElement('div');
  el.id = 'demo-bar';
  el.innerHTML = `<span><strong>Demo</strong> · simulierter Aroio, läuft nur in deinem Browser</span>
    <a href="https://github.com/Melf11/aroio" rel="external">GitHub</a>
    <button type="button">Neu starten</button>`;
  el.querySelector('button').onclick = () => location.reload();
  document.body.prepend(el);
}

function patchFetch(backend) {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/v1/')) return realFetch(input, init);
    const body = ['GET', 'HEAD'].includes(req.method) ? null : new Uint8Array(await req.arrayBuffer());
    const result = await backend.call(req.method, url.pathname + url.search, req.headers.get('content-type'),
                                      body && body.length ? body : null);
    const [status, headers, data] = result.toJs();
    result.destroy();
    return new Response([204, 304].includes(status) ? null : new Uint8Array(data), { status, headers: JSON.parse(headers) });
  };
}

function patchWebSocket(backend) {
  const RealWebSocket = window.WebSocket;
  class DemoSocket extends EventTarget {
    constructor(url) {
      super();
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      const kind = url.includes('/api/v1/levels') ? 'levels' : 'ws';
      setTimeout(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this.emit(new Event('open'));
        this.closer = backend.open_socket(kind, (text) => this.emit(new MessageEvent('message', { data: text })));
      });
    }
    emit(ev) {
      if (this.readyState === 3 && ev.type !== 'close') return;
      this.dispatchEvent(ev);
      this['on' + ev.type]?.call(this, ev);
    }
    send(data) {
      if (data === 'ping') setTimeout(() => this.emit(new MessageEvent('message', { data: '{"type":"pong"}' })));
    }
    close() {
      if (this.readyState >= 2) return;
      this.readyState = 3;
      if (this.closer) { this.closer(); this.closer.destroy(); }
      setTimeout(() => this.emit(new CloseEvent('close', { code: 1000, wasClean: true })));
    }
  }
  function PatchedWebSocket(url, protocols) {
    return String(url).includes('/api/v1/') ? new DemoSocket(String(url)) : new RealWebSocket(url, protocols);
  }
  Object.assign(PatchedWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  window.WebSocket = PatchedWebSocket;
}

export async function startDemo() {
  const el = loader('Python wird geladen …');
  try {
    const { loadPyodide } = await import(/* @vite-ignore */ PYODIDE + 'pyodide.mjs');
    const py = await loadPyodide({ indexURL: PYODIDE });
    loader('Pakete werden geladen …');
    await py.loadPackage(['numpy', 'aiohttp']);
    loader('Aroio wird gestartet …');
    const zip = await (await fetch(BASE + 'aroiod.zip')).arrayBuffer();
    py.unpackArchive(zip, 'zip', { extractDir: '/home/pyodide' });
    py.FS.writeFile('/home/pyodide/aroio_demo.py', backendSource);
    const backend = py.pyimport('aroio_demo');
    // ?neu: start like a new device, with the setup guide
    await backend.start('/home/pyodide/data', !new URLSearchParams(location.search).has('neu'));
    patchFetch(backend);
    patchWebSocket(backend);
    el.remove();
    bar();
  } catch (err) {
    console.error(err);
    loader('Die Demo konnte nicht starten: ' + (err?.message || err));
    throw err;
  }
}
