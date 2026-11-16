<script>
  import { logoUrl } from '../lib/assets.js';
  import { House, Library, AudioWaveform, Settings } from '@lucide/svelte';
  import { isActive } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { app } from '../lib/state.svelte.js';
  let { variant = 'bottom' } = $props();
  const items = [
    { href: '/', label: 'Start', icon: House, match: '/' },
    { href: '/musik', label: 'Musik', icon: Library, match: '/musik' },
    { href: '/klang', label: 'Klang', icon: AudioWaveform, match: '/klang' },
    { href: '/einstellungen', label: 'Einstellungen', icon: Settings, match: '/einstellungen' },
  ];
  const updateAvailable = $derived(!!app.topics.update?.available);
</script>

<nav class={variant} aria-label={t('Hauptnavigation')}>
  {#if variant === 'side'}
    <div class="brand"><img src={logoUrl} alt="" width="32" height="32" /><span>Aroio</span></div>
  {/if}
  <ul>
    {#each items as it}
      {@const active = it.match === '/' ? isActive('/') || isActive('/warteschlange') : isActive(it.match)}
      <li>
        <a href={it.href} aria-current={active ? 'page' : undefined}>
          <span class="ic"><it.icon size={24} aria-hidden="true" />
            {#if it.href === '/einstellungen' && updateAvailable}<span class="dot" aria-hidden="true"></span>{/if}
          </span>
          <span class="lbl">{t(it.label)}{#if it.href === '/einstellungen' && updateAvailable}<span class="sr-only"> ({t('Update verfügbar')})</span>{/if}</span>
        </a>
      </li>
    {/each}
  </ul>
</nav>

<style>
  nav ul { list-style: none; margin: 0; padding: 0; display: flex; }
  a { display: flex; align-items: center; color: var(--text-2); text-decoration: none; font-weight: 600; }
  a[aria-current="page"] { color: var(--brand-ink); }
  .ic { position: relative; display: grid; place-items: center; }
  .dot { position: absolute; top: -2px; right: -4px; width: 10px; height: 10px; border-radius: 50%; background: var(--danger); border: 2px solid var(--surface); }

  .bottom { background: var(--surface); border-top: 1px solid var(--border); padding-bottom: var(--safe-b); }
  .bottom ul { justify-content: space-around; }
  .bottom li { flex: 1; }
  .bottom a { flex-direction: column; justify-content: center; gap: 2px; height: var(--nav-h); font-size: .75rem; }
  .bottom a[aria-current="page"] .ic { background: var(--brand-soft); border-radius: 999px; padding: 2px 16px; }
  .bottom a[aria-current="page"] { color: var(--brand-soft-ink); }

  .side { padding: 20px 12px; display: flex; flex-direction: column; gap: 20px; }
  .brand { display: flex; align-items: center; gap: 10px; padding: 4px 12px; font-weight: 750; font-size: 1.25rem; }
  .side ul { flex-direction: column; gap: 4px; }
  .side a { gap: 14px; padding: 12px 14px; border-radius: 12px; min-height: 48px; color: var(--text); }
  .side a:hover { background: var(--surface-2); }
  .side a[aria-current="page"] { background: var(--brand-soft); color: var(--brand-soft-ink); }
</style>
