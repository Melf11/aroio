<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import { api } from '../../lib/api.js';
  import { toast } from '../../lib/state.svelte.js';
  import { t } from '../../lib/i18n.svelte.js';
  let list = $state(null);
  $effect(() => { api.get('/system/licenses').then((r) => (list = r.components)).catch((e) => toast(e.message, 'danger')); });
</script>

<div class="page">
  <PageHeader title={t('Open-Source-Lizenzen')} backTo="/einstellungen/geraet" />
  <p class="muted">{t('AroioOS baut auf freier Software auf. Danke an alle, die daran mitarbeiten.')}</p>
  {#if list}
    <ul class="list lic">
      {#each list as c}
        <li>
          <span class="grow">{#if c.url}<a href={c.url} target="_blank" rel="noopener">{c.name}</a>{:else}{c.name}{/if}{#if c.version}{' '}<span class="muted small">{c.version}</span>{/if}</span>
          <span class="muted small lt">{c.license}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .lic li { display: flex; align-items: center; gap: 12px; padding: 10px 16px; min-height: 48px; }
  .lic a { color: var(--brand-ink); font-weight: 600; }
  .lt { text-align: right; }
</style>
