<script>
  // Native <dialog>: focus trap, Escape and inert background come from the browser.
  import { X } from '@lucide/svelte';
  import { t } from '../lib/i18n.svelte.js';
  let { open = $bindable(false), title, children, actions, onclose } = $props();
  let el;
  $effect(() => {
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  });
</script>

<dialog bind:this={el} aria-labelledby="dlg-title" onclose={() => { open = false; onclose?.(); }}>
  <div class="head">
    <h2 id="dlg-title">{title}</h2>
    <button class="icon-btn" type="button" onclick={() => (open = false)} aria-label={t('Schließen')}><X aria-hidden="true" /></button>
  </div>
  <div class="body">{@render children?.()}</div>
  {#if actions}<div class="actions">{@render actions()}</div>{/if}
</dialog>

<style>
  dialog { border: 0; padding: 0; border-radius: 20px; background: var(--surface); color: var(--text); width: min(520px, calc(100vw - 32px)); max-height: calc(100dvh - 48px); box-shadow: 0 20px 60px rgb(0 0 0 / .35); }
  dialog::backdrop { background: rgb(4 18 18 / .55); }
  .head { display: flex; align-items: center; gap: 8px; padding: 16px 12px 4px 20px; }
  .head h2 { flex: 1; }
  .body { padding: 8px 20px 16px; display: flex; flex-direction: column; gap: 12px; }
  .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; padding: 0 20px 20px; }
</style>
