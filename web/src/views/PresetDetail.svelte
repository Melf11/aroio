<script>
  import { Trash2, Check } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import FrequencyChart from '../components/FrequencyChart.svelte';
  import PeqEditor from '../components/PeqEditor.svelte';
  import Dialog from '../components/Dialog.svelte';
  import { api } from '../lib/api.js';
  import { app, toast } from '../lib/state.svelte.js';
  import { go, route } from '../lib/router.svelte.js';
  import { db, rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  let { params } = $props();
  let preset = $state(null), curve = $state(null), name = $state(''), error = $state(null), confirmDelete = $state(false);
  let editing = $state(false), measurement = $state(null), original = null, editorKey = $state(0), dirty = $state(false);

  async function startEdit() {
    original = { peq: JSON.parse(JSON.stringify(preset.peq)), gain_db: preset.gain_db };
    measurement = await api.get(`/dsp/presets/${params.id}/measurement`).catch(() => null);
    editing = true;
    dirty = false;
  }
  async function savePeq(_ch, _filters, all) {
    try { await api.patch('/dsp/presets/' + params.id, { peq: all }); dirty = true; }
    catch (e) { toast(e.message, 'danger'); }
  }
  async function undo() {
    try { await api.patch('/dsp/presets/' + params.id, original); await load(); editorKey++; dirty = false; toast(t('Änderungen zurückgenommen.')); }
    catch (e) { toast(e.message, 'danger'); }
  }
  async function done() { editing = false; await load(); }
  const active = $derived(app.topics.dsp?.active_preset === params.id);
  const expert = $derived(app.topics.device?.expert_mode);

  async function load() {
    try {
      preset = await api.get('/dsp/presets/' + params.id);
      curve = await api.get(`/dsp/presets/${params.id}/curve`);
      name = preset.name;
    } catch (e) { error = e.message; }
  }
  $effect(() => { params.id; load().then(() => {
    // new own equalizer: straight into the editor
    if (route.query.get('bearbeiten') && preset?.kind === 'peq' && !editing) startEdit();
  }); });

  // level and timing (expert): gain, per-channel trim and delay, for FIR and EQ alike
  let lv = $state(null);
  $effect(() => { if (preset) lv = { gain_db: preset.gain_db || 0, trim_L: preset.trim_db?.L || 0, trim_R: preset.trim_db?.R || 0, delay_L: preset.delay_ms?.L || 0, delay_R: preset.delay_ms?.R || 0 }; });
  async function saveLevels(e) {
    e.preventDefault();
    try {
      await api.patch('/dsp/presets/' + params.id, { gain_db: +lv.gain_db, trim_db: { L: +lv.trim_L, R: +lv.trim_R }, delay_ms: { L: +lv.delay_L, R: +lv.delay_R } });
      await load(); toast(t('Gespeichert.'), 'ok');
    } catch (err) { toast(err.message, 'danger'); }
  }
  const builtin = $derived(preset?.origin === 'builtin');

  async function rename(e) {
    e.preventDefault();
    try { await api.patch('/dsp/presets/' + params.id, { name }); toast(t('Gespeichert.'), 'ok'); } catch (err) { toast(err.message, 'danger'); }
  }
  async function remove() {
    confirmDelete = false;
    try { await api.del('/dsp/presets/' + params.id); toast(t('Gelöscht.'), 'ok'); go('/klang', { replace: true }); } catch (e) { toast(e.message, 'danger'); }
  }
</script>

<div class="page">
  <PageHeader title={preset?.name || t('Klangeinstellung')} backTo="/klang" />
  {#if error}<p class="notice danger" role="alert">{error}</p>{/if}
  {#if preset}
    <div class="stack">
      {#if active}<p class="notice ok"><Check size={18} aria-hidden="true" />{t('Diese Einstellung ist gerade aktiv.')}</p>
      {:else}<button class="btn primary" type="button" onclick={() => api.post(`/dsp/presets/${params.id}/activate`).catch((e) => toast(e.message, 'danger'))}>{t('Verwenden')}</button>{/if}

      {#if editing}
        <section class="card stack" aria-labelledby="ed-h">
          <h2 id="ed-h">{t('Filter bearbeiten')}</h2>
          <p class="muted small">{active ? t('Jede Änderung ist sofort zu hören.') : t('Wähle „Verwenden“, um die Änderungen zu hören.')}</p>
          {#key editorKey}
            <PeqEditor peq={preset.peq} {measurement} fmax={measurement ? measurement.fmax * 2 : 20000} onchange={savePeq} />
          {/key}
          <div class="row wrap">
            <button class="btn primary" type="button" onclick={done}>{t('Fertig')}</button>
            <button class="btn" type="button" disabled={!dirty} onclick={undo}>{t('Rückgängig')}</button>
          </div>
        </section>
      {:else}
        {#if curve}
          <FrequencyChart freqs={curve.freqs} ymin={-20} ymax={10} summary={t('Wirkung der Einstellung über die Frequenz')}
            series={[{ label: t('Links'), values: curve.channels.L, color: 'var(--brand-ink)', width: 3 },
                     { label: t('Rechts'), values: curve.channels.R, color: 'var(--warn)', dash: '6 4', width: 2 }]} />
        {/if}
        {#if preset.kind === 'peq'}
          <button class="btn" type="button" onclick={startEdit}>{t('Filter bearbeiten')}</button>
        {/if}
      {/if}

      <form class="field" onsubmit={rename}>
        <label for="pname">{t('Name')}</label>
        <div class="row"><input id="pname" class="input" bind:value={name} maxlength="40" required /><button class="btn" type="submit">{t('Speichern')}</button></div>
      </form>

      <dl class="card info">
        <div><dt>{t('Art')}</dt><dd>{preset.kind === 'fir' ? t('FIR-Filter') : t('Equalizer')}</dd></div>
        {#if builtin}<div><dt>{t('Herkunft')}</dt><dd>{t('Werksfilter von ABACUS')}</dd></div>{/if}
        {#if preset.created}<div><dt>{t('Erstellt')}</dt><dd>{preset.created}</dd></div>{/if}
        {#if preset.fir}<div><dt>{t('Abtastraten')}</dt><dd>{Object.keys(preset.fir).map((r) => rate(+r)).join(', ')}</dd></div>{/if}
        {#if preset.gain_db}<div><dt>{t('Pegel')}</dt><dd>{db(preset.gain_db)}</dd></div>{/if}
        {#if preset.delay_ms?.L || preset.delay_ms?.R}<div><dt>{t('Verzögerung')}</dt><dd>L {preset.delay_ms.L} ms · R {preset.delay_ms.R} ms</dd></div>{/if}
      </dl>

      {#if expert && preset.kind !== 'bypass' && lv && !editing}
        <form class="card stack" onsubmit={saveLevels} aria-labelledby="lv-h">
          <h2 id="lv-h">{t('Pegel und Laufzeit')}</h2>
          <div class="lv">
            <div class="field"><label for="lv-g">{t('Pegel gesamt (dB)')}</label><input id="lv-g" class="input" type="number" step="0.1" min="-40" max="12" bind:value={lv.gain_db} /></div>
            <div class="field"><label for="lv-tl">{t('Pegel links (dB)')}</label><input id="lv-tl" class="input" type="number" step="0.1" min="-20" max="6" bind:value={lv.trim_L} /></div>
            <div class="field"><label for="lv-tr">{t('Pegel rechts (dB)')}</label><input id="lv-tr" class="input" type="number" step="0.1" min="-20" max="6" bind:value={lv.trim_R} /></div>
            <div class="field"><label for="lv-dl">{t('Verzögerung links (ms)')}</label><input id="lv-dl" class="input" type="number" step="0.01" min="0" max="100" bind:value={lv.delay_L} /></div>
            <div class="field"><label for="lv-dr">{t('Verzögerung rechts (ms)')}</label><input id="lv-dr" class="input" type="number" step="0.01" min="0" max="100" bind:value={lv.delay_R} /></div>
          </div>
          <p class="muted small">{t('1 ms Verzögerung entspricht etwa 34 cm Weg. Den näheren Lautsprecher verzögern.')}</p>
          <button class="btn" type="submit">{t('Speichern')}</button>
        </form>
      {/if}

      {#if expert && preset.peq && !editing}
        {#each ['L', 'R'] as ch}
          <h2 class="section-title">{ch === 'L' ? t('Filter links') : t('Filter rechts')}</h2>
          <table class="filters"><thead><tr><th scope="col">{t('Typ')}</th><th scope="col">{t('Frequenz')}</th><th scope="col">{t('Pegel')}</th><th scope="col">Q</th></tr></thead>
            <tbody>{#each preset.peq[ch] as f}<tr><td>{f.type}</td><td>{f.freq} Hz</td><td>{db(f.gain)}</td><td>{f.q}</td></tr>{/each}</tbody></table>
        {/each}
      {/if}

      {#if !builtin}<button class="btn danger" type="button" onclick={() => (confirmDelete = true)}><Trash2 size={18} aria-hidden="true" />{t('Löschen')}</button>{/if}
    </div>
  {/if}
</div>

<Dialog bind:open={confirmDelete} title={t('„{name}“ löschen?', { name: preset?.name })}>
  <p>{t('Das lässt sich nicht rückgängig machen.')}</p>
  {#snippet actions()}
    <button class="btn" type="button" onclick={() => (confirmDelete = false)}>{t('Behalten')}</button>
    <button class="btn danger" type="button" onclick={remove}>{t('Löschen')}</button>
  {/snippet}
</Dialog>

<style>
  .info { display: grid; gap: 8px; margin: 0; }
  .info div { display: flex; justify-content: space-between; gap: 12px; }
  dt { color: var(--text-2); } dd { margin: 0; font-weight: 600; text-align: right; }
  .filters { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; background: var(--surface); border-radius: 12px; }
  .filters th, .filters td { text-align: right; padding: 8px; border-bottom: 1px solid var(--border); }
  .filters th:first-child, .filters td:first-child { text-align: left; }
  .btn.danger { align-self: flex-start; }
  .wrap { flex-wrap: wrap; }
  .lv { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
  .stack > .btn:not(.block) { align-self: flex-start; }
</style>
