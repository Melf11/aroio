<script>
  import { Play, Pause, SkipForward } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import { app, position, toast } from '../lib/state.svelte.js';
  import { player } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  const p = $derived(app.topics.player);
  const pos = $derived(position(p, app.now));
  const pct = $derived(p?.track?.duration ? (pos / p.track.duration) * 100 : 0);
  const act = async (a) => { try { await player(a); } catch (e) { toast(e.message, 'danger'); } };
</script>

{#if p?.track}
  <section class="mini" aria-label={t('Wiedergabe')}>
    <div class="bar" style="width:{pct}%" aria-hidden="true"></div>
    <a class="info" href="/">
      <Cover src={p.track.image} size={44} radius={8} />
      <span class="text">
        <span class="title ellipsis">{p.track.title}</span>
        <span class="sub ellipsis">{p.track.artist} · {p.source_name}</span>
        <span class="sr-only">, {t('Wiedergabe öffnen')}</span>
      </span>
    </a>
    <button class="icon-btn" type="button" onclick={() => act('toggle')} aria-label={p.state === 'playing' ? t('Pause') : t('Abspielen')}>
      {#if p.state === 'playing'}<Pause size={24} fill="currentColor" aria-hidden="true" />{:else}<Play size={24} fill="currentColor" aria-hidden="true" />{/if}
    </button>
    {#if p.can?.next}
      <button class="icon-btn" type="button" onclick={() => act('next')} aria-label={t('Nächster Titel')}><SkipForward size={22} aria-hidden="true" /></button>
    {/if}
  </section>
{/if}

<style>
  .mini { position: relative; display: flex; align-items: center; gap: 4px; padding: 8px 8px 8px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; height: var(--mini-h); }
  .bar { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--brand); transition: width .5s linear; }
  .info { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; color: inherit; text-decoration: none; }
  .text { display: flex; flex-direction: column; min-width: 0; }
  .title { font-weight: 600; }
  .sub { font-size: .8125rem; color: var(--text-2); }
</style>
