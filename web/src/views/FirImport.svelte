<script>
  import { ExternalLink, FileUp, Headphones, TriangleAlert } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import Segmented from '../components/Segmented.svelte';
  import { api } from '../lib/api.js';
  import { app, toast } from '../lib/state.svelte.js';
  import { go } from '../lib/router.svelte.js';
  import { rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  const RE = /^(.+?)([LR])(44|48|88|96|176|192)\.(dbl|wav)$/i;
  const RATES = { 44: 44100, 48: 48000, 88: 88200, 96: 96000, 176: 176400, 192: 192000 };
  let name = $state(''), files = $state([]), busy = $state(false), warnings = $state([]);
  const parsed = $derived(files.map((f) => { const m = f.name.match(RE); return { f, ch: m?.[2]?.toUpperCase(), rate: m ? RATES[m[3]] : null, base: m?.[1] }; }));
  // a single WAV without channel and rate in its name: a stereo filter (e.g. from the headphone
  // project), converted for every rate on the Aroio
  const stereo = $derived(parsed.length === 1 && !parsed[0].ch && /\.wav$/i.test(parsed[0].f.name));
  const bad = $derived(stereo ? [] : parsed.filter((p) => !p.ch));
  const stereoName = (n) => n.replace(/\.wav$/i, '').replace(/\s*\(\d+\)$/, '').replace(/[-_ ]*filters?[-_ ]*\d+k$/i, '')
    .replace(/_+/g, ' ').replace(/\s+/g, ' ').replace(/^[ -]+|[ -]+$/g, '');
  $effect(() => { if (!name && (stereo || parsed[0]?.base)) name = stereo ? stereoName(parsed[0].f.name) : parsed[0].base; });

  // headphone correction filters (github.com/AcrosonusMastering/Headphone-Correction-Filters)
  let hp = $state(null), hpError = $state(''), hpCollection = $state(''), hpQuery = $state(''), hpBusy = $state('');
  async function loadHeadphones() {
    hpError = '';
    try {
      hp = await api.get('/dsp/headphones');
      hpCollection ||= hp.collections[0]?.id || '';
    } catch (err) { hpError = err.message; }
  }
  $effect(() => { loadHeadphones(); });
  const hpItems = $derived.by(() => {
    const items = hp?.collections.find((c) => c.id === hpCollection)?.items || [];
    const q = hpQuery.trim().toLowerCase();
    return q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
  });
  const activeSource = $derived(app.topics.dsp?.enabled ? app.topics.dsp?.presets?.find((p) => p.id === app.topics.dsp?.active_preset)?.source : null);
  async function applyHeadphone(item) {
    hpBusy = item.path;
    try {
      const r = await api.post('/dsp/headphones', { path: item.path });
      toast(t('„{name}“ ist aktiv.', { name: r.name }), 'ok');
    } catch (err) { toast(err.message, 'danger'); } finally { hpBusy = ''; }
  }

  async function submit(e) {
    e.preventDefault();
    busy = true;
    const form = new FormData();
    form.append('name', name);
    for (const p of parsed) form.append(p.ch ? `${p.ch}_${p.rate}` : 'file', p.f, p.f.name);
    try {
      const r = await api.upload('/dsp/import', form);
      warnings = r.warnings;
      toast(t('Filter importiert.'), 'ok');
      if (!r.warnings.length) go('/klang/preset/' + r.preset);
    } catch (err) { toast(err.message, 'danger'); } finally { busy = false; }
  }
</script>

<div class="page">
  <PageHeader title={t('FIR-Filter importieren')} backTo="/klang" />
  <form class="stack" onsubmit={submit}>
    <p>{t('Für Filter aus Acourate, Audiovero oder REW. Pro Abtastrate eine Datei für links und rechts, benannt wie bisher, z. B. „WohnzimmerL96.dbl“ und „WohnzimmerR96.dbl“.')}
      {t('Oder eine einzelne Stereo-WAV (links und rechts in einer Datei), z. B. aus dem Kopfhörer-Projekt: Der Aroio rechnet sie für alle Abtastraten um.')}</p>
    <label class="drop">
      <FileUp size={28} aria-hidden="true" />
      <span><strong>{t('Dateien wählen')}</strong><br /><span class="muted small">.dbl (64-Bit) {t('oder')} .wav</span></span>
      <input class="sr-only" type="file" multiple accept=".dbl,.wav" onchange={(e) => (files = [...e.currentTarget.files])} />
    </label>
    {#if parsed.length}
      <ul class="list">
        {#each parsed as p}
          <li class="frow"><span class="grow mono">{p.f.name}</span>
            {#if p.ch}<span class="badge brand">{p.ch === 'L' ? t('links') : t('rechts')} · {rate(p.rate)}</span>
            {:else if stereo}<span class="badge brand">{t('Stereo · alle Abtastraten')}</span>
            {:else}<span class="badge danger"><TriangleAlert size={14} aria-hidden="true" />{t('Name nicht erkannt')}</span>{/if}</li>
        {/each}
      </ul>
    {/if}
    <div class="field"><label for="fname">{t('Name')}</label><input id="fname" class="input" bind:value={name} maxlength="40" required /></div>
    {#each warnings as w}<p class="notice warn">{w}</p>{/each}
    <button class="btn primary" type="submit" disabled={busy || !parsed.length || bad.length > 0}>{busy ? t('Lädt hoch …') : t('Importieren')}</button>
  </form>

  <section class="stack hp" aria-labelledby="hp-title">
    <h2 id="hp-title" class="with-icon"><Headphones size={22} aria-hidden="true" />{t('Kopfhörer-Korrektur')}</h2>
    <p>{t('Fertige Korrekturfilter für viele Kopfhörer aus dem Projekt „Headphone Correction Filters“ (Messungen von Rtings). Sie gleichen den Klang deines Kopfhörers an eine neutrale Zielkurve an. Der Aroio lädt den Filter von GitHub, wenn du ihn anwendest, und rechnet ihn für alle Abtastraten um.')}</p>
    {#if hpError}
      <p class="notice warn" role="alert"><TriangleAlert size={20} aria-hidden="true" /><span>{hpError}</span></p>
      <button class="btn" type="button" onclick={loadHeadphones}>{t('Erneut versuchen')}</button>
    {:else if !hp}
      <p class="muted" role="status">{t('Lädt …')}</p>
    {:else}
      {#if hp.collections.length > 1}
        <Segmented legend={t('Zielkurve')} value={hpCollection} onchange={(v) => (hpCollection = v)}
                   options={hp.collections.map((c) => ({ value: c.id, label: t(c.label) }))} />
      {/if}
      <div class="field"><label for="hp-q">{t('Kopfhörer suchen')}</label>
        <input id="hp-q" class="input" type="search" bind:value={hpQuery} autocomplete="off" placeholder={t('z. B. Sennheiser')} /></div>
      <p class="muted small" aria-live="polite">{t('{n} Kopfhörer', { n: hpItems.length })}</p>
      {#if hpItems.length}
        <ul class="list">
          {#each hpItems as item (item.path)}
            {@const active = activeSource === item.path}
            <li class="frow"><span class="grow">{item.name}</span>
              {#if active}<span class="badge ok">{t('aktiv')}</span>
              {:else}<button class="btn" type="button" disabled={!!hpBusy} aria-label={t('Anwenden: {name}', { name: item.name })}
                             onclick={() => applyHeadphone(item)}>{hpBusy === item.path ? t('Lädt …') : t('Anwenden')}</button>{/if}</li>
          {/each}
        </ul>
      {/if}
      <p class="muted small"><a href={hp.source} rel="external" target="_blank">{t('Projekt auf GitHub')}<ExternalLink size={14} aria-hidden="true" /></a>
        · {t('Filter von Acrosonus Mastering (GPLv3), Messdaten von Rtings.com.')}</p>
    {/if}
  </section>
</div>

<style>
  .drop { display: flex; gap: 14px; align-items: center; padding: 20px; border: 2px dashed var(--border-strong); border-radius: var(--radius); background: var(--surface); cursor: pointer; }
  .drop:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
  .frow { display: flex; gap: 8px; align-items: center; padding: 10px 14px; min-height: 56px; }
  .hp { margin-top: 32px; }
  .with-icon { display: flex; gap: 10px; align-items: center; }
  .hp a { display: inline-flex; gap: 4px; align-items: center; }
</style>
