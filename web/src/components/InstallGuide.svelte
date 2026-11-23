<script>
  // How to put the app on the home screen (PWA) on iPhone/iPad and Android, or in the Dock /
  // as a window on a computer. Shows the steps for this device and browser first; nothing to
  // do when it already runs as an app. Desktop browsers offer "install" in the address bar only
  // on HTTPS; the Aroio is http://aroio.local, so the way through the menu is shown.
  import { EllipsisVertical, Share, SquareCheck } from '@lucide/svelte';
  import Segmented from './Segmented.svelte';
  import { t } from '../lib/i18n.svelte.js';
  import { browser, installed, os } from '../lib/platform.js';
  let { compact = false } = $props();

  const isIos = os === 'ios';
  let platform = $state(os === 'ios' ? 'ios' : os === 'android' ? 'android' : 'desktop');
  const host = typeof location !== 'undefined' ? location.host : 'aroio.local';
  const isIp = /^\d+\.\d+\.\d+\.\d+(:\d+)?$/.test(host);
  // desktop: this browser first, the others folded away
  const desktopOrder = ['safari', 'chrome', 'edge', 'firefox'];
  const first = desktopOrder.includes(browser) && !(browser === 'safari' && os !== 'mac') ? browser : (os === 'mac' ? 'safari' : 'chrome');
  const others = desktopOrder.filter((b) => b !== first && !(b === 'safari' && os !== 'mac'));
  const names = { safari: 'Safari', chrome: 'Chrome', edge: 'Edge', firefox: 'Firefox' };
</script>

{#snippet desktopSteps(b)}
  {#if b === 'safari'}
    <ol class="steps">
      <li>{t('Öffne den Aroio in Safari unter „{host}“.', { host })}</li>
      <li>{t('Wähle in der Menüleiste „Ablage › Zum Dock hinzufügen …“.')}</li>
      <li>{t('Klicke auf „Hinzufügen“. Der Aroio liegt jetzt im Dock und öffnet sich als eigenes Fenster.')}</li>
    </ol>
  {:else if b === 'chrome'}
    <ol class="steps">
      <li>{t('Öffne das Menü')} <span class="ico"><EllipsisVertical size={18} aria-hidden="true" /></span> {t('oben rechts und wähle „Streamen, speichern und teilen › Verknüpfung erstellen …“.')}</li>
      <li>{t('Setze das Häkchen bei „Als Fenster öffnen“ und klicke auf „Erstellen“.')}</li>
      <li>{t('Der Aroio liegt jetzt bei deinen Programmen und öffnet sich als eigenes Fenster.')}</li>
    </ol>
  {:else if b === 'edge'}
    <ol class="steps">
      <li>{t('Öffne das Menü „…“ oben rechts und wähle „Apps › Diese Website als App installieren“.')}</li>
      <li>{t('Klicke auf „Installieren“. Der Aroio öffnet sich als eigenes Fenster.')}</li>
    </ol>
  {:else}
    <p>{t('Firefox kann Seiten am Computer nicht als App anlegen. Nimm dafür Safari, Chrome oder Edge.')}</p>
  {/if}
{/snippet}


{#if installed}
  <p class="notice ok"><SquareCheck size={20} aria-hidden="true" /><span>{t('Die App läuft schon vom Home-Bildschirm.')}</span></p>
{:else}
  <div class="stack guide">
    {#if !compact}<p>{t('Lege den Aroio wie eine App auf den Home-Bildschirm deines Handys oder Tablets: Er startet dann ohne Browserleiste im Vollbild und ist mit einem Tipp da.')}</p>{/if}
    <Segmented legend={t('Gerät')} hideLegend={compact} value={platform} onchange={(v) => (platform = v)}
               options={[{ value: 'ios', label: t('iPhone / iPad') }, { value: 'android', label: 'Android' },
                         { value: 'desktop', label: t('Mac / PC') }]} />
    {#if platform === 'desktop'}
      <h3 class="browser">{names[first]}</h3>
      {@render desktopSteps(first)}
      <details class="others">
        <summary>{t('Anderer Browser')}</summary>
        {#each others as b}<h3 class="browser">{names[b]}</h3>{@render desktopSteps(b)}{/each}
      </details>
      <p class="muted small">{t('Ein Installieren-Symbol in der Adressleiste zeigen Browser nur bei Seiten mit HTTPS. Der Aroio ist im Heimnetz über http erreichbar, deshalb der Weg über das Menü – das Ergebnis ist dasselbe.')}</p>
    {:else if platform === 'ios'}
      <ol class="steps">
        <li>{t('Öffne den Aroio in Safari unter „{host}“.', { host })}</li>
        <li>{t('Tippe auf „Teilen“')} <span class="ico"><Share size={18} aria-hidden="true" /></span> {t('(Quadrat mit Pfeil nach oben, unten oder oben in der Leiste).')}</li>
        <li>{t('Wähle „Zum Home-Bildschirm“. Steht es nicht da, scrolle in der Liste nach unten.')}</li>
        <li>{t('Tippe auf „Hinzufügen“. Der Aroio liegt jetzt als App auf dem Home-Bildschirm.')}</li>
      </ol>
      {#if !isIos}<p class="muted small">{t('Ab iOS 16.4 geht das auch aus Chrome und Edge über deren Teilen-Menü.')}</p>{/if}
    {:else}
      <ol class="steps">
        <li>{t('Öffne den Aroio in Chrome unter „{host}“.', { host })}</li>
        <li>{t('Tippe oben rechts auf das Menü')} <span class="ico"><EllipsisVertical size={18} aria-hidden="true" /></span> {t('(drei Punkte).')}</li>
        <li>{t('Wähle „Zum Startbildschirm hinzufügen“ (bei manchen Geräten „App installieren“).')}</li>
        <li>{t('Tippe auf „Hinzufügen“. Der Aroio liegt jetzt als App auf dem Startbildschirm.')}</li>
      </ol>
      {#if !isIp}<p class="muted small">{t('Findet Android „{host}“ nicht, öffne den Aroio mit seiner IP-Adresse (Einstellungen › Netzwerk) und lege dann die App an.', { host })}</p>{/if}
    {/if}
  </div>
{/if}

<style>
  .steps { margin: 0; padding-left: 1.4em; display: grid; gap: 8px; }
  .ico { display: inline-flex; vertical-align: -3px; }
  .browser { font-size: 1rem; margin: 4px 0 0; }
  .others summary { cursor: pointer; padding: 10px 0; min-height: 44px; font-weight: 600; }
  .others { display: grid; gap: 8px; }
</style>
