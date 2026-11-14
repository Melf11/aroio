<script>
  import { Trash2, Check } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import FrequencyChart from '../components/FrequencyChart.svelte';
  import Dialog from '../components/Dialog.svelte';
  import { api } from '../lib/api.js';
  import { app, toast } from '../lib/state.svelte.js';
  import { go } from '../lib/router.svelte.js';
  import { db, rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  let { params } = $props();
  let preset = $state(null), curve = $state(null), name = $state(''), error = $state(null), confirmDelete = $state(false);
  const active = $derived(app.topics.dsp?.active_preset === params.id);
  const expert = $derived(app.topics.device?.expert_mode);

  async function load() {
    try {
      preset = await api.get('/dsp/presets/' + params.id);
      curve = await api.get(`/dsp/presets/${params.id}/curve`);
      name = preset.name;
    } catch (e) { error = e.message; }
  }
  $effect(() => { params.id; load(); });

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

      {#if curve}
        <FrequencyChart freqs={curve.freqs} ymin={-20} ymax={10} summary={t('Wirkung der Einstellung über die Frequenz')}
          series={[{ label: t('Links'), values: curve.channels.L, color: 'var(--brand-ink)', width: 3 },
                   { label: t('Rechts'), values: curve.channels.R, color: 'var(--warn)', dash: '6 4', width: 2 }]} />
      {/if}

      <form class="field" onsubmit={rename}>
        <label for="pname">{t('Name')}</label>
        <div class="row"><input id="pname" class="input" bind:value={name} maxlength="40" required /><button class="btn" type="submit">{t('Speichern')}</button></div>
      </form>

      <dl class="card info">
        <div><dt>{t('Art')}</dt><dd>{preset.kind === 'fir' ? t('FIR-Filter') : t('Equalizer')}</dd></div>
        {#if preset.created}<div><dt>{t('Erstellt')}</dt><dd>{preset.created}</dd></div>{/if}
        {#if preset.fir}<div><dt>{t('Abtastraten')}</dt><dd>{Object.keys(preset.fir).map((r) => rate(+r)).join(', ')}</dd></div>{/if}
        {#if preset.gain_db}<div><dt>{t('Pegel')}</dt><dd>{db(preset.gain_db)}</dd></div>{/if}
        {#if preset.delay_ms?.L || preset.delay_ms?.R}<div><dt>{t('Verzögerung')}</dt><dd>L {preset.delay_ms.L} ms · R {preset.delay_ms.R} ms</dd></div>{/if}
      </dl>

      {#if expert && preset.peq}
        {#each ['L', 'R'] as ch}
          <h2 class="section-title">{ch === 'L' ? t('Filter links') : t('Filter rechts')}</h2>
          <table class="filters"><thead><tr><th scope="col">{t('Typ')}</th><th scope="col">{t('Frequenz')}</th><th scope="col">{t('Pegel')}</th><th scope="col">Q</th></tr></thead>
            <tbody>{#each preset.peq[ch] as f}<tr><td>{f.type}</td><td>{f.freq} Hz</td><td>{db(f.gain)}</td><td>{f.q}</td></tr>{/each}</tbody></table>
        {/each}
      {/if}

      <button class="btn danger" type="button" onclick={() => (confirmDelete = true)}><Trash2 size={18} aria-hidden="true" />{t('Löschen')}</button>
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
</style>
