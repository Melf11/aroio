<script>
  import { Search } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import ItemGrid from '../components/ItemGrid.svelte';
  import ItemList from '../components/ItemList.svelte';
  import { api } from '../lib/api.js';
  import { route, go } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let q = $state(route.query.get('q') || '');
  let res = $state(null), busy = $state(false);
  let timer;
  async function run(text) {
    busy = true;
    try { res = await api.get('/library/search?q=' + encodeURIComponent(text)); } finally { busy = false; }
  }
  $effect(() => { const v = q; clearTimeout(timer); if (v.trim().length >= 2) timer = setTimeout(() => { run(v); go('/musik/suche?q=' + encodeURIComponent(v), { replace: true, focus: false }); }, 300); });
  const count = $derived(res ? res.groups.reduce((n, g) => n + g.artists.length + g.albums.length + g.tracks.length, 0) : 0);
</script>

<div class="page">
  <PageHeader title={t('Suche')} backTo="/musik" />
  <div class="search" role="search">
    <Search size={20} aria-hidden="true" />
    <label class="sr-only" for="q">{t('Suchbegriff')}</label>
    <input id="q" type="search" bind:value={q} placeholder={t('Künstler, Alben, Titel …')} autocomplete="off" />
  </div>
  <p class="sr-only" role="status">{busy ? t('Sucht …') : res ? t('{n} Treffer', { n: count }) : ''}</p>
  {#if res && !res.groups.length}<p class="muted pad">{t('Nichts gefunden für „{q}“.', { q: res.query })}</p>{/if}
  {#each res?.groups || [] as g}
    <section aria-labelledby={'g-' + g.provider}>
      <h2 id={'g-' + g.provider} class="gh">{g.title}</h2>
      {#if g.artists.length}<h3 class="section-title">{t('Künstler')}</h3><ItemList items={g.artists} />{/if}
      {#if g.albums.length}<h3 class="section-title">{t('Alben')}</h3><ItemGrid items={g.albums} scroll />{/if}
      {#if g.tracks.length}<h3 class="section-title">{t('Titel')}</h3><ItemList items={g.tracks} />{/if}
    </section>
  {/each}
</div>

<style>
  .search { display: flex; align-items: center; gap: 8px; padding: 0 14px; border: 1px solid var(--border-strong); background: var(--surface); border-radius: 999px; min-height: 48px; color: var(--text-2); }
  .search:focus-within { outline: 3px solid var(--focus); outline-offset: 1px; }
  .search input { flex: 1; border: 0; background: transparent; min-height: 46px; outline: none; color: var(--text); }
  .gh { margin-top: 28px; }
  .pad { padding: 20px 4px; }
</style>
