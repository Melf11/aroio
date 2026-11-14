<script>
  // Generic list rows: links (artists, folders, genres), playable items
  // (stations, playlists) and tracks. Each row has one main action and a
  // separate "more" button for the item menu.
  import { ChevronRight, EllipsisVertical, Play } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import ItemMenu from './ItemMenu.svelte';
  import { play, browseHref } from './library.js';
  import { time } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  import { app } from '../lib/state.svelte.js';
  let { items, numbered = false, parent = null, showCover = true } = $props();
  let menu = $state(null);
  const current = $derived(app.topics.player?.track?.id);
</script>

<ul class="list">
  {#each items as item, i (item.id + i)}
    <li class="row" class:now={current === item.id}>
      {#if item.kind === 'track' || item.kind === 'station' || (!item.path && item.playable)}
        <button class="main" type="button" onclick={() => (parent ? play(parent, 'play', i) : play(item.id))}>
          {#if numbered}<span class="num" aria-hidden="true">{item.number ?? i + 1}</span>
          {:else if showCover}<Cover src={item.image} size={48} />{/if}
          <span class="text">
            <span class="title ellipsis">{item.title}{#if current === item.id}<span class="sr-only"> ({t('läuft gerade')})</span>{/if}</span>
            {#if item.subtitle}<span class="sub ellipsis">{item.subtitle}</span>{/if}
          </span>
          {#if item.duration}<span class="dur" aria-label={t('Dauer {d}', { d: time(item.duration) })}>{time(item.duration)}</span>{/if}
          {#if current === item.id}<span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>{/if}
        </button>
      {:else}
        <a class="main" href={browseHref(item.path)}>
          {#if item.kind !== 'link' && item.kind !== 'genre' && item.kind !== 'folder'}<Cover src={item.image} size={48} radius={item.kind === 'artist' ? 24 : 10} />{/if}
          <span class="text">
            <span class="title ellipsis">{item.title}</span>
            {#if item.subtitle}<span class="sub ellipsis">{item.subtitle}</span>{/if}
          </span>
          <ChevronRight size={20} aria-hidden="true" class="chev" />
        </a>
      {/if}
      {#if item.playable && item.kind !== 'link'}
        {#if item.path}
          <button class="icon-btn" type="button" onclick={() => play(item.id)} aria-label={t('{title} abspielen', { title: item.title })}><Play size={20} aria-hidden="true" /></button>
        {/if}
        <button class="icon-btn" type="button" onclick={() => (menu = item)} aria-label={t('Mehr zu {title}', { title: item.title })}><EllipsisVertical size={20} aria-hidden="true" /></button>
      {/if}
    </li>
  {/each}
</ul>

<ItemMenu bind:item={menu} />

<style>
  .row { display: flex; align-items: center; padding-right: 4px; }
  .main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 8px 12px; min-height: 60px; background: none; border: 0; text-align: left; color: inherit; text-decoration: none; }
  .main:hover { background: var(--surface-2); }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .title { font-weight: 550; }
  .sub { font-size: .875rem; color: var(--text-2); }
  .num { width: 1.8em; text-align: right; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .dur { color: var(--text-2); font-size: .875rem; font-variant-numeric: tabular-nums; }
  .now .title { color: var(--brand-ink); }
  :global(.chev) { color: var(--text-2); flex: none; }
  .eq { display: flex; gap: 2px; align-items: flex-end; height: 14px; }
  .eq i { width: 3px; background: var(--brand-ink); animation: eq 1s ease-in-out infinite; }
  .eq i:nth-child(2) { animation-delay: -.3s; } .eq i:nth-child(3) { animation-delay: -.6s; }
  @keyframes eq { 0%, 100% { height: 4px; } 50% { height: 14px; } }
</style>
