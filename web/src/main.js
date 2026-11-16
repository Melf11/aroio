import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { connect } from './lib/state.svelte.js';
import { startRouter } from './lib/router.svelte.js';

const DEMO = import.meta.env.MODE === 'demo';

async function boot() {
  // demo on GitHub Pages: start the simulated Aroio in the browser first
  if (DEMO) {
    await import('./demo/demo.css');
    await (await import('./demo/demo.js')).startDemo();
  }
  startRouter();
  connect();
  mount(App, { target: document.getElementById('app') });
}
boot();

// Service worker only where browsers allow it (HTTPS or localhost). Over plain
// http://aroio.local the app still works and installs on iOS.
if ('serviceWorker' in navigator && window.isSecureContext && import.meta.env.PROD && !DEMO) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
