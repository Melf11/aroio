<script>
  import { Search, ChevronRight } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import ItemGrid from '../components/ItemGrid.svelte';
  import ItemList from '../components/ItemList.svelte';
  import { browseHref } from '../components/library.js';
  import { api } from '../lib/api.js';
  import { app } from '../lib/state.svelte.js';
  import { go } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  let page = $state(null), error = $state(null), q = $state('');
  const services = $derived(app.topics.services);
  const lyrion = $derived(services?.lyrion);
  async function load() {
    try { page = await api.get('/library/browse?path='); error = null; } catch (e) { error = e.message; }
  }
  $effect(() => { app.topics.services; load(); });
  const providers = $derived([
    { path: 'local', label: t('Meine Musik') },
    { path: 'favorites', label: t('Favoriten') },
    ...(services?.tidal?.enabled ? [{ path: 'tidal', label: 'TIDAL' }] : []),
    ...(services?.qobuz?.enabled ? [{ path: 'qobuz', label: 'Qobuz' }] : []),
    { path: 'radio', label: t('Radio') },
  ]);
</script>

<div class="page">
  <PageHeader title={t('Musik')} />
  {#if !page?.lyrion_off}
  <form class="search" role="search" onsubmit={(e) => { e.preventDefault(); if (q.trim()) go('/musik/suche?q=' + encodeURIComponent(q.trim())); }}>
    <Search size={20} aria-hidden="true" />
    <label class="sr-only" for="msearch">{t('Musik durchsuchen')}</label>
    <input id="msearch" type="search" bind:value={q} placeholder={t('Künstler, Alben, Titel …')} enterkeyhint="search" autocomplete="off" />
  </form>

  <nav aria-label={t('Bereiche')}>
    <ul class="chips">
      {#each providers as p}<li><a class="chip" href={browseHref(p.path)}>{p.label}</a></li>{/each}
    </ul>
  </nav>
  {/if}

  {#if page?.lyrion_off}
    <div class="empty card stack">
      <p>{page.empty}</p>
      <a class="btn primary" href={page.action.route}>{t('Lyrion einschalten')}</a>
    </div>
  {:else if lyrion && lyrion.status !== 'connected'}
    <p class="notice warn">{t('Kein Musikserver gefunden. Unter Einstellungen › Dienste › Lyrion kannst du einen eintragen oder den Musikserver auf dem Aroio starten.')}</p>
  {/if}
  {#if error}<p class="notice danger" role="alert">{error}</p>{/if}

  {#if page}
    {#each page.sections || [] as s}
      <section aria-labelledby={'sec-' + s.title}>
        <div class="sec-head">
          <h2 id={'sec-' + s.title}>{s.title}</h2>
          {#if s.path}<a href={browseHref(s.path)} class="more">{t('Alle')}<ChevronRight size={18} aria-hidden="true" /><span class="sr-only"> {s.title}</span></a>{/if}
        </div>
        {#if s.items[0]?.kind === 'station'}
          <ItemList items={s.items} />
        {:else}
          <ItemGrid items={s.items} scroll />
        {/if}
      </section>
    {/each}
  {:else if !error}
    <p class="muted" role="status">{t('Lädt …')}</p>
  {/if}
</div>

<style>
  .search { display: flex; align-items: center; gap: 8px; padding: 0 14px; border: 1px solid var(--border-strong); background: var(--surface); border-radius: 999px; min-height: 48px; color: var(--text-2); }
  .search:focus-within { outline: 3px solid var(--focus); outline-offset: 1px; }
  .search input { flex: 1; border: 0; background: transparent; min-height: 46px; outline: none; color: var(--text); }
  .chips { list-style: none; display: flex; gap: 8px; overflow-x: auto; padding: 14px 0 4px; margin: 0; scrollbar-width: none; }
  .chip { display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border-strong); color: var(--text); text-decoration: none; font-weight: 600; white-space: nowrap; }
  .chip:hover { background: var(--surface-2); }
  section { margin-top: 24px; }
  .sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .more { display: inline-flex; align-items: center; min-height: var(--tap); font-weight: 600; text-decoration: none; }
  .notice { margin-top: 12px; }
  .empty { margin-top: 8px; align-items: flex-start; }
</style>
