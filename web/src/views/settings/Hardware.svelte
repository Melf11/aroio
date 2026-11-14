<script>
  import { Radio, LoaderCircle, RotateCcw } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast, announce } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  let hw = $state(null), ir = $state(null), learning = $state(null);
  const loadIr = () => api.get('/hardware/ir').then((r) => (ir = r));
  $effect(() => { api.get('/config').then((c) => (hw = c.hardware)); loadIr(); });
  async function save(patch) { try { hw = (await config({ hardware: patch })).hardware; } catch (e) { toast(e.message, 'danger'); } }
  const d = $derived(app.topics.device);
  const ACTIONS = {
    KEY_PLAYPAUSE: 'Wiedergabe / Pause', KEY_STOP: 'Stopp', KEY_NEXT: 'Nächster Titel', KEY_PREVIOUS: 'Vorheriger Titel',
    KEY_VOLUMEUP: 'Lauter', KEY_VOLUMEDOWN: 'Leiser', KEY_MUTE: 'Stumm',
    KEY_1: 'Klangeinstellung 1', KEY_2: 'Klangeinstellung 2', KEY_3: 'Klangeinstellung 3', KEY_4: 'Klangeinstellung 4', KEY_5: 'Klangeinstellung 5',
  };
  const codeFor = (action) => Object.entries(ir?.map || {}).find(([, a]) => a === action)?.[0];
  async function learn(action) {
    learning = action;
    announce(t('Drücke jetzt die Taste für „{a}“ auf der Fernbedienung.', { a: t(ACTIONS[action]) }));
    try { const r = await api.post('/hardware/ir/learn', { action }); toast(t('Taste gespeichert ({c}).', { c: r.code }), 'ok'); await loadIr(); }
    catch (e) { toast(e.message, 'danger'); }
    learning = null;
  }
  async function resetIr() {
    try { await api.post('/hardware/ir/reset'); await loadIr(); toast(t('Belegung der Aroio-Fernbedienung wiederhergestellt.')); } catch (e) { toast(e.message, 'danger'); }
  }
</script>

<div class="page">
  <PageHeader title={t('Hardware (Experten)')} backTo="/einstellungen" />
  {#if hw && d}
    <div class="field">
      <label for="model">{t('Modell')}</label>
      <select id="model" class="input" value={hw.model} onchange={(e) => save({ model: e.currentTarget.value })} aria-describedby="model-h">
        <option value="auto">{t('Automatisch (erkannt: {m})', { m: d.models.find((m) => m.id === d.model_detected)?.label || d.model_detected })}</option>
        {#each d.models as m}<option value={m.id}>{m.label}</option>{/each}
      </select>
      <span id="model-h" class="hint">{t('Bestimmt Pegelregelung, Drehgeber und Taste am Gerät. Rechner: {b}. Wirkt nach einem Neustart.', { b: d.board_label })}</span>
    </div>
    <ul class="list top">
      <li><Toggle label={t('WLAN des Raspberry Pi')} description={t('Aus, wenn der Aroio per Kabel verbunden ist. Spart Strom und vermeidet Störungen.')} checked={hw.onboard_wifi} onchange={(v) => save({ onboard_wifi: v })} /></li>
      <li><Toggle label={t('Bluetooth des Raspberry Pi')} checked={hw.onboard_bluetooth} onchange={(v) => save({ onboard_bluetooth: v })} /></li>
      <li><Toggle label={t('Infrarot-Fernbedienung')} description={t('Die Aroio-Fernbedienung funktioniert sofort, andere Fernbedienungen lassen sich anlernen.')} checked={hw.ir_enabled} onchange={(v) => save({ ir_enabled: v })} /></li>
    </ul>
    <div class="stack gap">
      <div class="field"><label for="es">{t('Drehgeber: Schritte pro Raste (%)')}</label>
        <select id="es" class="input" value={hw.encoder_step} onchange={(e) => save({ encoder_step: +e.currentTarget.value })}>{#each [1, 2, 3, 4, 5] as n}<option value={n}>{n}</option>{/each}</select></div>
      <Segmented legend={t('Display-Drehung')} value={hw.display_rotate} options={[0, 90, 180, 270].map((v) => ({ value: v, label: v + '°' }))} onchange={(v) => save({ display_rotate: v })} />
    </div>

    {#if hw.ir_enabled && ir}
      <h2 class="section-title">{t('Tasten der Fernbedienung')}</h2>
      <p class="muted small">{t('„Anlernen“ wählen und innerhalb von 15 Sekunden die gewünschte Taste drücken.')}{#if ir.last}{' '}{t('Zuletzt empfangen: {c}', { c: ir.last })}{/if}</p>
      <ul class="list keys">
        {#each Object.keys(ACTIONS) as action}
          {@const code = codeFor(action)}
          <li>
            <span class="grow"><strong>{t(ACTIONS[action])}</strong><br /><span class="muted small mono">{code || t('nicht belegt')}</span></span>
            <button class="btn" type="button" disabled={!!learning} onclick={() => learn(action)} aria-label={learning === action ? t('Warte auf Taste für „{a}“ …', { a: t(ACTIONS[action]) }) : t('{a} anlernen', { a: t(ACTIONS[action]) })}>
              {#if learning === action}<LoaderCircle size={18} class="spin" aria-hidden="true" />{t('Warte auf Taste …')}{:else}<Radio size={18} aria-hidden="true" />{t('Anlernen')}{/if}
            </button>
          </li>
        {/each}
      </ul>
      <button class="btn" type="button" onclick={resetIr}><RotateCcw size={18} aria-hidden="true" />{t('Aroio-Fernbedienung wiederherstellen')}</button>
    {/if}
  {/if}
</div>

<style>
  .top { margin-top: 20px; }
  .gap { margin-top: 24px; gap: 20px; }
  .keys li { display: flex; align-items: center; gap: 12px; padding: 8px 8px 8px 16px; min-height: 60px; }
  .keys { margin-bottom: 12px; }
  .mono { font-family: var(--mono); }
</style>
