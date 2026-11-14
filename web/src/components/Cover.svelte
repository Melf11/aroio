<script>
  import { Music } from '@lucide/svelte';
  let { src = null, size = 56, alt = '', radius = 10 } = $props();
  let failed = $state(false);
</script>

{#if src && !failed}
  <img {src} {alt} width={size} height={size} loading="lazy" decoding="async" style="--r:{radius}px;--s:{size}px" onerror={() => (failed = true)} />
{:else}
  <span class="ph" style="--r:{radius}px;--s:{size}px" role={alt ? 'img' : undefined} aria-label={alt || undefined}><Music size={Math.max(16, size / 3)} aria-hidden="true" /></span>
{/if}

<style>
  img, .ph { width: var(--s); height: var(--s); border-radius: var(--r); flex: none; object-fit: cover; background: var(--surface-3); }
  .ph { display: grid; place-items: center; color: var(--text-2); }
  img[width="100%"] { width: 100%; height: auto; aspect-ratio: 1; }
</style>
