<script>
  import { SlidersHorizontal, Wifi, Radio, Bluetooth, Download, Info, Gauge, Cpu, Terminal, Speaker } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import LinkRow from '../components/LinkRow.svelte';
  import Toggle from '../components/Toggle.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { config } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  const n = $derived(app.topics.network);
  const u = $derived(app.topics.update);
  const sv = $derived(app.topics.services);
  const netText = $derived(!n ? '' : n.lan.connected ? t('LAN · {ip}', { ip: n.lan.address }) : n.wifi.connected ? t('WLAN „{ssid}“ · {ip}', { ssid: n.wifi.ssid, ip: n.wifi.address }) : n.hotspot.active ? t('Einrichtungs-Hotspot aktiv') : t('Nicht verbunden'));
  const svcText = $derived(!sv ? '' : [sv.spotify.enabled && 'Spotify', sv.tidal.enabled && 'TIDAL', sv.qobuz.enabled && 'Qobuz', sv.airplay.enabled && 'AirPlay', sv.upnp.enabled && 'UPnP', sv.roon.enabled && 'Roon', sv.netjack?.enabled && 'NetJack'].filter(Boolean).join(', '));
  const setExpert = async (v) => { try { await config({ device: { expert_mode: v } }); toast(v ? t('Expertenmodus an') : t('Expertenmodus aus')); } catch (e) { toast(e.message, 'danger'); } };
</script>

<div class="page">
  <PageHeader title={t('Einstellungen')} />
  {#if d}
    <ul class="list">
      <li><LinkRow href="/einstellungen/allgemein" icon={SlidersHorizontal} label={t('Allgemein')} value={t('{name} · Sprache, Darstellung', { name: d.name })} /></li>
      <li><LinkRow href="/einstellungen/netzwerk" icon={Wifi} label={t('Netzwerk')} value={netText} /></li>
      <li><LinkRow href="/einstellungen/dienste" icon={Radio} label={t('Dienste und Quellen')} value={svcText} /></li>
      <li><LinkRow href="/einstellungen/bluetooth" icon={Bluetooth} label="Bluetooth" value={app.topics.bluetooth?.enabled ? t('An') : t('Aus')} /></li>
      <li><LinkRow href="/einstellungen/lautsprecher" icon={Speaker} label={t('Lautsprecher prüfen')} value={t('Testton und Rauschen')} /></li>
      <li><LinkRow href="/einstellungen/updates" icon={Download} label={t('Updates')} value={t('Version {v}', { v: u?.current })} badge={u?.available ? t('Neu') : ''} badgeLevel="danger" /></li>
      <li><LinkRow href="/einstellungen/geraet" icon={Info} label={t('Über diesen Aroio')} value={`${d.model_label} · ${d.board_label}`} /></li>
    </ul>

    <ul class="list expert">
      <li><Toggle label={t('Expertenmodus')} description={t('Zeigt zusätzliche Einstellungen für Ton, DSP, Hardware und Protokolle. Für den normalen Betrieb nicht nötig.')} checked={d.expert_mode} onchange={setExpert} /></li>
    </ul>

    {#if d.expert_mode}
      <h2 class="section-title">{t('Expertenmodus')}</h2>
      <ul class="list">
        <li><LinkRow href="/einstellungen/ton" icon={Gauge} label={t('Ton')} value={t('Abtastrate, Resampler, Puffer')} /></li>
        <li><LinkRow href="/einstellungen/hardware" icon={Cpu} label={t('Hardware')} value={t('Drehgeber, Fernbedienung, Display')} /></li>
        <li><LinkRow href="/einstellungen/system" icon={Terminal} label={t('System')} value={t('Protokolle, Diagnose, SSH, Zurücksetzen')} /></li>
      </ul>
    {/if}
  {/if}
</div>

<style>
  .expert { margin-top: 20px; }
</style>
