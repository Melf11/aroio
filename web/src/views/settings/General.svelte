<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import LinkRow from '../../components/LinkRow.svelte';
  import { Smartphone } from '@lucide/svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const d = $derived(app.topics.device);
  let name = $state(app.topics.device?.name || '');
  let error = $state('');
  let pw = $state(''), pwOn = $state(false);
  $effect(() => { api.get('/auth/status').then((s) => (pwOn = s.enabled)); });
  async function setPassword(value) {
    try {
      await api.post('/security/password', { password: value });
      pwOn = !!value; pw = '';
      toast(value ? t('App-Passwort gesetzt.') : t('App-Passwort entfernt.'), 'ok');
    } catch (e) { toast(e.message, 'danger'); }
  }
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
    <h2 class="section-title">{t('Als App nutzen')}</h2>
    <ul class="list"><li><LinkRow href="/einstellungen/app" icon={Smartphone} label={t('Aroio als App einrichten')} value={t('Auf Handy, Tablet oder Computer')} /></li></ul>
    <h2 class="section-title">{t('App-Passwort')}</h2>
    <p class="muted">{pwOn ? t('Die App fragt in jedem neuen Browser nach dem Passwort.') : t('Ohne Passwort kann jeder im Heimnetz den Aroio bedienen. Das ist meist so gewollt.')}</p>
    <form class="stack" onsubmit={(e) => { e.preventDefault(); setPassword(pw); }}>
      <div class="field">
        <label for="apw">{pwOn ? t('Neues Passwort') : t('Passwort')}</label>
        <input id="apw" class="input" type="password" bind:value={pw} minlength="4" autocomplete="new-password" aria-describedby="apw-h" />
        <span id="apw-h" class="hint">{t('Mindestens 4 Zeichen.')}</span>
      </div>
      <div class="row wrap">
        <button class="btn primary" type="submit" disabled={pw.length < 4}>{pwOn ? t('Passwort ändern') : t('Passwort setzen')}</button>
        {#if pwOn}<button class="btn" type="button" onclick={() => setPassword(null)}>{t('Passwort entfernen')}</button>{/if}
      </div>
    </form>
  {/if}
</div>

<style>
  .gap { margin-top: 28px; gap: 24px; }
  .btn { align-self: flex-start; }
  .wrap { flex-wrap: wrap; }
</style>
