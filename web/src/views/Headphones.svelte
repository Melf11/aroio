<script>
  import { ExternalLink, TriangleAlert } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import Segmented from '../components/Segmented.svelte';
  import { api } from '../lib/api.js';
  import { app, toast } from '../lib/state.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

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

</script>

<div class="page">
  <PageHeader title={t('Kopfhörer-Korrektur')} backTo="/klang" />
  <section class="stack">
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
  .frow { display: flex; gap: 8px; align-items: center; padding: 10px 14px; min-height: 56px; }
  a { display: inline-flex; gap: 4px; align-items: center; }
</style>
