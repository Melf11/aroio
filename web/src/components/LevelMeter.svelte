<script>
  // Live level meter (peak + RMS per channel, dBFS) with meter ballistics:
  // instant attack, 20 dB/s release, peak hold 1.5 s, clip indicator.
  // Decorative for screen readers (it changes 15 times per second); the
  // label says what it is.
  import { onMount } from 'svelte';
  import { levels, useLevels } from '../lib/levels.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  let { variant = 'full' } = $props();
  const MIN = -60;
  let shown = $state({ rms: [MIN, MIN], peak: [MIN, MIN], hold: [MIN, MIN], clip: false });
  let holdAt = [0, 0], clipAt = -Infinity, last = performance.now(), frame;   // -Infinity: no clip at start

  onMount(() => {
    const stop = useLevels();
    const step = (now) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const stale = now - levels.at > 500;                // no data: fall to silence
      const next = { rms: [], peak: [], hold: [...shown.hold], clip: shown.clip };
      for (let i = 0; i < 2; i++) {
        const r = stale ? MIN : Math.max(MIN, levels.rms[i]);
        const p = stale ? MIN : Math.max(MIN, levels.peak[i]);
        next.rms[i] = r > shown.rms[i] ? r : Math.max(r, shown.rms[i] - 20 * dt);
        next.peak[i] = p > shown.peak[i] ? p : Math.max(p, shown.peak[i] - 20 * dt);
        if (p >= next.hold[i] || now - holdAt[i] > 1500) { next.hold[i] = p; holdAt[i] = now; }
        if (!stale && levels.peak[i] > -0.3) clipAt = now;
      }
      next.clip = now - clipAt < 2000;
      shown = next;
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(frame); stop(); };
  });

  const pct = (db) => Math.max(0, Math.min(100, ((db - MIN) / -MIN) * 100));
  const ticks = [-40, -20, -10, -6, -3, 0];
</script>

{#if variant === 'mini'}
  <span class="mini" role="img" aria-label={t('Pegelanzeige')}>
    {#each [0, 1] as i}
      <span class="track v"><i class="dim" style="bottom:{pct(shown.rms[i])}%"></i><i class="off" style="bottom:{pct(shown.peak[i])}%"></i></span>
    {/each}
  </span>
{:else}
  <div class="full" role="img" aria-label={t('Pegelanzeige links und rechts')}>
    {#each [0, 1] as i}
      <div class="row">
        <span class="ch" aria-hidden="true">{i ? 'R' : 'L'}</span>
        <span class="track h">
          <i class="dim" style="left:{pct(shown.rms[i])}%"></i>
          <i class="off" style="left:{pct(shown.peak[i])}%"></i>
          <i class="hold" style="left:{pct(shown.hold[i])}%"></i>
        </span>
      </div>
    {/each}
    <div class="scale" aria-hidden="true">
      {#each ticks as d}<span style="left:{pct(d)}%">{d}</span>{/each}
    </div>
    {#if shown.clip}<span class="clip">{t('Übersteuerung')}</span>{/if}
  </div>
{/if}

<style>
  /* The coloured zones are drawn once over the whole track (normal / from -6 dB / from -1 dB);
     the unlit part is covered: "dim" between RMS and peak, "off" above the peak. */
  .track { position: relative; overflow: hidden; border-radius: 3px; display: block; }
  .track.h { flex: 1; height: 8px; background: linear-gradient(to right, var(--brand) 0 90%, var(--warn) 90% 98.3%, var(--danger) 98.3%); }
  .track.v { width: 4px; height: 100%; background: linear-gradient(to top, var(--brand) 0 90%, var(--warn) 90% 98.3%, var(--danger) 98.3%); }
  .dim, .off { position: absolute; background: var(--surface-3); }
  .dim { opacity: .55; }
  .h .dim, .h .off { top: 0; bottom: 0; right: 0; }
  .v .dim, .v .off { left: 0; right: 0; top: 0; }
  .hold { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--text); }
  .full { position: relative; display: flex; flex-direction: column; gap: 5px; }
  .row { display: flex; align-items: center; gap: 8px; }
  .ch { width: 1em; font-size: .75rem; font-weight: 700; color: var(--text-2); }
  .scale { position: relative; height: 14px; margin-left: calc(1em + 8px); font-size: .625rem; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .scale span { position: absolute; transform: translateX(-50%); }
  .scale span:last-child { transform: translateX(-100%); }
  .clip { position: absolute; right: 0; top: -20px; font-size: .6875rem; font-weight: 700; color: var(--bg); background: var(--danger); padding: 0 6px; border-radius: 4px; }
  .mini { display: inline-flex; gap: 2px; height: 30px; flex: none; }
</style>
