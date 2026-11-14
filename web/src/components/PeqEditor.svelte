<script>
  // Manual PEQ editor. Every band: type, frequency, level, Q, each as slider plus
  // number field (sliders are hard to hit exactly, numbers are hard to "feel").
  // The chart recalculates in the browser instantly; changes go to the parent
  // (debounced), which makes them audible.
  import { untrack } from 'svelte';
  import { Plus, Trash2, Link, Unlink } from '@lucide/svelte';
  import FrequencyChart from './FrequencyChart.svelte';
  import Segmented from './Segmented.svelte';
  import { response, hasGain, logFreqs } from '../lib/biquad.js';
  import { hz, db } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  import { announce } from '../lib/state.svelte.js';

  let { peq, measurement = null, fmax = 20000, onchange } = $props();

  const copy = (list) => (list || []).map((f) => ({ ...f }));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  // seeded once; the parent re-mounts the editor ({#key}) to load other filters
  const init = untrack(() => peq);
  let bands = $state({ L: copy(init.L), R: copy(init.R) });
  let linked = $state(same(init.L, init.R));
  let channel = $state('L');
  let open = $state(-1);
  let timer;

  const freqs = $derived(measurement?.freqs || logFreqs());
  const typeLabels = $derived({ peaking: t('Glocke (Peak)'), lowshelf: t('Bass-Shelf'), highshelf: t('Höhen-Shelf'), lowpass: t('Tiefpass'), highpass: t('Hochpass') });
  const list = $derived(bands[channel]);
  const eq = $derived(response(list, freqs));
  const series = $derived(measurement?.channels?.[channel]?.before
    ? [
        { label: t('Gemessen'), values: measurement.channels[channel].before, color: 'var(--text-2)', width: 2 },
        { label: t('Ziel'), values: measurement.channels[channel].target, color: 'var(--warn)', dash: '6 4', width: 2 },
        { label: t('Mit Korrektur'), values: measurement.channels[channel].before.map((v, i) => v + eq[i]), color: 'var(--brand-ink)', width: 3 },
      ]
    : [
        { label: t('Filter links'), values: response(bands.L, freqs), color: 'var(--brand-ink)', width: 3 },
        { label: t('Filter rechts'), values: response(bands.R, freqs), color: 'var(--warn)', dash: '6 4', width: 2 },
      ]);

  function changed() {
    if (linked) bands[channel === 'L' ? 'R' : 'L'] = copy(bands[channel]);
    clearTimeout(timer);
    const ch = linked ? 'both' : channel;
    timer = setTimeout(() => onchange?.(ch, copy(bands[channel]), { L: copy(bands.L), R: copy(bands.R) }), 150);
  }
  function add() {
    if (list.length >= 20) return;
    bands[channel].push({ type: 'peaking', freq: 100, gain: 0, q: 1 });
    open = bands[channel].length - 1;
    changed();
    announce(t('Filter {n} hinzugefügt', { n: open + 1 }));
  }
  function remove(i) {
    bands[channel].splice(i, 1);
    open = -1;
    changed();
    announce(t('Filter {n} entfernt', { n: i + 1 }));
  }
  function setLinked(v) {
    linked = v;
    if (v) changed();
  }
  // frequency slider on a log scale: position 0..1000 <-> 20..20000 Hz
  const toPos = (f) => Math.round((Math.log(f / 20) / Math.log(1000)) * 1000);
  const fromPos = (p) => Math.round(20 * Math.pow(1000, p / 1000) * 10) / 10;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const summary = (f) => `${typeLabels[f.type]} · ${hz(f.freq)}${hasGain(f.type) ? ' · ' + db(f.gain) : ''} · Q ${f.q}`;
</script>

<div class="peq stack">
  <div class="top">
    {#if !linked}
      <Segmented legend={t('Kanal')} hideLegend value={channel} options={[{ value: 'L', label: t('Links') }, { value: 'R', label: t('Rechts') }]} onchange={(v) => { channel = v; open = -1; }} />
    {/if}
    <button class="btn" type="button" aria-pressed={linked} onclick={() => setLinked(!linked)}>
      {#if linked}<Link size={18} aria-hidden="true" />{t('Links und rechts gleich')}{:else}<Unlink size={18} aria-hidden="true" />{t('Kanäle getrennt')}{/if}
    </button>
  </div>

  <FrequencyChart {freqs} {series} fmin={20} {fmax} ymin={-20} ymax={15}
    summary={t('Wirkung der Filter {ch}', { ch: linked ? t('beider Kanäle') : channel === 'L' ? t('links') : t('rechts') })} />

  <ol class="bands">
    {#each list as f, i (i)}
      <li>
        <details open={open === i} ontoggle={(e) => { if (e.currentTarget.open) open = i; }}>
          <summary><span class="n">{i + 1}</span><span class="grow">{summary(f)}</span></summary>
          <fieldset>
            <legend class="sr-only">{t('Filter {n}', { n: i + 1 })}</legend>
            <div class="field">
              <label for="ty-{channel}-{i}">{t('Typ')}</label>
              <select id="ty-{channel}-{i}" class="input" bind:value={f.type} onchange={changed}>
                {#each Object.entries(typeLabels) as [v, l]}<option value={v}>{l}</option>{/each}
              </select>
            </div>
            <div class="param">
              <label for="fr-{channel}-{i}">{t('Frequenz')}</label>
              <input type="range" min="0" max="1000" value={toPos(f.freq)} aria-label={t('Frequenz')} aria-valuetext={hz(f.freq)}
                     oninput={(e) => { f.freq = fromPos(+e.currentTarget.value); changed(); }} />
              <span class="num"><input id="fr-{channel}-{i}" class="input mono" type="number" min="10" max="24000" step="1" value={f.freq}
                     onchange={(e) => { f.freq = clamp(+e.currentTarget.value || 100, 10, 24000); changed(); }} /> Hz</span>
            </div>
            {#if hasGain(f.type)}
              <div class="param">
                <label for="ga-{channel}-{i}">{t('Pegel')}</label>
                <input type="range" min="-15" max="6" step="0.5" value={f.gain} aria-label={t('Pegel')} aria-valuetext={db(f.gain)}
                       oninput={(e) => { f.gain = +e.currentTarget.value; changed(); }} />
                <span class="num"><input id="ga-{channel}-{i}" class="input mono" type="number" min="-24" max="12" step="0.1" value={f.gain}
                       onchange={(e) => { f.gain = clamp(+e.currentTarget.value || 0, -24, 12); changed(); }} /> dB</span>
              </div>
            {/if}
            <div class="param">
              <label for="q-{channel}-{i}">{t('Güte (Q)')}</label>
              <input type="range" min="0.3" max="10" step="0.1" value={f.q} aria-label={t('Güte (Q)')} aria-valuetext={String(f.q)}
                     oninput={(e) => { f.q = +e.currentTarget.value; changed(); }} />
              <span class="num"><input id="q-{channel}-{i}" class="input mono" type="number" min="0.1" max="20" step="0.1" value={f.q}
                     onchange={(e) => { f.q = clamp(+e.currentTarget.value || 1, 0.1, 20); changed(); }} /></span>
            </div>
            <button class="btn ghost danger-text" type="button" onclick={() => remove(i)}><Trash2 size={18} aria-hidden="true" />{t('Filter {n} entfernen', { n: i + 1 })}</button>
          </fieldset>
        </details>
      </li>
    {/each}
  </ol>
  {#if !list.length}<p class="muted">{t('Keine Filter. Der Klang bleibt unverändert.')}</p>{/if}
  <button class="btn" type="button" disabled={list.length >= 20} onclick={add}><Plus size={18} aria-hidden="true" />{t('Filter hinzufügen')}</button>
  <p class="muted small">{t('Tipp: Lieber absenken als anheben. Anhebungen gleicht der Aroio mit weniger Vorpegel aus, damit nichts übersteuert.')}</p>
</div>

<style>
  .top { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; justify-content: space-between; }
  .top :global(.seg) { flex: 1; min-width: 180px; }
  .btn[aria-pressed="true"] { border-color: var(--brand-ink); color: var(--brand-ink); }
  .bands { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  details { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  summary { display: flex; align-items: center; gap: 10px; padding: 10px 14px; min-height: var(--tap); cursor: pointer; font-weight: 600; font-variant-numeric: tabular-nums; }
  .n { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: var(--brand-soft); color: var(--brand-soft-ink); font-size: .8125rem; flex: none; }
  fieldset { border: 0; margin: 0; padding: 4px 14px 14px; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .param { display: grid; grid-template-columns: 1fr auto; grid-template-areas: "label num" "range range"; gap: 4px 12px; align-items: center; }
  .param label { grid-area: label; font-weight: 600; }
  .param .num { grid-area: num; display: flex; align-items: center; gap: 6px; color: var(--text-2); }
  .param .num .input { width: 6.5em; min-height: 40px; padding: 6px 8px; }
  .param input[type=range] { grid-area: range; width: 100%; height: var(--tap); accent-color: var(--brand-ink); margin: 0; }
  .danger-text { color: var(--danger); align-self: flex-start; }
</style>
