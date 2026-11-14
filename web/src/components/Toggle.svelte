<script>
  // A switch with visible label and optional description. role="switch" so
  // screen readers say "an"/"aus".
  let { checked = false, label, description = '', disabled = false, onchange } = $props();
  const id = 'sw-' + Math.random().toString(36).slice(2, 8);
</script>

<div class="toggle-row">
  <div class="text">
    <span id="{id}-l" class="label">{label}</span>
    {#if description}<span id="{id}-d" class="muted small">{description}</span>{/if}
  </div>
  <button type="button" role="switch" aria-checked={checked} aria-labelledby="{id}-l"
          aria-describedby={description ? `${id}-d` : undefined} {disabled}
          class="switch" onclick={() => onchange?.(!checked)}>
    <span class="knob"></span>
  </button>
</div>

<style>
  .toggle-row { display: flex; align-items: center; gap: 16px; padding: 12px 16px; min-height: 60px; }
  .text { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .label { font-weight: 600; }
  .switch { position: relative; flex: none; width: 56px; height: 34px; border-radius: 999px; border: 2px solid var(--border-strong); background: var(--surface-3); padding: 0; }
  .knob { position: absolute; top: 3px; left: 3px; width: 24px; height: 24px; border-radius: 50%; background: var(--surface); box-shadow: 0 1px 3px rgb(0 0 0 / .3); transition: transform .18s ease; border: 1px solid var(--border-strong); }
  .switch[aria-checked="true"] { background: var(--brand); border-color: var(--brand-ink); }
  .switch[aria-checked="true"] .knob { transform: translateX(22px); background: #fff; border-color: var(--brand-ink); }
  .switch[aria-checked="true"] .knob::after { content: ''; position: absolute; inset: 6px 9px 7px 8px; border: solid var(--brand-ink); border-width: 0 2px 2px 0; transform: rotate(40deg); }
  .switch:disabled { opacity: .5; cursor: not-allowed; }
</style>
