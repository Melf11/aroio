<script>
  import { WifiOff } from '@lucide/svelte';
  import Nav from './components/Nav.svelte';
  import MiniPlayer from './components/MiniPlayer.svelte';
  import Toasts from './components/Toasts.svelte';
  import RebootOverlay from './components/RebootOverlay.svelte';
  import { app } from './lib/state.svelte.js';
  import { route, match } from './lib/router.svelte.js';
  import { t, lang } from './lib/i18n.svelte.js';

  import Player from './views/Player.svelte';
  import Queue from './views/Queue.svelte';
  import MusicHome from './views/MusicHome.svelte';
  import Browse from './views/Browse.svelte';
  import Search from './views/Search.svelte';
  import Sound from './views/Sound.svelte';
  import RoomWizard from './views/RoomWizard.svelte';
  import PresetDetail from './views/PresetDetail.svelte';
  import FirImport from './views/FirImport.svelte';
  import Settings from './views/Settings.svelte';
  import SettingsGeneral from './views/settings/General.svelte';
  import SettingsNetwork from './views/settings/Network.svelte';
  import SettingsServices from './views/settings/Services.svelte';
  import SettingsService from './views/settings/Service.svelte';
  import SettingsBluetooth from './views/settings/Bluetooth.svelte';
  import SettingsUpdates from './views/settings/Updates.svelte';
  import SettingsDevice from './views/settings/Device.svelte';
  import SettingsAudio from './views/settings/Audio.svelte';
  import SettingsHardware from './views/settings/Hardware.svelte';
  import SettingsSystem from './views/settings/System.svelte';
  import Setup from './views/Setup.svelte';
  import Migration from './views/Migration.svelte';
  import WifiSetup from './views/WifiSetup.svelte';

  const routes = [
    ['/', Player], ['/warteschlange', Queue],
    ['/musik', MusicHome], ['/musik/b', Browse], ['/musik/suche', Search],
    ['/klang', Sound], ['/klang/raumkorrektur', RoomWizard], ['/klang/preset/:id', PresetDetail], ['/klang/import', FirImport],
    ['/einstellungen', Settings], ['/einstellungen/allgemein', SettingsGeneral], ['/einstellungen/netzwerk', SettingsNetwork],
    ['/einstellungen/dienste', SettingsServices], ['/einstellungen/dienste/:id', SettingsService],
    ['/einstellungen/bluetooth', SettingsBluetooth], ['/einstellungen/updates', SettingsUpdates],
    ['/einstellungen/geraet', SettingsDevice], ['/einstellungen/ton', SettingsAudio],
    ['/einstellungen/hardware', SettingsHardware], ['/einstellungen/system', SettingsSystem],
  ];

  const current = $derived.by(() => {
    for (const [pattern, component] of routes) {
      const params = match(pattern);
      if (params) return { component, params };
    }
    return { component: Player, params: {} };
  });

  const device = $derived(app.topics.device);
  const migration = $derived(app.topics.migration);
  const flow = $derived(migration?.pending ? 'migration' : device && !device.setup_completed ? 'setup' : null);

  $effect(() => {
    const th = device?.theme || 'auto';
    if (th === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.dataset.theme = th;
    document.documentElement.lang = lang();
  });
  $effect(() => {
    document.title = device?.name ? `${device.name} · Aroio` : 'Aroio';
  });
</script>

<a class="skip" href="#main">{t('Zum Inhalt springen')}</a>
<Toasts />

{#if !app.everConnected}
  <div class="splash" role="status">
    <img src="/icons/logo.svg" alt="" width="72" height="72" />
    <p>{t('Verbinde mit dem Aroio …')}</p>
  </div>
{:else if route.path === '/einrichtung'}
  <main id="main" class="flow"><WifiSetup /></main>
{:else if flow === 'migration'}
  <main id="main" class="flow"><Migration /></main>
{:else if flow === 'setup'}
  <main id="main" class="flow"><Setup /></main>
{:else}
  <div class="shell" class:on-player={route.path === '/'}>
    <aside class="side"><Nav variant="side" /></aside>
    <main id="main">
      {#if !app.connected}
        <div class="offline" role="status"><WifiOff size={18} aria-hidden="true" />{t('Keine Verbindung zum Aroio. Wird erneut versucht …')}</div>
      {/if}
      {#key route.path}
        <current.component params={current.params} />
      {/key}
    </main>
    <div class="dock">
      {#if route.path !== '/'}<div class="mini-wrap"><MiniPlayer /></div>{/if}
      <div class="bottom-nav"><Nav variant="bottom" /></div>
    </div>
  </div>
{/if}

{#if app.rebooting || app.showBack}<RebootOverlay />{/if}

<style>
  .skip { position: absolute; left: 12px; top: -60px; z-index: 100; background: var(--brand); color: var(--on-brand); padding: 10px 16px; border-radius: 10px; font-weight: 700; }
  .skip:focus { top: calc(12px + var(--safe-t)); }
  .splash { min-height: 100dvh; display: grid; place-content: center; justify-items: center; gap: 16px; color: var(--text-2); }
  .shell { min-height: 100dvh; padding-top: var(--safe-t); }
  .side { display: none; }
  main { padding-bottom: calc(var(--nav-h) + var(--mini-h) + 24px + var(--safe-b)); outline: none; }
  .shell.on-player main { padding-bottom: calc(var(--nav-h) + 16px + var(--safe-b)); }
  .dock { position: fixed; z-index: 20; left: 0; right: 0; bottom: 0; display: flex; flex-direction: column; }
  .mini-wrap { padding: 0 8px 8px; }
  .flow { min-height: 100dvh; padding-top: var(--safe-t); padding-bottom: var(--safe-b); }
  .offline { display: flex; align-items: center; gap: 8px; justify-content: center; padding: 8px 12px; background: var(--warn-soft); color: var(--warn); font-weight: 600; font-size: .9375rem; }
  :global(.spin) { animation: spin 1s linear infinite; color: var(--brand-ink); }
  @keyframes spin { to { transform: rotate(360deg); } }

  @media (min-width: 900px) {
    .shell { display: grid; grid-template-columns: var(--side-w) 1fr; }
    .side { display: block; position: sticky; top: 0; height: 100dvh; border-right: 1px solid var(--border); background: var(--surface); overflow: auto; }
    .bottom-nav { display: none; }
    .dock { left: var(--side-w); }
    .mini-wrap { padding: 0 24px 16px; max-width: 960px; margin: 0 auto; width: 100%; }
    main { padding-bottom: calc(var(--mini-h) + 32px); }
    .shell.on-player main { padding-bottom: 24px; }
  }
</style>
