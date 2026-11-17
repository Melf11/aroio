<script>
  import { Wifi, Cable, Lock, LoaderCircle, Router } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Dialog from '../../components/Dialog.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const n = $derived(app.topics.network);
  const expert = $derived(app.topics.device?.expert_mode);
  let networks = $state(null), scanning = $state(false), chosen = $state(null), pw = $state(''), joining = $state(false), joinError = $state('');
  let lan = $state(null), lanErrors = $state({});
  let confirmOff = $state(false);

  async function setWifi(on) {
    confirmOff = false;
    if (!on) networks = null;
    try { await config({ network: { wifi: { enabled: on } } }); toast(on ? t('WLAN eingeschaltet.') : t('WLAN ausgeschaltet.'), 'ok'); }
    catch (e) { toast(e.message, 'danger'); }
  }
  // without a cable the app is reached over WLAN: switching it off ends this connection
  const wifiToggle = (on) => (on || n.lan.connected ? setWifi(on) : (confirmOff = true));

  async function scan() {
    scanning = true;
    try { networks = (await api.post('/network/scan')).networks.sort((a, b) => b.signal - a.signal); } catch (e) { toast(e.message, 'danger'); } finally { scanning = false; }
  }
  async function join(e) {
    e.preventDefault();
    joining = true; joinError = '';
    try { await api.post('/network/wifi', { ssid: chosen.ssid, password: pw }); toast(t('Mit „{ssid}“ verbunden.', { ssid: chosen.ssid }), 'ok'); chosen = null; pw = ''; }
    catch (err) { joinError = err.message; } finally { joining = false; }
  }
  const bars = (s) => (s > -55 ? t('sehr gut') : s > -67 ? t('gut') : s > -75 ? t('mittel') : t('schwach'));
  async function saveLan(e) {
    e.preventDefault();
    try { await config({ network: { lan: lan } }); toast(t('Gespeichert.'), 'ok'); lanErrors = {}; } catch (err) { lanErrors = { [err.field?.split('.').pop()]: err.message }; }
  }
  $effect(() => { if (expert && !lan) api.get('/config').then((c) => (lan = { ...c.network.lan })); });
</script>

<div class="page">
  <PageHeader title={t('Netzwerk')} backTo="/einstellungen" />
  {#if n}
    <ul class="list">
      <li class="st"><Cable size={22} aria-hidden="true" /><div class="grow"><strong>LAN</strong><br /><span class="muted small">{n.lan.connected ? t('Verbunden · {ip}', { ip: n.lan.address }) : t('Kein Kabel')}</span>{#if n.lan.mac}<br /><span class="muted small">MAC {n.lan.mac}</span>{/if}</div>{#if n.lan.connected}<span class="badge ok">{t('Verbunden')}</span>{/if}</li>
      <li class="st"><Wifi size={22} aria-hidden="true" /><div class="grow"><strong>WLAN</strong><br /><span class="muted small">{n.wifi.connected ? t('„{ssid}“ · {ip}', { ssid: n.wifi.ssid, ip: n.wifi.address }) : t('Nicht verbunden')}</span>{#if n.wifi.mac}<br /><span class="muted small">MAC {n.wifi.mac}</span>{/if}</div>{#if n.wifi.connected}<span class="badge ok">{t('Verbunden')}</span>{/if}</li>
      {#if n.hotspot.active}<li class="st"><Router size={22} aria-hidden="true" /><div class="grow"><strong>{t('Einrichtungs-Hotspot')}</strong><br /><span class="muted small">{n.hotspot.ssid}</span></div></li>{/if}
    </ul>
    <p class="muted small addr">{t('Adresse der App: {url}', { url: `http://${n.hostname}.local` })}</p>

    <h2 class="section-title">WLAN</h2>
    <ul class="list"><li><Toggle label={t('WLAN')} description={t('Aus, wenn der Aroio per Kabel verbunden ist: kein Funk, keine zweite Adresse im Netz. Bleibt auch nach einem Neustart aus. Ohne Kabel öffnet der Aroio trotzdem den Einrichtungs-Hotspot, damit er erreichbar bleibt.')}
                             checked={n.wifi.enabled} onchange={wifiToggle} /></li></ul>
    {#if n.wifi.enabled}
    <button class="btn top" type="button" onclick={scan} disabled={scanning}>{#if scanning}<LoaderCircle size={18} class="spin" aria-hidden="true" />{t('Suche …')}{:else}{t('Nach WLANs suchen')}{/if}</button>
    {/if}
    {#if networks && n.wifi.enabled}
      <ul class="list nets" aria-label={t('Gefundene WLANs')}>
        {#each networks as w}
          <li><button class="net" type="button" onclick={() => { chosen = w; pw = ''; joinError = ''; }}>
            <Wifi size={20} aria-hidden="true" /><span class="grow">{w.ssid}</span>
            <span class="muted small">{bars(w.signal)}</span>{#if w.secure}<Lock size={16} aria-label={t('geschützt')} />{/if}
          </button></li>
        {/each}
      </ul>
    {/if}

    {#if expert && lan}
      <h2 class="section-title">{t('LAN-Adresse (Experten)')}</h2>
      <form class="card stack" onsubmit={saveLan}>
        <ul class="list flat"><li><Toggle label={t('Automatisch (DHCP)')} checked={lan.dhcp} onchange={(v) => (lan.dhcp = v)} /></li></ul>
        {#if !lan.dhcp}
          {#each [['address', t('IP-Adresse')], ['netmask', t('Netzmaske')], ['gateway', t('Gateway')], ['dns', 'DNS']] as [k, label]}
            <div class="field"><label for={'lan-' + k}>{label}</label>
              <input id={'lan-' + k} class="input mono" inputmode="decimal" bind:value={lan[k]} aria-invalid={!!lanErrors[k]} required />
              {#if lanErrors[k]}<span class="error-text">{lanErrors[k]}</span>{/if}</div>
          {/each}
        {/if}
        <button class="btn primary" type="submit">{t('Speichern')}</button>
      </form>
    {/if}
  {/if}
</div>

<Dialog bind:open={confirmOff} title={t('WLAN ausschalten?')}>
  <p>{t('Der Aroio hat kein Kabel. Ohne WLAN verliert diese App die Verbindung. Er öffnet dann den Einrichtungs-Hotspot, darüber kannst du das WLAN wieder einrichten.')}</p>
  {#snippet actions()}
    <button class="btn" type="button" onclick={() => (confirmOff = false)}>{t('Abbrechen')}</button>
    <button class="btn danger" type="button" onclick={() => setWifi(false)}>{t('Ausschalten')}</button>
  {/snippet}
</Dialog>

<Dialog open={!!chosen} title={t('Mit „{ssid}“ verbinden', { ssid: chosen?.ssid })} onclose={() => (chosen = null)}>
  <form class="stack" onsubmit={join} id="joinform">
    {#if chosen?.secure}
      <div class="field"><label for="wpw">{t('WLAN-Passwort')}</label>
        <input id="wpw" class="input" type="password" bind:value={pw} autocomplete="off" required aria-invalid={!!joinError} /></div>
    {/if}
    {#if joinError}<p class="error-text" role="alert">{joinError}</p>{/if}
  </form>
  {#snippet actions()}
    <button class="btn primary" type="submit" form="joinform" disabled={joining}>{joining ? t('Verbinde …') : t('Verbinden')}</button>
  {/snippet}
</Dialog>

<style>
  .st { display: flex; gap: 14px; align-items: center; padding: 14px 16px; }
  .addr { margin: 8px 4px 0; }
  .top { margin-top: 12px; }
  .nets { margin-top: 12px; }
  .net { display: flex; width: 100%; gap: 12px; align-items: center; padding: 14px 16px; min-height: 56px; border: 0; background: none; text-align: left; }
  .net:hover { background: var(--surface-2); }
  .flat { border: 0; }
</style>
