<script>
  import { FileUp, TriangleAlert } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import { api } from '../lib/api.js';
  import { toast } from '../lib/state.svelte.js';
  import { go } from '../lib/router.svelte.js';
  import { rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  const RE = /^(.+?)([LR])(44|48|88|96|176|192)\.(dbl|wav)$/i;
  const RATES = { 44: 44100, 48: 48000, 88: 88200, 96: 96000, 176: 176400, 192: 192000 };
  let name = $state(''), files = $state([]), busy = $state(false), warnings = $state([]);
  const parsed = $derived(files.map((f) => { const m = f.name.match(RE); return { f, ch: m?.[2]?.toUpperCase(), rate: m ? RATES[m[3]] : null, base: m?.[1] }; }));
  const bad = $derived(parsed.filter((p) => !p.ch));
  $effect(() => { if (!name && parsed[0]?.base) name = parsed[0].base; });

  async function submit(e) {
    e.preventDefault();
    busy = true;
    const form = new FormData();
    form.append('name', name);
    for (const p of parsed) form.append(`${p.ch}_${p.rate}`, p.f, p.f.name);
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
    <p>{t('Für Filter aus Acourate, Audiovero oder REW. Pro Abtastrate eine Datei für links und rechts, benannt wie bisher, z. B. „WohnzimmerL96.dbl“ und „WohnzimmerR96.dbl“.')}</p>
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
            {:else}<span class="badge danger"><TriangleAlert size={14} aria-hidden="true" />{t('Name nicht erkannt')}</span>{/if}</li>
        {/each}
      </ul>
    {/if}
    <div class="field"><label for="fname">{t('Name')}</label><input id="fname" class="input" bind:value={name} maxlength="40" required /></div>
    {#each warnings as w}<p class="notice warn">{w}</p>{/each}
    <button class="btn primary" type="submit" disabled={busy || !parsed.length || bad.length > 0}>{busy ? t('Lädt hoch …') : t('Importieren')}</button>
  </form>
</div>

<style>
  .drop { display: flex; gap: 14px; align-items: center; padding: 20px; border: 2px dashed var(--border-strong); border-radius: var(--radius); background: var(--surface); cursor: pointer; }
  .drop:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
  .frow { display: flex; gap: 8px; align-items: center; padding: 10px 14px; }
</style>
