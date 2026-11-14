<script>
  import { ChevronRight } from '@lucide/svelte';
  let { href, icon = null, label, value = '', badge = '', badgeLevel = 'brand' } = $props();
</script>

<a class="lr" {href}>
  {#if icon}{@const Icon = icon}<span class="ic"><Icon size={20} aria-hidden="true" /></span>{/if}
  <span class="text"><span class="label">{label}</span>{#if value}<span class="muted small ellipsis">{value}</span>{/if}</span>
  {#if badge}<span class="badge {badgeLevel}">{badge}</span>{/if}
  <ChevronRight size={20} aria-hidden="true" class="chev" />
</a>

<style>
  .lr { display: flex; align-items: center; gap: 14px; padding: 12px 12px 12px 16px; min-height: 60px; color: inherit; text-decoration: none; }
  .lr:hover { background: var(--surface-2); }
  .ic { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; background: var(--brand-soft); color: var(--brand-soft-ink); flex: none; }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .label { font-weight: 600; }
  :global(.chev) { color: var(--text-2); flex: none; }
</style>
