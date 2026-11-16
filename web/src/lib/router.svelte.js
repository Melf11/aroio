// Path router (History API). Links are plain <a href>; a click handler on the
// document turns same-origin clicks into client-side navigation. After every
// navigation focus moves to the page heading, so screen readers announce it.

import { tick } from 'svelte';

// base path of the build ("" on the Aroio, "/aroio" for the demo on GitHub Pages);
// app paths ("/klang") never contain it
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '');
const appPath = (p) => (BASE && (p === BASE || p.startsWith(BASE + '/')) ? p.slice(BASE.length) || '/' : p);

export const route = $state({ path: appPath(location.pathname), query: new URLSearchParams(location.search), depth: 0 });

function update() {
  route.path = appPath(location.pathname);
  route.query = new URLSearchParams(location.search);
}

export async function go(to, { replace = false, focus = true } = {}) {
  const url = new URL(to, location.origin + BASE + route.path);
  url.pathname = BASE + appPath(url.pathname);
  if (url.pathname + url.search === location.pathname + location.search) return;
  if (replace) history.replaceState({ depth: route.depth }, '', url);
  else history.pushState({ depth: ++route.depth }, '', url);
  update();
  if (focus) await focusHeading();
  window.scrollTo({ top: 0 });
}

export function back(fallback = '/') {
  if (route.depth > 0) history.back();
  else go(fallback, { replace: true });
}

export async function focusHeading() {
  await tick();
  const h = document.querySelector('main h1');
  if (h) {
    h.setAttribute('tabindex', '-1');
    h.focus({ preventScroll: true });
  }
}

export function startRouter() {
  history.replaceState({ depth: 0 }, '');
  window.addEventListener('popstate', (e) => {
    route.depth = e.state?.depth ?? 0;
    update();
    focusHeading();
  });
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest?.('a[href]');
    if (!a || a.target || a.hasAttribute('download') || a.getAttribute('rel') === 'external') return;
    const url = new URL(a.href);
    if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
    e.preventDefault();
    go(appPath(url.pathname) + url.search);
  });
}

export function match(pattern) {
  // "/einstellungen/dienste/:id" -> {id} or null
  const p = pattern.split('/').filter(Boolean);
  const a = route.path.split('/').filter(Boolean);
  if (p.length !== a.length) return null;
  const params = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(a[i]);
    else if (p[i] !== a[i]) return null;
  }
  return params;
}

export const isActive = (prefix) => (prefix === '/' ? route.path === '/' : route.path.startsWith(prefix));
