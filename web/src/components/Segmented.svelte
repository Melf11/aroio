<script>
  // Radio group that looks like segmented buttons. Arrow keys work natively.
  let { legend, options, value, onchange, hideLegend = false } = $props();
  const name = 'seg-' + Math.random().toString(36).slice(2, 8);
</script>

<fieldset class="seg">
  <legend class:sr-only={hideLegend}>{legend}</legend>
  <div class="opts">
    {#each options as o}
      <label class:on={value === o.value}>
        <input type="radio" {name} value={o.value} checked={value === o.value} onchange={() => onchange(o.value)} />
        <span>{o.label}</span>
      </label>
    {/each}
  </div>
</fieldset>

<style>
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  legend { font-weight: 600; margin-bottom: 8px; padding: 0; }
  .opts { display: flex; background: var(--surface-2); border: 1px solid var(--border-strong); border-radius: 999px; padding: 3px; gap: 2px; }
  label { flex: 1; position: relative; display: grid; place-items: center; min-height: 40px; border-radius: 999px; font-weight: 600; cursor: pointer; text-align: center; padding: 4px 10px; font-size: .9375rem; }
  label.on { background: var(--brand); color: var(--on-brand); }
  input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
  label:has(input:focus-visible) { outline: 3px solid var(--focus); outline-offset: 1px; }
</style>
