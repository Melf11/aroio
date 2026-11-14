<script>
  import { X, Info, CircleCheck, TriangleAlert } from '@lucide/svelte';
  import { app, dismiss, onAnnounce } from '../lib/state.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  // Two live regions; text is set after a frame so repeated messages are read again.
  let polite = $state(''), assertive = $state('');
  onAnnounce((text, p) => {
    if (p === 'assertive') { assertive = ''; requestAnimationFrame(() => (assertive = text)); }
    else { polite = ''; requestAnimationFrame(() => (polite = text)); }
  });
  const icons = { info: Info, ok: CircleCheck, warn: TriangleAlert, danger: TriangleAlert };
</script>

<div class="sr-only" aria-live="polite" aria-atomic="true">{polite}</div>
<div class="sr-only" aria-live="assertive" aria-atomic="true">{assertive}</div>

<div class="toasts" aria-hidden="true">
  {#each app.toasts as toast (toast.id)}
    {@const Icon = icons[toast.level] || Info}
    <div class="toast {toast.level}">
      <Icon size={20} />
      <span class="grow">{toast.text}</span>
      <button class="icon-btn" tabindex="-1" onclick={() => dismiss(toast.id)} aria-label={t('Schließen')}><X size={18} /></button>
    </div>
  {/each}
</div>

<style>
  .toasts { position: fixed; z-index: 50; left: 50%; transform: translateX(-50%); top: calc(12px + var(--safe-t)); width: min(480px, calc(100vw - 24px)); display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
  .toast { pointer-events: auto; display: flex; align-items: center; gap: 10px; padding: 6px 6px 6px 14px; border-radius: 14px; background: var(--text); color: var(--bg); box-shadow: var(--shadow); font-weight: 550; animation: in .2s ease; }
  .toast.danger { background: var(--danger); color: #fff; }
  .icon-btn:hover { background: rgb(255 255 255 / .12); }
  @keyframes in { from { opacity: 0; transform: translateY(-8px); } }
</style>
