<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import LinkRow from '../../components/LinkRow.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const sv = $derived(app.topics.services);
  const d = $derived(app.topics.device);
  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
  const status = (s) => (!s.enabled ? t('Aus') : s.logged_in ? t('Angemeldet') : t('Nicht angemeldet'));
  const lyrionText = $derived(!sv ? '' : sv.lyrion.status !== 'connected' ? t('Kein Server gefunden') : sv.lyrion.mode === 'local' ? t('Läuft auf diesem Aroio') : t('Server {s}', { s: sv.lyrion.server }));
</script>

<div class="page">
  <PageHeader title={t('Dienste und Quellen')} backTo="/einstellungen" />
  {#if sv && d}
    <h2 class="section-title">{t('Streamingdienste')}</h2>
    <ul class="list">
      <li><LinkRow href="/einstellungen/dienste/spotify" label="Spotify Connect" value={!sv.spotify.enabled ? t('Aus') : sv.spotify.status === 'ready' ? t('Bereit') : t('Einrichtung nötig')} badge={sv.spotify.enabled && sv.spotify.status !== 'ready' ? t('Einrichten') : ''} badgeLevel="warn" /></li>
      <li><LinkRow href="/einstellungen/dienste/tidal" label="TIDAL" value={status(sv.tidal)} /></li>
      <li><LinkRow href="/einstellungen/dienste/qobuz" label="Qobuz" value={status(sv.qobuz)} /></li>
    </ul>

    <h2 class="section-title">{t('Musikbibliothek')}</h2>
    <ul class="list">
      <li><LinkRow href="/einstellungen/dienste/lyrion" label={t('Lyrion Music Server')} value={lyrionText} /></li>
    </ul>

    <h2 class="section-title">{t('Abspielen vom Handy oder Computer')}</h2>
    <ul class="list">
      <li><Toggle label="AirPlay" description={t('Von iPhone, iPad und Mac. Auch Multiroom mit anderen AirPlay-2-Lautsprechern.')} checked={sv.airplay.enabled} onchange={(v) => save({ sources: { airplay: { enabled: v } } })} /></li>
      <li><Toggle label="UPnP / DLNA" description={t('Für Apps wie BubbleUPnP, mConnect oder Linn Kazoo.')} checked={sv.upnp.enabled} onchange={(v) => save({ sources: { upnp: { enabled: v } } })} /></li>
      <li><Toggle label="Bluetooth" description={t('Handy direkt verbinden. Koppeln unter Einstellungen › Bluetooth.')} checked={app.topics.sources.find((s) => s.id === 'bluetooth')?.enabled} onchange={(v) => save({ sources: { bluetooth: { enabled: v } } })} /></li>
      <li><Toggle label="Roon" description={t('Der Aroio erscheint in Roon als Zone (Roon Bridge).')} checked={sv.roon.enabled} onchange={(v) => save({ sources: { roon: { enabled: v } } })} /></li>
      {#if d.has_input || d.expert_mode}
        <li><Toggle label={t('Eingang')} description={t('Analoger oder digitaler Eingang der Soundkarte.')} checked={app.topics.sources.find((s) => s.id === 'input')?.enabled ?? false} onchange={(v) => save({ sources: { input: { enabled: v } } })} /></li>
      {/if}
    </ul>
  {/if}
</div>
