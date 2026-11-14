<script>
  // Frequency response chart, log frequency axis. Series differ by colour AND
  // line style, so they are distinguishable without colour. A data table in a
  // <details> gives screen readers the numbers.
  import { hz, db } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';

  let { freqs, series, fmin = 20, fmax = 20000, ymin = -15, ymax = 15, summary = '', height = 220 } = $props();

  const W = 640, PAD = { l: 40, r: 12, t: 12, b: 26 };
  const x = (f) => PAD.l + (Math.log10(f / fmin) / Math.log10(fmax / fmin)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + ((ymax - Math.max(ymin, Math.min(ymax, v))) / (ymax - ymin)) * (height - PAD.t - PAD.b);
  const ticks = $derived([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].filter((f) => f >= fmin && f <= fmax));
  const yticks = $derived(Array.from({ length: Math.floor((ymax - ymin) / 5) + 1 }, (_, i) => ymin + i * 5));

  function path(values) {
    let d = '';
    freqs.forEach((f, i) => {
      if (f < fmin || f > fmax || values[i] == null) return;
      d += (d ? 'L' : 'M') + x(f).toFixed(1) + ' ' + y(values[i]).toFixed(1);
    });
    return d;
  }
  const tableRows = $derived(freqs.map((f, i) => ({ f, i })).filter((r) => r.f >= fmin && r.f <= fmax && r.i % 6 === 0));
</script>

<div class="chart">
<figure>
  <svg viewBox="0 0 {W} {height}" role="img" aria-label={summary || t('Frequenzgang')} preserveAspectRatio="none" style="aspect-ratio:{W}/{height}">
    {#each yticks as v}
      <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} class:zero={v === 0} class="grid" />
      <text x={PAD.l - 6} y={y(v) + 4} text-anchor="end" class="tick">{v > 0 ? '+' + v : v}</text>
    {/each}
    {#each ticks as f}
      <line y1={PAD.t} y2={height - PAD.b} x1={x(f)} x2={x(f)} class="grid" />
      <text x={x(f)} y={height - 8} text-anchor="middle" class="tick">{f >= 1000 ? f / 1000 + 'k' : f}</text>
    {/each}
    {#each series as s}
      <path d={path(s.values)} fill="none" stroke={s.color} stroke-width={s.width || 2.5}
            stroke-dasharray={s.dash || null} stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
    {/each}
  </svg>
  <figcaption class="legend">
    {#each series as s}
      <span class="item"><svg width="28" height="10" aria-hidden="true"><line x1="1" x2="27" y1="5" y2="5" stroke={s.color} stroke-width="3" stroke-dasharray={s.dash || null} /></svg>{s.label}</span>
    {/each}
  </figcaption>
</figure>
  <details>
    <summary>{t('Werte als Tabelle')}</summary>
    <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">{t('Frequenz')}</th>{#each series as s}<th scope="col">{s.label}</th>{/each}</tr></thead>
        <tbody>
          {#each tableRows as r}
            <tr><th scope="row">{hz(r.f)}</th>{#each series as s}<td>{db(s.values[r.i])}</td>{/each}</tr>
          {/each}
        </tbody>
      </table>
    </div>
  </details>
</div>

<style>
  .chart { display: flex; flex-direction: column; gap: 8px; }
  figure { margin: 0; display: flex; flex-direction: column; gap: 8px; }
  svg { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); stroke-width: 1; vector-effect: non-scaling-stroke; }
  .grid.zero { stroke: var(--border-strong); }
  .tick { font-size: 11px; fill: var(--text-2); font-family: var(--font); }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: .875rem; color: var(--text-2); }
  .item { display: inline-flex; align-items: center; gap: 6px; }
  details summary { cursor: pointer; color: var(--brand-ink); font-weight: 600; font-size: .875rem; min-height: var(--tap); display: flex; align-items: center; }
  .table-wrap { max-height: 280px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-s); }
  table { border-collapse: collapse; width: 100%; font-size: .875rem; font-variant-numeric: tabular-nums; }
  th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--border); }
  thead th { position: sticky; top: 0; background: var(--surface-2); }
  tbody th { text-align: left; font-weight: 500; }
</style>
