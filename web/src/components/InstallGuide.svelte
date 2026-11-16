<script>
  // How to put the app on the home screen (PWA) on iPhone/iPad and Android. Shows the
  // steps for the device in use first; nothing to do when it already runs as an app.
  import { EllipsisVertical, Share, SquareCheck } from '@lucide/svelte';
  import Segmented from './Segmented.svelte';
  import { t } from '../lib/i18n.svelte.js';
  let { compact = false } = $props();

  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
  const isIos = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const installed = typeof window !== 'undefined'
    && (window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone === true);
  let platform = $state(/Android/.test(ua) ? 'android' : 'ios');
  const host = typeof location !== 'undefined' ? location.host : 'aroio.local';
  const isIp = /^\d+\.\d+\.\d+\.\d+(:\d+)?$/.test(host);
</script>

{#if installed}
  <p class="notice ok"><SquareCheck size={20} aria-hidden="true" /><span>{t('Die App läuft schon vom Home-Bildschirm.')}</span></p>
{:else}
  <div class="stack guide">
    {#if !compact}<p>{t('Lege den Aroio wie eine App auf den Home-Bildschirm deines Handys oder Tablets: Er startet dann ohne Browserleiste im Vollbild und ist mit einem Tipp da.')}</p>{/if}
    <Segmented legend={t('Gerät')} hideLegend={compact} value={platform} onchange={(v) => (platform = v)}
               options={[{ value: 'ios', label: t('iPhone / iPad') }, { value: 'android', label: 'Android' }]} />
    {#if platform === 'ios'}
      <ol class="steps">
        <li>{t('Öffne den Aroio in Safari unter „{host}“.', { host })}</li>
        <li>{t('Tippe auf „Teilen“')} <Share size={18} aria-hidden="true" /> {t('(Quadrat mit Pfeil nach oben, unten oder oben in der Leiste).')}</li>
        <li>{t('Wähle „Zum Home-Bildschirm“. Steht es nicht da, scrolle in der Liste nach unten.')}</li>
        <li>{t('Tippe auf „Hinzufügen“. Der Aroio liegt jetzt als App auf dem Home-Bildschirm.')}</li>
      </ol>
      {#if !isIos}<p class="muted small">{t('Ab iOS 16.4 geht das auch aus Chrome und Edge über deren Teilen-Menü.')}</p>{/if}
    {:else}
      <ol class="steps">
        <li>{t('Öffne den Aroio in Chrome unter „{host}“.', { host })}</li>
        <li>{t('Tippe oben rechts auf das Menü')} <EllipsisVertical size={18} aria-hidden="true" /> {t('(drei Punkte).')}</li>
        <li>{t('Wähle „Zum Startbildschirm hinzufügen“ (bei manchen Geräten „App installieren“).')}</li>
        <li>{t('Tippe auf „Hinzufügen“. Der Aroio liegt jetzt als App auf dem Startbildschirm.')}</li>
      </ol>
      {#if !isIp}<p class="muted small">{t('Findet Android „{host}“ nicht, öffne den Aroio mit seiner IP-Adresse (Einstellungen › Netzwerk) und lege dann die App an.', { host })}</p>{/if}
    {/if}
  </div>
{/if}

<style>
  .steps { margin: 0; padding-left: 1.4em; display: grid; gap: 8px; }
  .steps :global(svg) { vertical-align: -3px; }
</style>
