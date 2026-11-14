<script>
  // Native range input (keyboard, VoiceOver/TalkBack adjustable) plus explicit
  // minus/plus buttons for people who can't drag. Sends at most every 80 ms.
  import { Volume1, Volume2, VolumeX, Minus, Plus } from '@lucide/svelte';
  import { player } from '../lib/api.js';
  import { t } from '../lib/i18n.svelte.js';
  import { toast } from '../lib/state.svelte.js';
  let { value = 0, limit = 100, muted = false, compact = false } = $props();
  let local = $state(null);
  let timer = null;
  const shown = $derived(local ?? value);

  function send(v) {
    local = v;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try { await player('volume', { value: v }); } catch (e) { toast(e.message, 'danger'); }
      setTimeout(() => (local = null), 300);
    }, 80);
  }
  const toggleMute = () => player('mute', { on: !muted }).catch((e) => toast(e.message, 'danger'));
  const step = (d) => send(Math.max(0, Math.min(limit, shown + d)));
</script>

<div class="vol" class:compact>
  {#if !compact}
    <button class="icon-btn" type="button" onclick={() => step(-5)} aria-label={t('Leiser')}><Minus aria-hidden="true" /></button>
  {/if}
  <button class="icon-btn mute" class:on={muted} type="button" onclick={toggleMute} aria-pressed={muted} aria-label={t('Stumm')}>
    {#if muted || shown === 0}<VolumeX size={20} aria-hidden="true" />{:else if shown < 50}<Volume1 size={20} aria-hidden="true" />{:else}<Volume2 size={20} aria-hidden="true" />{/if}
  </button>
  <input type="range" min="0" max="100" step="1" value={shown} aria-label={t('Lautstärke')}
         aria-valuetext={t('{v} Prozent', { v: shown })}
         style="--p:{shown}%"
         oninput={(e) => send(Math.min(limit, +e.currentTarget.value))} />
  <output aria-hidden="true">{shown}</output>
  {#if !compact}
    <button class="icon-btn" type="button" onclick={() => step(5)} aria-label={t('Lauter')}><Plus aria-hidden="true" /></button>
  {/if}
</div>

<style>
  .vol { display: flex; align-items: center; gap: 6px; width: 100%; }
  .mute { color: var(--text-2); flex: none; }
  .mute.on { color: var(--danger-ink, var(--danger)); }
  output { width: 2.2em; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text-2); }
  input[type=range] { flex: 1; min-width: 0; height: var(--tap); background: transparent; -webkit-appearance: none; appearance: none; margin: 0; }
  input[type=range]::-webkit-slider-runnable-track { height: 8px; border-radius: 4px; background: linear-gradient(to right, var(--brand) var(--p), var(--surface-3) var(--p)); border: 1px solid var(--border-strong); }
  input[type=range]::-moz-range-track { height: 8px; border-radius: 4px; background: var(--surface-3); border: 1px solid var(--border-strong); }
  input[type=range]::-moz-range-progress { height: 8px; border-radius: 4px; background: var(--brand); }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 26px; height: 26px; margin-top: -10px; border-radius: 50%; background: #fff; border: 2px solid var(--brand-ink); box-shadow: 0 1px 4px rgb(0 0 0 / .3); }
  input[type=range]::-moz-range-thumb { width: 24px; height: 24px; border-radius: 50%; background: #fff; border: 2px solid var(--brand-ink); }
  input[type=range]:focus-visible { outline: none; }
  input[type=range]:focus-visible::-webkit-slider-thumb { outline: 3px solid var(--focus); outline-offset: 2px; }
  input[type=range]:focus-visible::-moz-range-thumb { outline: 3px solid var(--focus); outline-offset: 2px; }
</style>
