import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { connect } from './lib/state.svelte.js';
import { startRouter } from './lib/router.svelte.js';

startRouter();
connect();
mount(App, { target: document.getElementById('app') });

// Service worker only where browsers allow it (HTTPS or localhost). Over plain
// http://aroio.local the app still works and installs on iOS.
if ('serviceWorker' in navigator && window.isSecureContext && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
