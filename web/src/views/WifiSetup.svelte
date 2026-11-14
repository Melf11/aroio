<script>
  // Opens by itself in the phone's captive portal window when it joins the
  // setup hotspot. One task per screen: choose WLAN, password, then what happens next.
  import { Wifi, Lock, CircleCheck, TriangleAlert, LoaderCircle, Eye, EyeOff, Copy } from '@lucide/svelte';
  import Stepper from '../components/Stepper.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { api } from '../lib/api.js';
  import { focusHeading } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  const n = $derived(app.topics.network);
  const d = $derived(app.topics.device);
  let step = $state(0), choice = $state(null), hidden = $state(''), pw = $state(''), show = $state(false);
  let busy = $state(false), error = $state(''), sentTo = $state(null), networks = $state(null);

  const list = $derived(networks || n?.networks || []);
  const ssid = $derived(choice === '__hidden' ? hidden.trim() : choice);
  const secure = $derived(choice === '__hidden' || list.find((x) => x.ssid === choice)?.secure);
  const failed = $derived(n?.setup?.state === 'failed' ? n.setup : null);
  const address = $derived(`http://${d?.hostname || 'aroio'}.local`);
  const bars = (s) => (s > -55 ? t('sehr gut') : s > -67 ? t('gut') : s > -75 ? t('mittel') : t('schwach'));

  async function goto(i) { step = i; error = ''; await focusHeading(); }
  async function rescan() {
    try { networks = (await api.post('/network/scan')).networks; } catch (e) { toast(e.message, 'danger'); }
  }
  async function connect(e) {
    e.preventDefault();
    busy = true; error = '';
    try {
      const r = await api.post('/network/wifi', { ssid, password: secure ? pw : '' });
      sentTo = ssid;
      await goto(r.switching ? 3 : 4);
    } catch (err) { error = err.message; } finally { busy = false; }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(address); toast(t('Adresse kopiert.'), 'ok'); }
    catch { toast(t('Kopieren geht hier nicht. Bitte die Adresse abschreiben.')); }
  }
  $effect(() => { if (!n?.hotspot?.active && !list.length) rescan(); });
</script>

<div class="page wiz">
  <div class="logo"><img src="/icons/logo.svg" alt="" width="40" height="40" /><span>Aroio</span></div>
  {#if step < 3}<Stepper steps={[{ title: t('WLAN wählen') }, { title: t('Passwort') }, { title: t('Verbinden') }]} current={step} />{/if}

  {#if step === 0}
    <section class="stack">
      <h1>{t('Mit dem WLAN verbinden')}</h1>
      <p>{t('Wähle das WLAN, mit dem sich dein Aroio verbinden soll. Meist ist es dasselbe wie das deines Handys.')}</p>
      {#if failed}
        <p class="notice danger" role="alert"><TriangleAlert size={20} aria-hidden="true" />
          <span>{t('Die Verbindung mit „{s}“ hat nicht geklappt: {e} Bitte noch einmal versuchen.', { s: failed.ssid, e: failed.error })}</span></p>
      {/if}
      <fieldset>
        <legend class="sr-only">{t('Gefundene WLANs')}</legend>
        <ul class="list">
          {#each list as w (w.ssid)}
            <li><label class="opt">
              <input type="radio" name="ssid" value={w.ssid} bind:group={choice} />
              <Wifi size={20} aria-hidden="true" />
              <span class="grow name">{w.ssid}</span>
              <span class="muted small">{bars(w.signal)}</span>
              {#if w.secure}<Lock size={16} aria-label={t('geschützt')} />{/if}
            </label></li>
          {/each}
          <li><label class="opt">
            <input type="radio" name="ssid" value="__hidden" bind:group={choice} />
            <span class="grow name">{t('Anderes WLAN (Name eingeben)')}</span>
          </label></li>
        </ul>
      </fieldset>
      {#if !list.length}<p class="muted">{t('Keine WLANs gefunden.')}</p>{/if}
      {#if choice === '__hidden'}
        <div class="field"><label for="hid">{t('Name des WLANs')}</label>
          <input id="hid" class="input" bind:value={hidden} autocomplete="off" autocapitalize="none" spellcheck="false" /></div>
      {/if}
      <button class="btn primary block" type="button" disabled={!ssid} onclick={() => goto(secure ? 1 : 2)}>{t('Weiter')}</button>
      {#if !n?.hotspot?.active}<button class="btn ghost" type="button" onclick={rescan}>{t('Nach WLANs suchen')}</button>{/if}
    </section>

  {:else if step === 1}
    <form class="stack" onsubmit={(e) => { e.preventDefault(); goto(2); }}>
      <h1>{t('Passwort für „{s}“', { s: ssid })}</h1>
      <div class="field">
        <label for="pw">{t('WLAN-Passwort')}</label>
        <input id="pw" class="input" type={show ? 'text' : 'password'} bind:value={pw} autocomplete="off" autocapitalize="none" spellcheck="false" required minlength="8" />
        <span class="hint">{t('Steht oft auf der Rückseite deines Routers. Groß- und Kleinschreibung beachten.')}</span>
      </div>
      <button class="btn ghost show" type="button" aria-pressed={show} onclick={() => (show = !show)}>
        {#if show}<EyeOff size={18} aria-hidden="true" />{t('Passwort verbergen')}{:else}<Eye size={18} aria-hidden="true" />{t('Passwort anzeigen')}{/if}
      </button>
      <button class="btn primary block" type="submit">{t('Weiter')}</button>
      <button class="btn ghost" type="button" onclick={() => goto(0)}>{t('Zurück')}</button>
    </form>

  {:else if step === 2}
    <form class="stack" onsubmit={connect}>
      <h1>{t('Gleich geht’s los')}</h1>
      <p>{t('Der Aroio verlässt dann das Einrichtungs-WLAN und verbindet sich mit „{s}“. Dein Handy verliert dabei kurz die Verbindung zum Aroio. Das ist normal.', { s: ssid })}</p>
      <ol class="steps-text">
        <li>{t('Verbinde dein Handy danach wieder mit „{s}“.', { s: ssid })}</li>
        <li>{t('Öffne im Browser {a}', { a: address })}</li>
      </ol>
      {#if error}<p class="error-text" role="alert">{error}</p>{/if}
      <button class="btn primary block" type="submit" disabled={busy}>{busy ? t('Verbinde …') : t('Jetzt verbinden')}</button>
      <button class="btn ghost" type="button" onclick={() => goto(secure ? 1 : 0)}>{t('Zurück')}</button>
    </form>

  {:else if step === 3}
    <section class="stack" role="status">
      <h1>{t('Der Aroio verbindet sich')}</h1>
      <p class="row"><LoaderCircle size={22} class="spin" aria-hidden="true" />{t('Mit „{s}“ …', { s: sentTo })}</p>
      <ol class="big-steps">
        <li>{t('Öffne die WLAN-Einstellungen deines Handys und verbinde dich wieder mit „{s}“.', { s: sentTo })}</li>
        <li>{t('Öffne dann im Browser:')}
          <span class="addr"><span class="mono">{address}</span>
            <button class="btn" type="button" onclick={copy}><Copy size={16} aria-hidden="true" />{t('Kopieren')}</button></span></li>
      </ol>
      <p class="muted small">{t('Taucht „{h}“ wieder auf, hat es nicht geklappt. Verbinde dich dann erneut damit, hier steht dann der Grund.', { h: n?.hotspot?.ssid || 'Aroio-Einrichtung' })}</p>
      <p class="muted small">{t('Klappt {a} nicht (bei manchen Android-Handys), findest du die Adresse des Aroio in deinem Router.', { a: address })}</p>
    </section>

  {:else}
    <section class="stack">
      <CircleCheck size={48} class="ok-ic" aria-hidden="true" />
      <h1>{t('Verbunden mit „{s}“', { s: sentTo })}</h1>
      <a class="btn primary" href="/">{t('Zum Aroio')}</a>
    </section>
  {/if}
</div>

<style>
  .wiz { max-width: 560px; padding-top: 24px; }
  .logo { display: flex; align-items: center; gap: 10px; font-weight: 750; font-size: 1.25rem; margin-bottom: 20px; }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  .opt { display: flex; align-items: center; gap: 12px; padding: 12px 16px; min-height: 56px; cursor: pointer; }
  .opt input { width: 22px; height: 22px; accent-color: var(--brand-ink); flex: none; }
  .name { font-weight: 600; }
  .show { align-self: flex-start; }
  .steps-text, .big-steps { margin: 0; padding-left: 22px; display: flex; flex-direction: column; gap: 12px; }
  .big-steps { font-size: 1.0625rem; }
  .addr { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 6px; font-size: 1.125rem; font-weight: 650; }
  :global(.ok-ic) { color: var(--ok); }
</style>
