<script>
  // Queue with buttons instead of drag & drop: "nach oben", "nach unten",
  // "entfernen". Works with keyboard, switch control and screen readers.
  import { ArrowUp, ArrowDown, Trash2 } from '@lucide/svelte';
  import Cover from './Cover.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { api } from '../lib/api.js';
  import { time } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';
  const q = $derived(app.topics.queue || { items: [], index: -1 });
  const act = async (a, data) => { try { await api.post('/queue/' + a, data); } catch (e) { toast(e.message, 'danger'); } };
</script>

{#if !q.items.length}
  <p class="muted">{t('Die Warteschlange ist leer.')}</p>
{:else}
  <ol class="list">
    {#each q.items as item, i (item.id + ':' + i)}
      <li class:now={i === q.index} class:past={i < q.index}>
        <button class="main" type="button" onclick={() => act('jump', { index: i })} aria-current={i === q.index ? 'true' : undefined}>
          <Cover src={item.image} size={44} radius={8} />
          <span class="text">
            <span class="title ellipsis">{item.title}</span>
            <span class="sub ellipsis">{item.subtitle} · {time(item.duration)}</span>
          </span>
          {#if i === q.index}<span class="badge brand">{t('Läuft')}</span>{/if}
        </button>
        {#if i !== q.index}
          <div class="tools">
            <button class="icon-btn" type="button" disabled={i === 0} onclick={() => act('move', { from: i, to: i - 1 })} aria-label={t('{title} nach oben', { title: item.title })}><ArrowUp size={18} aria-hidden="true" /></button>
            <button class="icon-btn" type="button" disabled={i === q.items.length - 1} onclick={() => act('move', { from: i, to: i + 1 })} aria-label={t('{title} nach unten', { title: item.title })}><ArrowDown size={18} aria-hidden="true" /></button>
            <button class="icon-btn" type="button" onclick={() => act('remove', { index: i })} aria-label={t('{title} entfernen', { title: item.title })}><Trash2 size={18} aria-hidden="true" /></button>
          </div>
        {/if}
      </li>
    {/each}
  </ol>
  <button class="btn ghost" type="button" onclick={() => act('clear')}>{t('Warteschlange leeren')}</button>
{/if}

<style>
  li { display: flex; align-items: center; flex-wrap: wrap; }
  .main { flex: 1; min-width: 200px; display: flex; align-items: center; gap: 12px; padding: 8px 12px; min-height: 60px; border: 0; background: none; text-align: left; color: inherit; }
  .main:hover { background: var(--surface-2); }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .title { font-weight: 550; }
  .sub { font-size: .8125rem; color: var(--text-2); }
  .now .title { color: var(--brand-ink); }
  .past { opacity: .7; }
  .tools { display: flex; padding-right: 4px; }
  .tools .icon-btn:disabled { opacity: .3; }
</style>
