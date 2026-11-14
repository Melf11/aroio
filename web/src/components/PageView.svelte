<script>
  // Renders one library page of any provider (see aroiod/library.py).
  import { Play, Shuffle, Heart } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import ItemGrid from './ItemGrid.svelte';
  import ItemList from './ItemList.svelte';
  import { play, favorite, browseHref } from './library.js';
  import { time } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  let { page } = $props();
  let fav = $state(null);
  const isFav = $derived(fav ?? page.header?.favorite);
</script>

{#if page.layout === 'album' && page.header}
  {@const h = page.header}
  <div class="album-head">
    <div class="art"><Cover src={h.image} size={320} radius={16} /></div>
    <div class="info">
      <p class="muted small">{h.kind === 'playlist' ? t('Playlist') : t('Album')}{#if h.year}{' · '}{h.year}{/if}{#if h.genre}{' · '}{h.genre}{/if}</p>
      {#if h.artist_path}<a class="artist" href={browseHref(h.artist_path)}>{h.subtitle?.split(' · ')[0]}</a>{:else}<p class="artist">{h.subtitle}</p>{/if}
      <p class="muted small">{#if h.count}{t('{n} Titel', { n: h.count })} · {time(h.duration)}{/if}{#if h.quality} <span class="badge brand">{h.quality}</span>{/if}</p>
      <div class="actions">
        <button class="btn primary" type="button" onclick={() => play(h.id)}><Play size={20} fill="currentColor" aria-hidden="true" />{t('Abspielen')}</button>
        <button class="btn" type="button" onclick={() => play(h.id, 'add')}><Shuffle size={18} aria-hidden="true" />{t('Hinzufügen')}</button>
        <button class="icon-btn" type="button" aria-pressed={!!isFav} onclick={async () => (fav = await favorite(h.id))} aria-label={t('Favorit')}>
          <Heart size={22} fill={isFav ? 'currentColor' : 'none'} aria-hidden="true" />
        </button>
      </div>
    </div>
  </div>
  <h2 class="sr-only">{t('Titel')}</h2>
  <ItemList items={page.items} numbered={h.kind === 'album'} parent={h.id} showCover={h.kind !== 'album'} />
{:else if page.layout === 'grid'}
  {#if page.header}
    <div class="row artist-head"><Cover src={page.header.image} size={72} radius={36} />
      <button class="btn primary" type="button" onclick={() => play(page.header.id)}><Play size={18} fill="currentColor" aria-hidden="true" />{t('Alles abspielen')}</button></div>
  {/if}
  <ItemGrid items={page.items} />
{:else}
  <ItemList items={page.items} />
{/if}

{#if !page.items?.length && page.empty}
  <div class="empty">
    <p>{page.empty}</p>
    {#if page.action}<a class="btn primary" href={page.action.route}>{page.action.label}</a>{/if}
  </div>
{/if}

<style>
  .album-head { display: flex; flex-direction: column; gap: 16px; margin-bottom: 16px; }
  .art { width: min(260px, 70vw); align-self: center; aspect-ratio: 1; }
  .art :global(img), .art :global(.ph) { width: 100%; height: 100%; box-shadow: var(--shadow); }
  .info { display: flex; flex-direction: column; gap: 6px; }
  .artist { font-weight: 650; font-size: 1.0625rem; color: var(--brand-ink); text-decoration: none; }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
  .icon-btn[aria-pressed="true"] { color: var(--danger); }
  .artist-head { margin-bottom: 16px; }
  .empty { display: flex; flex-direction: column; gap: 12px; align-items: flex-start; padding: 24px 4px; }
  @media (min-width: 700px) {
    .album-head { flex-direction: row; align-items: flex-end; }
    .art { width: 220px; align-self: auto; }
  }
</style>
