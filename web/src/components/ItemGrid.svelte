<script>
  // Albums/playlists as cover grid. The card is one link (opens the album);
  // the play button is a separate, labelled control.
  import { Play } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import { play, browseHref } from './library.js';
  import { t } from '../lib/i18n.svelte.js';
  let { items, scroll = false } = $props();
</script>

<ul class="grid" class:scroll>
  {#each items as item (item.id)}
    <li>
      <a class="card-link" href={item.path ? browseHref(item.path) : undefined}
         onclick={(e) => { if (!item.path) { e.preventDefault(); play(item.id); } }}>
        <span class="cover"><Cover src={item.image} size={300} radius={12} /></span>
        <span class="title ellipsis">{item.title}</span>
        {#if item.subtitle}<span class="sub ellipsis">{item.subtitle}</span>{/if}
      </a>
      {#if item.quality && item.hires}<span class="badge brand q" aria-label={t('Qualität {q}', { q: item.quality })}>{item.quality}</span>{/if}
      {#if item.playable}
        <button class="play" type="button" onclick={() => play(item.id)} aria-label={t('{title} abspielen', { title: item.title })}>
          <Play size={20} fill="currentColor" aria-hidden="true" />
        </button>
      {/if}
    </li>
  {/each}
</ul>

<style>
  .grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(150px, 42vw), 1fr)); gap: 16px 12px; }
  .grid.scroll { grid-auto-flow: column; grid-template-columns: none; grid-auto-columns: min(150px, 40vw); overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 8px; scrollbar-width: thin; }
  .grid.scroll li { scroll-snap-align: start; }
  li { position: relative; min-width: 0; }
  .card-link { display: flex; flex-direction: column; gap: 2px; color: inherit; text-decoration: none; border-radius: 14px; }
  .cover { display: block; aspect-ratio: 1; margin-bottom: 6px; }
  .cover :global(img), .cover :global(.ph) { width: 100%; height: 100%; }
  .title { font-weight: 600; }
  .sub { font-size: .875rem; color: var(--text-2); }
  .q { position: absolute; top: 8px; left: 8px; box-shadow: 0 1px 3px rgb(0 0 0 / .25); }
  .play { position: absolute; right: 8px; top: calc(100% - 4.4rem - 44px); width: 44px; height: 44px; border-radius: 50%; border: 0; background: var(--brand); color: var(--on-brand); display: grid; place-items: center; box-shadow: 0 2px 8px rgb(0 0 0 / .3); }
</style>
