<script>
  import { Play, Pause, Square, SkipForward, Volume1, Volume2, VolumeX } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import LevelMeter from './LevelMeter.svelte';
  import VolumeSlider from './VolumeSlider.svelte';
  import { app, position, toast } from '../lib/state.svelte.js';
  import { player } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  const p = $derived(app.topics.player);
  const pos = $derived(position(p, app.now));
  const pct = $derived(p?.track?.duration ? (pos / p.track.duration) * 100 : 0);
  const act = async (a) => { try { await player(a); } catch (e) { toast(e.message, 'danger'); } };
  // volume: inline on wide screens, behind a button (panel above the mini player) on phones
  const canVolume = $derived(!app.topics.device?.fixed_level);
  let volOpen = $state(false), box = $state(null), volBtn = $state(null);
  function closeVol(focus = false) { volOpen = false; if (focus) volBtn?.focus(); }
  function onDocClick(e) { if (volOpen && box && !box.contains(e.target)) closeVol(); }
  function onKey(e) { if (volOpen && e.key === 'Escape') closeVol(true); }
</script>

<svelte:document onclick={onDocClick} onkeydown={onKey} />

{#if p?.track}
  <div class="box" bind:this={box}>
  {#if volOpen && canVolume}
    <div class="vol-panel" id="mini-volume">
      <VolumeSlider value={p.volume} limit={p.volume_limit} muted={p.muted} />
    </div>
  {/if}
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
    <LevelMeter variant="mini" />
    {#if canVolume}
      <div class="vol-inline"><VolumeSlider value={p.volume} limit={p.volume_limit} muted={p.muted} compact /></div>
      <button class="icon-btn vol-btn" type="button" bind:this={volBtn} onclick={() => (volOpen = !volOpen)}
              aria-expanded={volOpen} aria-controls="mini-volume" aria-label={t('Lautstärke: {v} Prozent', { v: p.volume })}>
        {#if p.muted || p.volume === 0}<VolumeX size={22} aria-hidden="true" />{:else if p.volume < 50}<Volume1 size={22} aria-hidden="true" />{:else}<Volume2 size={22} aria-hidden="true" />{/if}
      </button>
    {/if}
    {#if p.state === 'playing' && p.can?.pause}
      <button class="icon-btn" type="button" onclick={() => act('pause')} aria-label={t('Pause')}><Pause size={24} fill="currentColor" aria-hidden="true" /></button>
    {:else if p.state === 'playing' && p.can?.stop}
      <button class="icon-btn" type="button" onclick={() => act('stop')} aria-label={t('Stopp')}><Square size={20} fill="currentColor" aria-hidden="true" /></button>
    {:else if p.state !== 'playing'}
      <button class="icon-btn" type="button" disabled={!p.can?.play} onclick={() => act('play')} aria-label={t('Abspielen')}><Play size={24} fill="currentColor" aria-hidden="true" /></button>
    {/if}
    {#if p.can?.next}
      <button class="icon-btn" type="button" onclick={() => act('next')} aria-label={t('Nächster Titel')}><SkipForward size={22} aria-hidden="true" /></button>
    {/if}
  </section>
  </div>
{/if}

<style>
  .mini { position: relative; display: flex; align-items: center; gap: 4px; padding: 8px 8px 8px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; height: var(--mini-h); }
  .bar { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--brand); transition: width .5s linear; }
  .info { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; color: inherit; text-decoration: none; }
  .text { display: flex; flex-direction: column; min-width: 0; }
  .title { font-weight: 600; }
  .icon-btn:disabled { opacity: .35; cursor: default; }
  .sub { font-size: .8125rem; color: var(--text-2); }
  .box { position: relative; }
  .vol-panel { position: absolute; left: 0; right: 0; bottom: calc(100% + 8px); padding: 6px 10px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .vol-inline { display: none; width: 220px; flex: none; }
  @media (min-width: 900px) {
    .vol-inline { display: block; }
    .vol-btn, .vol-panel { display: none; }
  }
</style>
