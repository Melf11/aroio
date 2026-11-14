<script>
  import PageHeader from '../components/PageHeader.svelte';
  import PageView from '../components/PageView.svelte';
  import { api } from '../lib/api.js';
  import { route, focusHeading } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let page = $state(null), error = $state(null);
  const path = $derived(route.query.get('path') || '');
  $effect(() => {
    page = null;
    api.get('/library/browse?path=' + encodeURIComponent(path))
      .then((p) => { page = p; error = null; focusHeading(); })
      .catch((e) => (error = e.message));
  });
</script>

<div class="page">
  <PageHeader title={page?.title || t('Musik')} backTo="/musik" />
  {#if error}<p class="notice danger" role="alert">{error}</p>
  {:else if !page}<p class="muted" role="status">{t('Lädt …')}</p>
  {:else}<PageView {page} />{/if}
</div>
