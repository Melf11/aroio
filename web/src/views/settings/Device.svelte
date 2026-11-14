<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  let info = $state(null);
  $effect(() => { api.get('/system').then((i) => (info = i)); });
  const tone = (channel) => api.post('/system/test-tone', { channel }).then(() => toast(channel === 'L' ? t('Testton links') : channel === 'R' ? t('Testton rechts') : t('Testton beide'))).catch((e) => toast(e.message, 'danger'));
  let noise = $state(null);
  const setNoise = (channel) => api.post('/system/test-noise', { channel }).then(() => (noise = channel)).catch((e) => toast(e.message, 'danger'));
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
    <h2 class="section-title">{t('Lautsprecher prüfen')}</h2>
    <div class="row wrap">
      <button class="btn" type="button" onclick={() => tone('L')}>{t('Testton links')}</button>
      <button class="btn" type="button" onclick={() => tone('R')}>{t('Testton rechts')}</button>
    </div>
    {#if d.expert_mode}
      <h3 class="sub">{t('Rosa Rauschen (Experten)')}</h3>
      <p class="muted small">{t('Zum Einpegeln und Ausrichten der Lautsprecher. Läuft höchstens 5 Minuten. Vorsicht mit der Lautstärke.')}</p>
      <div class="row wrap">
        <button class="btn" type="button" aria-pressed={noise === 'L'} onclick={() => setNoise('L')}>{t('Links')}</button>
        <button class="btn" type="button" aria-pressed={noise === 'R'} onclick={() => setNoise('R')}>{t('Rechts')}</button>
        <button class="btn" type="button" aria-pressed={noise === 'both'} onclick={() => setNoise('both')}>{t('Beide')}</button>
        <button class="btn" type="button" disabled={!noise} onclick={() => setNoise(null)}>{t('Aus')}</button>
      </div>
    {/if}
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
  .wrap { flex-wrap: wrap; }
  .mono { font-family: var(--mono); font-weight: 500; }
  .sub { font-size: 1rem; margin: 20px 0 4px; }
  .links a { display: flex; align-items: center; min-height: 48px; padding: 0 16px; color: var(--brand-ink); }
  [aria-pressed='true'] { background: var(--brand); color: var(--on-brand); border-color: var(--brand); }
</style>
