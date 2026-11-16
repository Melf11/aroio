<script>
  import { logoUrl } from '../lib/assets.js';
  import { Lock } from '@lucide/svelte';
  import { api } from '../lib/api.js';
  import { connect } from '../lib/state.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let pw = $state(''), error = $state(''), busy = $state(false);
  async function submit(e) {
    e.preventDefault();
    busy = true; error = '';
    try { await api.post('/auth/login', { password: pw }); await connect(); }
    catch (err) { error = err.message; }
    busy = false;
  }
</script>

<div class="login">
  <img src={logoUrl} alt="" width="64" height="64" />
  <h1>{t('Anmelden')}</h1>
  <p class="muted">{t('Dieser Aroio ist mit einem Passwort geschützt.')}</p>
  <form class="stack" onsubmit={submit}>
    <div class="field">
      <label for="lpw">{t('Passwort')}</label>
      <!-- svelte-ignore a11y_autofocus (the only field on the page) -->
      <input id="lpw" class="input" type="password" bind:value={pw} autocomplete="current-password" required autofocus aria-invalid={!!error} aria-describedby={error ? 'lpw-e' : undefined} />
      {#if error}<span id="lpw-e" class="error-text" role="alert">{error}</span>{/if}
    </div>
    <button class="btn primary" type="submit" disabled={busy || !pw}><Lock size={18} aria-hidden="true" />{t('Anmelden')}</button>
  </form>
</div>

<style>
  .login { max-width: 360px; margin: 0 auto; min-height: 100dvh; display: flex; flex-direction: column; justify-content: center; gap: 12px; padding: 24px 16px; }
  .login img { align-self: center; }
  h1 { text-align: center; margin: 0; }
  .muted { text-align: center; margin: 0 0 8px; }
</style>
