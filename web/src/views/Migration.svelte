<script>
  // Taking over an old Aroio: review what will be imported, apply, check, done.
  import { CircleCheck, TriangleAlert, Info, MinusCircle } from '@lucide/svelte';
  import Stepper from '../components/Stepper.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { api } from '../lib/api.js';
  import { focusHeading } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';

  const m = $derived(app.topics.migration);
  const groups = $derived.by(() => {
    const out = {};
    for (const it of m?.report || []) (out[it.area] ||= []).push(it);
    return Object.entries(out);
  });
  const checks = $derived((m?.report || []).filter((i) => i.status === 'check'));
  const step = $derived(m?.state === 'applied' ? 1 : 0);
  const icons = { ok: CircleCheck, check: TriangleAlert, info: Info, dropped: MinusCircle };
  const labels = $derived({ ok: t('übernommen'), check: t('bitte prüfen'), info: t('Hinweis'), dropped: t('entfällt') });
  $effect(() => { step; focusHeading(); });

  const act = async (a) => { try { await api.post('/migration/' + a); } catch (e) { toast(e.message, 'danger'); } };
  const tone = (channel) => api.post('/system/test-tone', { channel });
</script>

<div class="page wiz">
  <div class="logo"><img src="/icons/logo.svg" alt="" width="40" height="40" /><span>Aroio</span></div>
  <Stepper steps={[{ title: t('Übersicht') }, { title: t('Prüfen') }]} current={step} />

  {#if step === 0}
    <section class="stack">
      <h1>{t('Einstellungen vom alten Aroio übernehmen')}</h1>
      <p>{t('Wir haben die Einstellungen deines bisherigen Aroio gefunden ({s}). So werden sie übernommen:', { s: m?.source })}</p>
      {#each groups as [area, items]}
        <h2 class="section-title">{area}</h2>
        <ul class="list">
          {#each items as it}
            {@const Icon = icons[it.status] || Info}
            <li class="item {it.status}">
              <Icon size={20} aria-hidden="true" />
              <div class="grow">
                <div class="head"><strong>{it.label}</strong><span class="val">{it.value}</span></div>
                {#if it.note}<p class="muted small">{it.note}</p>{/if}
              </div>
              <span class="sr-only">({labels[it.status]})</span>
            </li>
          {/each}
        </ul>
      {/each}
      <button class="btn primary block" type="button" onclick={() => act('apply')}>{t('Übernehmen')}</button>
      <button class="btn ghost block" type="button" onclick={() => act('discard')}>{t('Nicht übernehmen, neu einrichten')}</button>
    </section>
  {:else}
    <section class="stack">
      <h1>{t('Fast fertig')}</h1>
      <p class="notice ok"><CircleCheck size={20} aria-hidden="true" /><span>{t('Deine Einstellungen sind übernommen.')}</span></p>
      {#if checks.length}
        <h2 class="section-title">{t('Bitte kurz prüfen')}</h2>
        <ul class="list">{#each checks as it}<li class="item check"><TriangleAlert size={20} aria-hidden="true" /><div class="grow"><strong>{it.label}</strong>{#if it.note}<p class="muted small">{it.note}</p>{/if}</div></li>{/each}</ul>
      {/if}
      <h2 class="section-title">{t('Lautsprecher prüfen')}</h2>
      <div class="row wrap"><button class="btn" type="button" onclick={() => tone('L')}>{t('Ton links')}</button><button class="btn" type="button" onclick={() => tone('R')}>{t('Ton rechts')}</button></div>
      <button class="btn primary block" type="button" onclick={() => act('finish')}>{t('Fertig')}</button>
    </section>
  {/if}
</div>

<style>
  .wiz { max-width: 640px; padding-top: 24px; }
  .logo { display: flex; align-items: center; gap: 10px; font-weight: 750; font-size: 1.25rem; margin-bottom: 20px; }
  .item { display: flex; gap: 12px; padding: 12px 16px; align-items: flex-start; }
  .item :global(svg) { flex: none; margin-top: 2px; }
  .item.ok :global(svg) { color: var(--ok); }
  .item.check :global(svg) { color: var(--warn); }
  .item.info :global(svg) { color: var(--brand-ink); }
  .item.dropped { color: var(--text-2); }
  .head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .val { text-align: right; }
  .wrap { flex-wrap: wrap; }
</style>
