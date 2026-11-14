<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  let name = $state(app.topics.device?.name || '');
  let error = $state('');
  async function save(patch, msg = t('Gespeichert.')) {
    try { await config(patch); toast(msg, 'ok'); error = ''; return true; } catch (e) { error = e.message; toast(e.message, 'danger'); return false; }
  }
</script>

<div class="page">
  <PageHeader title={t('Allgemein')} backTo="/einstellungen" />
  {#if d}
    <form class="stack" onsubmit={(e) => { e.preventDefault(); save({ device: { name } }); }}>
      <div class="field">
        <label for="dname">{t('Name des Aroio')}</label>
        <input id="dname" class="input" bind:value={name} maxlength="40" required aria-describedby="dname-h" aria-invalid={!!error} />
        <span id="dname-h" class="hint">{t('Unter diesem Namen erscheint der Aroio in Spotify, AirPlay, Bluetooth, UPnP und Lyrion.')}</span>
        {#if error}<span class="error-text">{error}</span>{/if}
      </div>
      <button class="btn primary" type="submit" disabled={name === d.name}>{t('Namen speichern')}</button>
    </form>
    <div class="stack gap">
      <Segmented legend={t('Sprache')} options={[{ value: 'de', label: 'Deutsch' }, { value: 'en', label: 'English' }]} value={d.language} onchange={(v) => save({ device: { language: v } })} />
      <Segmented legend={t('Darstellung')} options={[{ value: 'auto', label: t('Automatisch') }, { value: 'light', label: t('Hell|Darstellung') }, { value: 'dark', label: t('Dunkel') }]} value={d.theme} onchange={(v) => save({ device: { theme: v } })} />
    </div>
  {/if}
</div>

<style>
  .gap { margin-top: 28px; gap: 24px; }
  .btn { align-self: flex-start; }
</style>
