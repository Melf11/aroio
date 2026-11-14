<script>
  // Restart of the Aroio: phases and a progress estimate (from the last measured
  // restart), reconnects by itself; reloads the app when the version changed.
  import { CircleCheck } from '@lucide/svelte';
  import { app } from '../lib/state.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  const expected = $derived(app.rebootExpected || 60);
  const elapsed = $derived(app.rebootSince ? Math.max(0, app.now - app.rebootSince / 1000) : 0);
  // ease towards 95 % while waiting; 100 % only when it is really back
  const pct = $derived(app.rebooting ? Math.min(95, Math.round(95 * (1 - Math.exp(-elapsed / (expected / 2.2))))) : 100);
  const phase = $derived(!app.rebooting ? 'back' : app.connected ? 'down' : elapsed < expected * 0.85 ? 'boot' : 'late');
  const text = $derived({
    down: t('Der Aroio fährt herunter …'),
    boot: t('Der Aroio startet …'),
    late: t('Dauert etwas länger als sonst … Die Seite verbindet sich von selbst.'),
    back: t('Der Aroio ist wieder da.'),
  }[phase]);
</script>

<div class="reboot" role="alertdialog" aria-modal="true" aria-labelledby="rb-t" aria-describedby="rb-s">
  <img src="/icons/logo.svg" alt="" width="64" height="64" />
  <h2 id="rb-t">{phase === 'back' ? t('Wieder da') : t('Der Aroio startet neu')}</h2>
  <div class="bar" role="progressbar" aria-label={t('Fortschritt des Neustarts')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}>
    <i style="width:{pct}%"></i>
  </div>
  <p id="rb-s" aria-live="polite">{#if phase === 'back'}<CircleCheck size={18} aria-hidden="true" class="ok" />{/if}{text}</p>
  {#if phase !== 'back'}<p class="muted small">{t('Etwa {s} Sekunden. Du musst nichts tun.', { s: Math.round(expected) })}</p>{/if}
</div>

<style>
  .reboot { position: fixed; inset: 0; z-index: 90; background: var(--bg); display: grid; place-content: center; justify-items: center; gap: 14px; text-align: center; padding: 24px; }
  .bar { width: min(320px, 80vw); height: 10px; border-radius: 5px; background: var(--surface-3); overflow: hidden; border: 1px solid var(--border-strong); }
  .bar i { display: block; height: 100%; background: var(--brand); transition: width .5s linear; }
  p { display: flex; align-items: center; gap: 8px; justify-content: center; max-width: 420px; }
  :global(.ok) { color: var(--ok); }
</style>
