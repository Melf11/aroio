<script>
  import { ChevronLeft } from '@lucide/svelte';
  import { back } from '../lib/router.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  let { title, backTo = null, children } = $props();
</script>

<header class="page-head">
  {#if backTo}
    <button class="icon-btn" type="button" onclick={() => back(backTo)} aria-label={t('Zurück')}>
      <ChevronLeft size={26} aria-hidden="true" />
    </button>
  {/if}
  <h1>{title}</h1>
  {@render children?.()}
</header>
