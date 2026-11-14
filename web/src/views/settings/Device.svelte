<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  let info = $state(null);
  $effect(() => { api.get('/system').then((i) => (info = i)); });
  const tone = (channel) => api.post('/system/test-tone', { channel }).then(() => toast(channel === 'L' ? t('Testton links') : channel === 'R' ? t('Testton rechts') : t('Testton beide'))).catch((e) => toast(e.message, 'danger'));
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
      {#if info}<div><dt>{t('Läuft seit')}</dt><dd>{up(info.uptime)}</dd></div><div><dt>{t('Temperatur')}</dt><dd>{info.temperature} °C</dd></div>{/if}
    </dl>
    <h2 class="section-title">{t('Lautsprecher prüfen')}</h2>
    <div class="row wrap">
      <button class="btn" type="button" onclick={() => tone('L')}>{t('Testton links')}</button>
      <button class="btn" type="button" onclick={() => tone('R')}>{t('Testton rechts')}</button>
    </div>
    <h2 class="section-title">{t('Hersteller')}</h2>
    <p class="muted">ABACUS electronics · AroioOS {d.version}{#if d.simulated}{' · '}{t('Simulator')}{/if}</p>
  {/if}
</div>

<style>
  .info { display: grid; gap: 10px; margin: 0; }
  .info div { display: flex; justify-content: space-between; gap: 12px; }
  dt { color: var(--text-2); } dd { margin: 0; font-weight: 600; text-align: right; }
  .wrap { flex-wrap: wrap; }
</style>
