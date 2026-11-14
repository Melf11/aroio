<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  let hw = $state(null);
  $effect(() => { api.get('/config').then((c) => (hw = c.hardware)); });
  async function save(patch) { try { hw = (await config({ hardware: patch })).hardware; } catch (e) { toast(e.message, 'danger'); } }
  const d = $derived(app.topics.device);
</script>

<div class="page">
  <PageHeader title={t('Hardware (Experten)')} backTo="/einstellungen" />
  {#if hw && d}
    <p class="muted">{t('Modell: {m} · {b}', { m: d.model_label, b: d.board_label })}</p>
    <ul class="list top">
      <li><Toggle label={t('WLAN des Raspberry Pi')} description={t('Aus, wenn der Aroio per Kabel verbunden ist. Spart Strom und vermeidet Störungen.')} checked={hw.onboard_wifi} onchange={(v) => save({ onboard_wifi: v })} /></li>
      <li><Toggle label={t('Bluetooth des Raspberry Pi')} checked={hw.onboard_bluetooth} onchange={(v) => save({ onboard_bluetooth: v })} /></li>
      <li><Toggle label={t('Infrarot-Fernbedienung')} description={t('Tasten 1–9 wählen die Klangeinstellung.')} checked={hw.ir_enabled} onchange={(v) => save({ ir_enabled: v })} /></li>
    </ul>
    <div class="stack gap">
      <div class="field"><label for="es">{t('Drehgeber: Schritte pro Raste (%)')}</label>
        <select id="es" class="input" value={hw.encoder_step} onchange={(e) => save({ encoder_step: +e.currentTarget.value })}>{#each [1, 2, 3, 4, 5] as n}<option value={n}>{n}</option>{/each}</select></div>
      <Segmented legend={t('Display-Drehung')} value={hw.display_rotate} options={[0, 90, 180, 270].map((v) => ({ value: v, label: v + '°' }))} onchange={(v) => save({ display_rotate: v })} />
      <p class="muted small">{t('Belegung der Tasten und Fernbedienung anlernen folgt in Phase 2.')}</p>
    </div>
  {/if}
</div>

<style>
  .top { margin-top: 12px; }
  .gap { margin-top: 24px; gap: 20px; }
</style>
