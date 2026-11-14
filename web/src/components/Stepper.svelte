<script>
  // Progress of a wizard: "Schritt 3 von 7: Lautstärke" for screen readers,
  // a row of segments visually.
  import { t } from '../lib/i18n.svelte.js';
  let { steps, current } = $props();
</script>

<nav class="stepper" aria-label={t('Fortschritt')}>
  <p class="label">{t('Schritt {n} von {total}', { n: current + 1, total: steps.length })}<span class="muted">{" · "}{steps[current]?.title}</span></p>
  <ol>
    {#each steps as s, i}
      <li class:done={i < current} class:current={i === current} aria-current={i === current ? 'step' : undefined}>
        <span class="sr-only">{s.title}{i < current ? ` (${t('erledigt')})` : ''}</span>
      </li>
    {/each}
  </ol>
</nav>

<style>
  .stepper { margin: 0 0 20px; }
  .label { font-weight: 650; font-size: .9375rem; margin-bottom: 8px; }
  ol { list-style: none; display: flex; gap: 6px; margin: 0; padding: 0; }
  li { flex: 1; height: 6px; border-radius: 3px; background: var(--surface-3); }
  li.done { background: var(--brand-ink); }
  li.current { background: var(--brand); outline: 2px solid var(--brand-ink); outline-offset: 1px; }
</style>
