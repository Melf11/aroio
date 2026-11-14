<script>
  import { Play, ListStart, ListEnd, Heart } from '@lucide/svelte';
  import Dialog from './Dialog.svelte';
  import { play, favorite } from './library.js';
  import { t } from '../lib/i18n.svelte.js';
  let { item = $bindable(null) } = $props();
  let open = $state(false);
  $effect(() => { open = !!item; });
  async function run(fn) { const it = item; open = false; item = null; await fn(it); }
</script>

<Dialog bind:open title={item?.title || ''} onclose={() => (item = null)}>
  {#if item}
    <p class="muted">{item.subtitle || ''}</p>
    <div class="menu">
      <button class="btn block" onclick={() => run((i) => play(i.id, 'play'))}><Play size={20} aria-hidden="true" />{t('Jetzt abspielen')}</button>
      <button class="btn block" onclick={() => run((i) => play(i.id, 'next'))}><ListStart size={20} aria-hidden="true" />{t('Als Nächstes spielen')}</button>
      <button class="btn block" onclick={() => run((i) => play(i.id, 'add'))}><ListEnd size={20} aria-hidden="true" />{t('Zur Warteschlange hinzufügen')}</button>
      {#if item.kind !== 'link'}
        <button class="btn block" onclick={() => run((i) => favorite(i.id))}><Heart size={20} aria-hidden="true" />{t('Favorit an/aus')}</button>
      {/if}
    </div>
  {/if}
</Dialog>

<style>
  .menu { display: flex; flex-direction: column; gap: 8px; }
  .menu .btn { justify-content: flex-start; border-radius: 12px; }
</style>
