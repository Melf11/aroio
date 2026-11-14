<script>
  import { CircleCheck, Download, LoaderCircle } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const u = $derived(app.topics.update);
  const expert = $derived(app.topics.device?.expert_mode);
  const run = (a) => api.post('/system/' + a).catch((e) => toast(e.message, 'danger'));
  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
</script>

<div class="page">
  <PageHeader title={t('Updates')} backTo="/einstellungen" />
  {#if u}
    <div class="card stack">
      <p>{t('Installiert: Version {v}', { v: u.current })}</p>
      {#if u.state === 'checking'}
        <p class="row" role="status"><LoaderCircle size={18} class="spin" aria-hidden="true" />{t('Suche nach Updates …')}</p>
      {:else if u.state === 'installing'}
        <p role="status">{t('Update wird installiert … {p} %', { p: u.progress })}</p>
        <progress max="100" value={u.progress} aria-label={t('Fortschritt')}></progress>
        <p class="muted small">{t('Musik spielt weiter. Der Aroio bleibt währenddessen normal bedienbar.')}</p>
      {:else if u.state === 'reboot_required'}
        <p class="notice ok"><CircleCheck size={18} aria-hidden="true" />{t('Update ist installiert. Es wird nach einem Neustart aktiv.')}</p>
        <button class="btn primary" type="button" onclick={() => run('reboot')}>{t('Jetzt neu starten')}</button>
      {:else if u.available}
        <h2>{t('Version {v} ist verfügbar', { v: u.available })}</h2>
        <ul class="notes">{#each u.notes as n}<li>{n}</li>{/each}</ul>
        <button class="btn primary" type="button" onclick={() => run('update-install')}><Download size={18} aria-hidden="true" />{t('Update installieren')}</button>
        <p class="muted small">{t('Sicher: Geht beim Update etwas schief, startet der Aroio automatisch mit der bisherigen Version.')}</p>
      {:else}
        <p class="notice ok"><CircleCheck size={18} aria-hidden="true" />{u.checked ? t('Der Aroio ist auf dem neuesten Stand.') : t('Noch nicht gesucht.')}</p>
        <button class="btn" type="button" onclick={() => run('update-check')}>{t('Nach Updates suchen')}</button>
      {/if}
    </div>
    <ul class="list auto"><li><Toggle label={t('Automatisch aktualisieren')} description={t('Updates werden nachts installiert, wenn keine Musik läuft.')} checked={u.auto} onchange={(v) => save({ update: { auto: v } })} /></li></ul>
    {#if expert}
      <div class="chan"><Segmented legend={t('Update-Kanal')} value={u.channel} options={[{ value: 'stable', label: t('Stabil') }, { value: 'beta', label: 'Beta' }]} onchange={(v) => save({ update: { channel: v } })} /></div>
    {/if}
  {/if}
</div>

<style>
  .card { align-items: flex-start; }
  progress { width: 100%; height: 10px; accent-color: var(--brand-ink); }
  .notes { margin: 0; padding-left: 20px; }
  .auto { margin-top: 16px; }
  .chan { margin-top: 20px; }
</style>
