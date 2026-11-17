<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import { app } from '../../lib/state.svelte.js';
  import { api } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  let info = $state(null);
  $effect(() => { api.get('/system').then((i) => (info = i)); });
  const n = $derived(app.topics.network);
  const up = (s) => `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
</script>

<div class="page">
  <PageHeader title={t('Über diesen Aroio')} backTo="/einstellungen" />
  {#if d}
    <dl class="card info">
      <div><dt>{t('Name')}</dt><dd>{d.name}</dd></div>
      <div><dt>{t('Modell')}</dt><dd>{d.model_label}</dd></div>
      <div><dt>{t('Rechner')}</dt><dd>{d.board_label}</dd></div>
      <div><dt>{t('Version')}</dt><dd>{d.version}</dd></div>
      <div><dt>{t('Adresse')}</dt><dd>{d.hostname}.local</dd></div>
      {#if n?.lan?.mac}<div><dt>{t('MAC-Adresse LAN')}</dt><dd class="mono">{n.lan.mac}</dd></div>{/if}
      {#if n?.wifi?.mac}<div><dt>{t('MAC-Adresse WLAN')}</dt><dd class="mono">{n.wifi.mac}</dd></div>{/if}
      {#if info}<div><dt>{t('Läuft seit')}</dt><dd>{up(info.uptime)}</dd></div><div><dt>{t('Temperatur')}</dt><dd>{info.temperature} °C</dd></div>{/if}
    </dl>
    <h2 class="section-title">{t('Hersteller')}</h2>
    <p class="muted">ABACUS electronics · AroioOS {d.version}{#if d.simulated}{' · '}{t('Simulator')}{/if}</p>
    <ul class="list links">
      <li><a href="https://www.abacus-electronics.de/produkte/streaming/aroioos.html" target="_blank" rel="noopener">{t('AroioOS auf abacus-electronics.de')}</a></li>
      <li><a href="https://www.abacus-electronics.de/forum/index.php" target="_blank" rel="noopener">{t('ABACUS-Forum')}</a></li>
      <li><a href="https://get.teamviewer.com/abacus-electronics" target="_blank" rel="noopener">{t('Fernwartung (TeamViewer) für den ABACUS-Support')}</a></li>
      <li><a href="/einstellungen/lizenzen">{t('Open-Source-Lizenzen')}</a></li>
    </ul>
  {/if}
</div>

<style>
  .info { display: grid; gap: 10px; margin: 0; }
  .info div { display: flex; justify-content: space-between; gap: 12px; }
  dt { color: var(--text-2); } dd { margin: 0; font-weight: 600; text-align: right; }
  .mono { font-family: var(--mono); font-weight: 500; }
  .links a { display: flex; align-items: center; min-height: 48px; padding: 0 16px; color: var(--brand-ink); }
</style>
