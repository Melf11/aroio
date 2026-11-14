<script>
  // First start: language, name, network, services, speaker test. Each step one task.
  import { Cable, CircleCheck, FileUp, Wifi } from '@lucide/svelte';
  import Stepper from '../components/Stepper.svelte';
  import Segmented from '../components/Segmented.svelte';
  import Toggle from '../components/Toggle.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { api, config } from '../lib/api.js';
  import { focusHeading } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  const d = $derived(app.topics.device);
  const n = $derived(app.topics.network);
  const sv = $derived(app.topics.services);
  let step = $state(0);
  let name = $state(app.topics.device?.name || 'Aroio');
  let nameError = $state('');
  let networks = $state(null), ssid = $state(''), pw = $state(''), joinError = $state(''), joining = $state(false);
  const steps = $derived([{ title: t('Willkommen') }, { title: t('Name') }, { title: t('Netzwerk') }, { title: t('Dienste') }, { title: t('Soundkarte') }, { title: t('Lautsprecher') }]);
  let hw = $state(null), driver = $state(null);
  async function loadHw() { hw = await api.get('/audio/hardware'); driver ??= hw.driver; }
  $effect(() => { if (step === 4 && !hw) loadHw(); });
  async function saveDriver() {
    try {
      await config({ hardware: { dac_driver: driver } });
      hw = await api.get('/audio/hardware');
      goto(5);
    } catch (e) { toast(e.message, 'danger'); }
  }
  const needsReboot = $derived(!!d?.reboot_required);
  async function finishAndReboot() {
    try { await api.post('/system/setup-complete'); await api.post('/system/reboot'); } catch (e) { toast(e.message, 'danger'); }
  }

  async function goto(i) { step = i; await focusHeading(); }
  async function saveName() {
    try { await config({ device: { name } }); nameError = ''; goto(2); } catch (e) { nameError = e.message; }
  }
  async function scan() { networks = (await api.post('/network/scan')).networks; }
  async function join(e) {
    e.preventDefault(); joining = true; joinError = '';
    try { await api.post('/network/wifi', { ssid, password: pw }); } catch (err) { joinError = err.message; } finally { joining = false; }
  }
  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
  async function finish() {
    try { await api.post('/system/setup-complete'); toast(t('Einrichtung abgeschlossen.'), 'ok'); } catch (e) { toast(e.message, 'danger'); }
  }
  async function upload(e) {
    const form = new FormData();
    for (const f of e.currentTarget.files) form.append('file', f, f.name);
    try { await api.upload('/migration/upload', form); } catch (err) { toast(err.message, 'danger'); }
  }
  const tone = (channel) => api.post('/system/test-tone', { channel });
  $effect(() => { if (step === 2 && n && !n.lan.connected && !networks) scan(); });
</script>

<div class="page wiz">
  <div class="logo"><img src="/icons/logo.svg" alt="" width="40" height="40" /><span>Aroio</span></div>
  <Stepper {steps} current={step} />

  {#if step === 0}
    <section class="stack">
      <h1>{t('Willkommen beim Aroio')}</h1>
      <p>{t('In wenigen Schritten ist dein Aroio bereit. Du kannst alles später in den Einstellungen ändern.')}</p>
      <Segmented legend={t('Sprache')} value={d?.language} options={[{ value: 'de', label: 'Deutsch' }, { value: 'en', label: 'English' }]} onchange={(v) => save({ device: { language: v } })} />
      <button class="btn primary block" type="button" onclick={() => goto(1)}>{t('Los geht’s')}</button>
      <div class="card stack migrate">
        <h2>{t('Hast du einen älteren Aroio?')}</h2>
        <p class="muted">{t('Wähle die Datei „userconfig.txt“ von der alten Speicherkarte (oder eine ZIP-Datei mit dem ganzen Inhalt inklusive Filtern). Der Aroio übernimmt dann deine Einstellungen.')}</p>
        <label class="btn"><FileUp size={18} aria-hidden="true" />{t('Einstellungen übernehmen')}<input class="sr-only" type="file" accept=".txt,.zip,.dbl" multiple onchange={upload} /></label>
      </div>
    </section>
  {:else if step === 1}
    <form class="stack" onsubmit={(e) => { e.preventDefault(); saveName(); }}>
      <h1>{t('Wie soll dein Aroio heißen?')}</h1>
      <p>{t('Unter diesem Namen findest du ihn in Spotify, AirPlay und Bluetooth. Zum Beispiel der Raum, in dem er steht.')}</p>
      <div class="field"><label for="sn">{t('Name')}</label>
        <input id="sn" class="input" bind:value={name} maxlength="40" required aria-invalid={!!nameError} />
        {#if nameError}<span class="error-text" role="alert">{nameError}</span>{/if}</div>
      <div class="chips">{#each [t('Wohnzimmer'), t('Küche'), t('Arbeitszimmer'), t('Schlafzimmer')] as s}<button class="btn" type="button" onclick={() => (name = s)}>{s}</button>{/each}</div>
      <button class="btn primary block" type="submit">{t('Weiter')}</button>
    </form>
  {:else if step === 2}
    <section class="stack">
      <h1>{t('Netzwerk')}</h1>
      {#if n?.lan.connected}
        <p class="notice ok"><Cable size={20} aria-hidden="true" /><span>{t('Der Aroio ist per Kabel verbunden. Alles bereit.')}</span></p>
      {:else if n?.wifi.connected}
        <p class="notice ok"><Wifi size={20} aria-hidden="true" /><span>{t('Verbunden mit „{s}“.', { s: n.wifi.ssid })}</span></p>
      {:else}
        <p>{t('Wähle dein WLAN. Oder stecke ein Netzwerkkabel ein, das ist für Musik in hoher Auflösung am zuverlässigsten.')}</p>
        <form class="stack" onsubmit={join}>
          <div class="field"><label for="ss">{t('WLAN')}</label>
            <select id="ss" class="input" bind:value={ssid} required>
              <option value="" disabled>{networks ? t('Bitte wählen') : t('Suche …')}</option>
              {#each networks || [] as w}<option value={w.ssid}>{w.ssid}</option>{/each}
            </select></div>
          <div class="field"><label for="sp">{t('WLAN-Passwort')}</label>
            <input id="sp" class="input" type="password" bind:value={pw} autocomplete="off" aria-invalid={!!joinError} />
            {#if joinError}<span class="error-text" role="alert">{joinError}</span>{/if}</div>
          <button class="btn" type="submit" disabled={joining || !ssid}>{joining ? t('Verbinde …') : t('Verbinden')}</button>
        </form>
      {/if}
      <button class="btn primary block" type="button" disabled={!n?.lan.connected && !n?.wifi.connected} onclick={() => goto(3)}>{t('Weiter')}</button>
    </section>
  {:else if step === 3}
    <section class="stack">
      <h1>{t('Wie möchtest du Musik hören?')}</h1>
      <p class="muted">{t('Wähle aus, was du nutzt. Alles andere bleibt aus.')}</p>
      {#if sv}
        <ul class="list">
          <li><Toggle label={t('Lyrion (eigene Musiksammlung, Radio)')} description={t('Nur, wenn du einen Lyrion-Server hast oder einen auf dem Aroio möchtest.')}
                      checked={app.topics.sources.find((s) => s.id === 'lms')?.enabled} onchange={(v) => save({ sources: { lms: { enabled: v } } })} /></li>
          <li><Toggle label="Spotify" checked={sv.spotify.enabled} onchange={(v) => save({ sources: { spotify: { enabled: v } } })} /></li>
          <li><Toggle label="TIDAL" checked={sv.tidal.enabled} onchange={(v) => save({ services: { tidal: { enabled: v } } })} /></li>
          <li><Toggle label="Qobuz" checked={sv.qobuz.enabled} onchange={(v) => save({ services: { qobuz: { enabled: v } } })} /></li>
          <li><Toggle label={t('AirPlay (iPhone, Mac)')} checked={sv.airplay.enabled} onchange={(v) => save({ sources: { airplay: { enabled: v } } })} /></li>
          <li><Toggle label="Bluetooth" checked={app.topics.sources.find((s) => s.id === 'bluetooth')?.enabled} onchange={(v) => save({ sources: { bluetooth: { enabled: v } } })} /></li>
          <li><Toggle label="UPnP / DLNA" checked={sv.upnp.enabled} onchange={(v) => save({ sources: { upnp: { enabled: v } } })} /></li>
        </ul>
        <p class="muted small">{t('Anmelden bei TIDAL und Qobuz kannst du danach unter Einstellungen › Dienste.')}</p>
      {/if}
      <button class="btn primary block" type="button" onclick={() => goto(4)}>{t('Weiter')}</button>
    </section>
  {:else if step === 4}
    <form class="stack" onsubmit={(e) => { e.preventDefault(); saveDriver(); }}>
      <h1>{t('Welche Soundkarte steckt im Aroio?')}</h1>
      <p class="muted">{t('Bei einem Aroio von ABACUS ist es der Aroio DAC. Bei einem eigenen Raspberry Pi wähle die Aufsteckkarte, die du verwendest.')}</p>
      {#if hw}
        <fieldset>
          <legend class="sr-only">{t('Soundkarte')}</legend>
          <ul class="list">
            {#each hw.drivers as dr (dr.id)}
              <li><label class="opt">
                <input type="radio" name="drv" value={dr.id} bind:group={driver} />
                <span class="text"><span class="name">{t(dr.label)}</span>{#if dr.hint}<span class="muted small">{t(dr.hint)}</span>{/if}</span>
              </label></li>
            {/each}
          </ul>
        </fieldset>
      {:else}<p class="muted" role="status">{t('Lädt …')}</p>{/if}
      <button class="btn primary block" type="submit" disabled={!driver}>{t('Weiter')}</button>
    </form>
  {:else if step === 5}
    <section class="stack">
      {#if needsReboot}
        <h1>{t('Fast fertig')}</h1>
        <p>{t('Damit die gewählte Soundkarte aktiv wird, startet der Aroio jetzt einmal neu. Danach kannst du die Lautsprecher unter Einstellungen › Über diesen Aroio prüfen.')}</p>
      {:else}
        <h1>{t('Lautsprecher prüfen')}</h1>
        <p>{t('Spiele einen kurzen Ton links und rechts. Kommt er aus dem richtigen Lautsprecher?')}</p>
        <div class="row wrap"><button class="btn" type="button" onclick={() => tone('L')}>{t('Ton links')}</button><button class="btn" type="button" onclick={() => tone('R')}>{t('Ton rechts')}</button></div>
        <p class="muted small">{t('Falls links und rechts vertauscht sind: Kabel am Verstärker tauschen.')}</p>
      {/if}
      <div class="card stack">
        <CircleCheck size={28} class="ok-ic" aria-hidden="true" />
        <h2>{t('Fertig eingerichtet')}</h2>
        <p>{t('Tipp: Mit einem Messmikrofon kann der Aroio deinen Raum einmessen und den Klang verbessern (Klang › Raum einmessen).')}</p>
      </div>
      {#if needsReboot}
        <button class="btn primary block" type="button" onclick={finishAndReboot}>{t('Neu starten und fertig')}</button>
      {:else}
        <button class="btn primary block" type="button" onclick={finish}>{t('Zum Aroio')}</button>
      {/if}
    </section>
  {/if}
  {#if step > 0}<button class="btn ghost" type="button" onclick={() => goto(step - 1)}>{t('Zurück')}</button>{/if}
</div>

<style>
  .wiz { max-width: 560px; padding-top: 24px; }
  .logo { display: flex; align-items: center; gap: 10px; font-weight: 750; font-size: 1.25rem; margin-bottom: 20px; }
  .migrate { margin-top: 24px; align-items: flex-start; }
  label.btn { cursor: pointer; }
  label.btn:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  .opt { display: flex; align-items: center; gap: 12px; padding: 12px 16px; min-height: 56px; cursor: pointer; }
  .opt input { width: 22px; height: 22px; accent-color: var(--brand-ink); flex: none; }
  .text { display: flex; flex-direction: column; }
  .name { font-weight: 600; }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .wrap { flex-wrap: wrap; }
  :global(.ok-ic) { color: var(--ok); }
  .btn.ghost { margin-top: 12px; }
</style>
