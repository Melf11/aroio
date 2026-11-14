<script>
  import { Download, RotateCcw, Power } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import Dialog from '../../components/Dialog.svelte';
  import { toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  let unit = $state('system'), logs = $state(null), ssh = $state(false), confirmReset = $state(false), typed = $state('');
  $effect(() => { api.get('/system/logs?unit=' + unit).then((l) => (logs = l.lines)).catch((e) => toast(e.message, 'danger')); });
  $effect(() => { api.get('/config').then((c) => (ssh = c.security.ssh)); });
  const setSsh = async (v) => { try { ssh = (await config({ security: { ssh: v } })).security.ssh; } catch (e) { toast(e.message, 'danger'); } };
  async function reset() {
    try { await api.post('/system/factory-reset', { confirm: 'zuruecksetzen' }); confirmReset = false; toast(t('Auf Werkseinstellungen zurückgesetzt.')); }
    catch (e) { toast(e.message, 'danger'); }
  }
</script>

<div class="page">
  <PageHeader title={t('System (Experten)')} backTo="/einstellungen" />
  <Segmented legend={t('Protokoll')} value={unit} onchange={(v) => (unit = v)}
    options={[{ value: 'system', label: 'System' }, { value: 'audio', label: t('Ton') }, { value: 'lyrion', label: 'Lyrion' }, { value: 'kernel', label: 'Kernel' }]} />
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (scrollable region must be reachable by keyboard, WCAG 2.1.1) -->
  <pre class="log" role="region" tabindex="0" aria-label={t('Protokoll {u}', { u: unit })}>{(logs || []).join('\n')}</pre>
  <a class="btn" href="/api/v1/system/diagnostics" download><Download size={18} aria-hidden="true" />{t('Diagnose-Paket herunterladen')}</a>
  <p class="muted small">{t('Enthält Einstellungen (ohne Passwörter) und Zustand. Hilft dem Support bei Fehlern.')}</p>

  <ul class="list top"><li><Toggle label="SSH" description={t('Zugang für Fachleute, nur mit Schlüssel.')} checked={ssh} onchange={setSsh} /></li></ul>

  <h2 class="section-title">{t('Neustart und Zurücksetzen')}</h2>
  <div class="row wrap">
    <button class="btn" type="button" onclick={() => api.post('/system/reboot')}><Power size={18} aria-hidden="true" />{t('Neu starten')}</button>
    <button class="btn danger" type="button" onclick={() => { typed = ''; confirmReset = true; }}><RotateCcw size={18} aria-hidden="true" />{t('Werkseinstellungen')}</button>
  </div>
</div>

<Dialog bind:open={confirmReset} title={t('Alles zurücksetzen?')}>
  <p>{t('Alle Einstellungen, Klangeinstellungen, Anmeldungen und Kopplungen werden gelöscht. Tippe zur Bestätigung „zurücksetzen“.')}</p>
  <label class="sr-only" for="conf">{t('Bestätigung')}</label>
  <input id="conf" class="input" bind:value={typed} autocomplete="off" />
  {#snippet actions()}
    <button class="btn" type="button" onclick={() => (confirmReset = false)}>{t('Abbrechen')}</button>
    <button class="btn danger" type="button" disabled={typed.trim().toLowerCase() !== t('zurücksetzen')} onclick={reset}>{t('Zurücksetzen')}</button>
  {/snippet}
</Dialog>

<style>
  .log { margin: 12px 0; padding: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; max-height: 320px; overflow: auto; font: .8125rem/1.5 var(--mono); white-space: pre-wrap; }
  .top { margin-top: 20px; }
  .wrap { flex-wrap: wrap; }
</style>
