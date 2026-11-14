<script>
  import { CircleCheck, ExternalLink, LoaderCircle } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  let { params } = $props();
  const id = $derived(params.id);
  const sv = $derived(app.topics.services);
  const d = $derived(app.topics.device);
  const titles = { spotify: 'Spotify Connect', tidal: 'TIDAL', qobuz: 'Qobuz', lyrion: 'Lyrion Music Server' };
  let key = $state(''), email = $state(''), password = $state(''), err = $state(''), busy = $state(false), server = $state(''), local = $state('auto');
  $effect(() => { if (id === 'lyrion') api.get('/config').then((c) => { server = c.sources.lms.server; local = c.services.lyrion_local; }); });

  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
  async function login(data) {
    busy = true; err = '';
    try { await api.post(`/services/${id}/login`, data); if (id !== 'tidal') toast(t('Angemeldet.'), 'ok'); }
    catch (e) { err = e.message; } finally { busy = false; }
  }
  const logout = () => api.post(`/services/${id}/logout`).then(() => toast(t('Abgemeldet.'))).catch((e) => toast(e.message, 'danger'));
</script>

<div class="page">
  <PageHeader title={titles[id] || id} backTo="/einstellungen/dienste" />
  {#if sv && d}
    {#if id === 'spotify'}
      {@const s = sv.spotify}
      <ul class="list"><li><Toggle label="Spotify Connect" checked={s.enabled} onchange={(v) => save({ sources: { spotify: { enabled: v } } })} /></li></ul>
      {#if s.enabled}
        {#if s.status === 'ready'}
          <p class="notice ok big"><CircleCheck size={20} aria-hidden="true" /><span>{t('Bereit. Öffne Spotify auf deinem Handy und wähle „{name}“ als Lautsprecher.', { name: d.name })}</span></p>
          {#if d.expert_mode}<p class="muted small">{t('Verfahren: {m}', { m: s.method })}{#if s.key_expires}{' · '}{t('Schlüssel gültig bis {d}', { d: s.key_expires })}{/if}</p>{/if}
        {:else}
          <div class="stack">
            <p class="notice warn">{t('Dein Spotify-Konto braucht einen eigenen Schlüssel. Das ist einmalig und dauert etwa 5 Minuten.')}</p>
            <ol class="howto">
              <li>{t('Öffne developer.spotify.com und melde dich mit deinem Spotify-Premium-Konto an.')} <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener external">{t('Seite öffnen')}<ExternalLink size={14} aria-hidden="true" /><span class="sr-only"> ({t('öffnet in neuem Fenster')})</span></a></li>
              <li>{t('Lege eine neue App an und wähle „Soloist“.')}</li>
              <li>{t('Kopiere den angezeigten Schlüssel und füge ihn hier ein.')}</li>
            </ol>
            <form class="stack" onsubmit={(e) => { e.preventDefault(); login({ soloist_key: key }); }}>
              <div class="field"><label for="skey">{t('Schlüssel')}</label>
                <input id="skey" class="input mono" bind:value={key} autocomplete="off" spellcheck="false" required aria-invalid={!!err} />
                {#if err}<span class="error-text" role="alert">{err}</span>{/if}</div>
              <button class="btn primary" type="submit" disabled={busy}>{t('Speichern')}</button>
            </form>
          </div>
        {/if}
      {/if}

    {:else if id === 'tidal'}
      {@const s = sv.tidal}
      <ul class="list"><li><Toggle label={t('TIDAL in der Musikbibliothek')} checked={s.enabled} onchange={(v) => save({ services: { tidal: { enabled: v } } })} /></li></ul>
      {#if s.enabled}
        {#if s.logged_in}
          <p class="notice ok big"><CircleCheck size={20} aria-hidden="true" /><span>{t('Angemeldet als {a}', { a: s.account })}</span></p>
          <a class="btn" href="/musik/b?path=tidal">{t('TIDAL öffnen')}</a>
          <button class="btn ghost" type="button" onclick={logout}>{t('Abmelden')}</button>
        {:else if s.login}
          <div class="card stack" role="status">
            <p>{t('Öffne {url} auf deinem Handy oder Computer und gib diesen Code ein:', { url: s.login.url })}</p>
            <p class="code" aria-label={t('Code {c}', { c: s.login.code.split('').join(' ') })}>{s.login.code}</p>
            <p class="row muted"><LoaderCircle size={18} class="spin" aria-hidden="true" />{t('Warte auf die Anmeldung …')}</p>
          </div>
        {:else}
          <p>{t('Melde dich mit deinem TIDAL-Konto an. Danach findest du deine Alben, Playlisten und Mixe unter Musik.')}</p>
          <button class="btn primary" type="button" disabled={busy} onclick={() => login({ action: 'start' })}>{t('Bei TIDAL anmelden')}</button>
          {#if err}<p class="error-text" role="alert">{err}</p>{/if}
        {/if}
      {/if}

    {:else if id === 'qobuz'}
      {@const s = sv.qobuz}
      <ul class="list"><li><Toggle label={t('Qobuz in der Musikbibliothek')} checked={s.enabled} onchange={(v) => save({ services: { qobuz: { enabled: v } } })} /></li></ul>
      {#if s.enabled}
        {#if s.logged_in}
          <p class="notice ok big"><CircleCheck size={20} aria-hidden="true" /><span>{t('Angemeldet als {a}', { a: s.account })}</span></p>
          <a class="btn" href="/musik/b?path=qobuz">{t('Qobuz öffnen')}</a>
          <button class="btn ghost" type="button" onclick={logout}>{t('Abmelden')}</button>
        {:else}
          <form class="stack" onsubmit={(e) => { e.preventDefault(); login({ email, password }); }}>
            <div class="field"><label for="qe">{t('E-Mail')}</label><input id="qe" class="input" type="email" bind:value={email} autocomplete="username" required /></div>
            <div class="field"><label for="qp">{t('Passwort')}</label><input id="qp" class="input" type="password" bind:value={password} autocomplete="current-password" required aria-invalid={!!err} />
              {#if err}<span class="error-text" role="alert">{err}</span>{/if}</div>
            <button class="btn primary" type="submit" disabled={busy}>{t('Anmelden')}</button>
          </form>
        {/if}
      {/if}

    {:else if id === 'lyrion'}
      {@const l = sv.lyrion}
      {@const lyrionOn = app.topics.sources.find((x) => x.id === 'lms')?.enabled}
      <ul class="list"><li><Toggle label={t('Lyrion verwenden')} description={t('Aus, wenn du keinen Lyrion-Server hast. Musik kommt dann über Spotify, AirPlay, Bluetooth oder UPnP.')}
                                   checked={lyrionOn} onchange={(v) => save({ sources: { lms: { enabled: v } } })} /></li></ul>
      {#if lyrionOn}
      <div class="stack">
        {#if l.status === 'connected'}
          <p class="notice ok big"><CircleCheck size={20} aria-hidden="true" /><span>{l.mode === 'local' ? t('Der Musikserver läuft auf diesem Aroio.') : t('Verbunden mit {s}{auto}', { s: l.server, auto: l.found_automatically ? ' (' + t('automatisch gefunden') + ')' : '' })}</span></p>
        {:else}
          <p class="notice warn">{t('Es wurde kein Lyrion-Server im Netzwerk gefunden.')}</p>
        {/if}
        <p class="muted">{t('Lyrion (früher Logitech Media Server) verwaltet deine Musiksammlung. Die App zeigt sie unter Musik. Die TIDAL- und Qobuz-Anbindung läuft ebenfalls darüber.')}</p>
        <Segmented legend={t('Musikserver auf diesem Aroio')} value={local}
          options={[{ value: 'auto', label: t('Automatisch') }, { value: 'on', label: t('Immer') }, { value: 'off', label: t('Nie') }]}
          onchange={(v) => { local = v; save({ services: { lyrion_local: v } }); }} />
        <p class="muted small">{t('Automatisch: Der Aroio startet seinen eigenen Server nur, wenn im Netzwerk keiner gefunden wird.')}</p>
        <form class="field" onsubmit={(e) => { e.preventDefault(); save({ sources: { lms: { server } } }).then(() => toast(t('Gespeichert.'), 'ok')); }}>
          <label for="lsrv">{t('Server-Adresse (optional)')}</label>
          <div class="row"><input id="lsrv" class="input mono" bind:value={server} placeholder="192.168.1.10" autocomplete="off" /><button class="btn" type="submit">{t('Speichern')}</button></div>
          <span class="hint">{t('Leer lassen, damit der Aroio den Server selbst findet.')}</span>
        </form>
      </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .page :global(.list) { margin-bottom: 16px; }
  .big { font-weight: 600; margin-bottom: 12px; }
  .howto { margin: 0; padding-left: 22px; display: flex; flex-direction: column; gap: 10px; }
  .howto a { display: inline-flex; gap: 4px; align-items: center; font-weight: 600; }
  .code { font-family: var(--mono); font-size: 2.25rem; letter-spacing: .25em; font-weight: 700; text-align: center; padding: 8px; background: var(--surface-2); border-radius: 12px; }
  .btn { align-self: flex-start; }
</style>
