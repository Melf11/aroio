<script>
  import { TriangleAlert, Power } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';

  let cfg = $state(null), hw = $state(null), errors = $state({}), saving = $state(false);
  const kinds = $derived({ hat: t('Aufsteckkarte'), usb: 'USB', hdmi: 'HDMI', analog: t('Kopfhörerbuchse') });

  $effect(() => { api.get('/config').then((c) => (cfg = c.audio)); });
  // re-read the hardware list whenever the audio path changes (USB DAC plugged in, driver, reboot)
  $effect(() => { app.topics.dsp; app.topics.device; api.get('/audio/hardware').then((h) => (hw = h)); });

  const missing = $derived(hw && hw.selected !== 'auto' && !hw.outputs.some((o) => o.id === hw.selected));
  // friendly names: the kernel calls HDMI "vc4-hdmi-0" and the jack "bcm2835 Headphones"
  const label = (o) => o.kind === 'hdmi' ? (hw.outputs.filter((x) => x.kind === 'hdmi').length > 1 ? `HDMI ${o.card.replace(/\D/g, '') * 1 + 1}` : 'HDMI')
    : o.kind === 'analog' ? t('Kopfhörerbuchse') : o.name;
  const activeName = $derived.by(() => { const o = hw?.outputs.find((x) => x.id === hw.active); return o ? label(o) : hw?.active; });
  const driverHint = $derived(hw?.drivers.find((d) => d.id === hw.driver)?.hint);

  async function save(patch, msg = t('Gespeichert.')) {
    try { cfg = (await config({ audio: patch })).audio; errors = {}; toast(msg, 'ok'); return true; }
    catch (e) { errors = { [e.field?.split('.').pop()]: e.message }; return false; }
  }
  async function setDriver(id) {
    try { await config({ hardware: { dac_driver: id } }); toast(t('Treiber gespeichert. Wird nach einem Neustart aktiv.')); }
    catch (e) { toast(e.message, 'danger'); }
  }

  const numbers = [
    ['start_volume_max', 'Höchstens nach dem Einschalten (%)', 'Der Aroio merkt sich die Lautstärke. Nach dem Einschalten gilt die zuletzt eingestellte, aber höchstens dieser Wert.'],
    ['volume_limit', 'Höchste Lautstärke (%)', 'Schützt Lautsprecher und Ohren.'],
    ['chunksize', 'CamillaDSP chunksize', '0 = gemessener Standard für dieses Gerät.'],
    ['target_level', 'CamillaDSP target_level', '0 = doppelte chunksize.'],
    ['lms_buffer_kb', 'Squeezelite-Puffer (kB)', '0 = Standard.'],
    ['airplay_latency_ms', 'AirPlay-Puffer (ms)', '0 = Standard.'],
  ];
  async function saveNumbers(e) {
    e.preventDefault();
    saving = true;
    const form = new FormData(e.currentTarget);
    const patch = {};
    for (const [key] of numbers) {
      const v = Number(form.get(key));
      if (v !== cfg[key]) patch[key] = v;
    }
    if (Object.keys(patch).length) await save(patch);
    else toast(t('Keine Änderungen.'));
    saving = false;
  }
</script>

<div class="page">
  <PageHeader title={t('Ton (Experten)')} backTo="/einstellungen" />

  {#if hw}
    <section aria-labelledby="hw-h" class="stack">
      <h2 id="hw-h">{t('Audiohardware')}</h2>
      {#if hw.reboot_required}
        <div class="notice warn" role="status">
          <TriangleAlert size={18} aria-hidden="true" />
          <span class="grow">{t('Der neue Treiber wird nach einem Neustart aktiv.')}</span>
          <button class="btn" type="button" onclick={() => api.post('/system/reboot')}><Power size={18} aria-hidden="true" />{t('Jetzt neu starten')}</button>
        </div>
      {/if}

      <fieldset>
        <legend class="label">{t('Ausgabegerät')}</legend>
        <ul class="list">
          <li><label class="opt">
            <input type="radio" name="out" checked={hw.selected === 'auto'} onchange={() => save({ output: 'auto' }, t('Ausgabegerät: automatisch'))} />
            <span class="text"><span class="name">{t('Automatisch (empfohlen)')}</span>
              <span class="muted small">{t('Der Aroio wählt selbst. Zurzeit: {name}', { name: activeName })}</span></span>
          </label></li>
          {#each hw.outputs as o (o.id)}
            <li><label class="opt">
              <input type="radio" name="out" checked={hw.selected === o.id} onchange={() => save({ output: o.id }, t('Ausgabegerät: {name}', { name: label(o) }))} />
              <span class="text"><span class="name">{label(o)}</span>
                <span class="muted small">{kinds[o.kind]}{#if hw.selected !== 'auto' && o.id === hw.active}{' · '}{t('spielt gerade')}{/if}</span></span>
            </label></li>
          {/each}
          {#if missing}
            <li class="opt warn-item"><TriangleAlert size={18} aria-hidden="true" />
              <span class="text"><span class="name mono">{hw.selected}</span>
                <span class="small">{t('Nicht angeschlossen. Solange wird automatisch gewählt.')}</span></span></li>
          {/if}
        </ul>
      </fieldset>

      <p><a href="/einstellungen/lautsprecher">{t('Lautsprecher prüfen')}</a></p>

      <div class="field">
        <label for="drv">{t('Treiber für die Aufsteckkarte')}</label>
        <select id="drv" class="input" value={hw.driver} onchange={(e) => setDriver(e.currentTarget.value)} aria-describedby="drv-h">
          {#each hw.drivers as d}<option value={d.id}>{t(d.label)}</option>{/each}
        </select>
        <span id="drv-h" class="hint">{driverHint ? t(driverHint) + ' ' : ''}{t('Nur nötig, wenn die Karte nicht automatisch erkannt wird. Änderung wirkt nach einem Neustart.')}</span>
      </div>
    </section>
  {/if}

  {#if cfg}
    <section aria-labelledby="rate-h" class="stack sec">
      <h2 id="rate-h">{t('Abtastrate')}</h2>
      <Segmented legend={t('Abtastrate')} hideLegend value={cfg.rate_mode} options={[{ value: 'follow', label: t('Folgt der Musik') }, { value: 'fixed', label: t('Fest') }]} onchange={(v) => save({ rate_mode: v })} />
      <p class="muted small">{cfg.rate_mode === 'follow' ? t('Jede Datei spielt in ihrer eigenen Abtastrate, ohne Umrechnung. Empfohlen.') : t('Alles wird auf eine feste Rate umgerechnet (CamillaDSP AsyncSinc).')}</p>
      {#if cfg.rate_mode === 'fixed'}
        <div class="field"><label for="fr">{t('Feste Abtastrate')}</label>
          <select id="fr" class="input" value={cfg.fixed_rate} onchange={(e) => save({ fixed_rate: +e.currentTarget.value })}>
            {#each [44100, 48000, 88200, 96000, 176400, 192000] as r}<option value={r}>{r / 1000} kHz</option>{/each}
          </select></div>
      {/if}
      <div class="field"><label for="mr">{t('Höchste Abtastrate des DAC')}</label>
        <select id="mr" class="input" value={cfg.max_rate} onchange={(e) => save({ max_rate: +e.currentTarget.value })} aria-describedby="mr-h">
          {#each [48000, 96000, 192000] as r}<option value={r}>{r / 1000} kHz</option>{/each}
        </select>
        <span id="mr-h" class="hint">{t('Höhere Raten werden auf das Doppelte bzw. Vierfache von 44,1 oder 48 kHz heruntergerechnet, das der DAC noch kann.')}</span></div>
      <Segmented legend={t('Resampler-Qualität')} value={cfg.resampler} options={[{ value: 'fast', label: t('Schnell') }, { value: 'balanced', label: t('Ausgewogen') }, { value: 'best', label: t('Beste') }]} onchange={(v) => save({ resampler: v })} />
    </section>

    <form class="stack sec" onsubmit={saveNumbers} aria-labelledby="buf-h">
      <h2 id="buf-h">{t('Lautstärke und Puffer')}</h2>
      <div class="grid">
        {#each numbers as [key, label, hint]}
          <div class="field">
            <label for={'n-' + key}>{t(label)}</label>
            <input id={'n-' + key} name={key} class="input mono" type="number" inputmode="numeric" value={cfg[key]}
                   aria-invalid={!!errors[key]} aria-describedby={'h-' + key} />
            <span id={'h-' + key} class="hint">{t(hint)}</span>
            {#if errors[key]}<span class="error-text" role="alert">{errors[key]}</span>{/if}
          </div>
        {/each}
      </div>
      <button class="btn primary save" type="submit" disabled={saving}>{t('Speichern')}</button>
    </form>
  {/if}
</div>

<style>
  .sec { margin-top: 32px; }
  fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
  legend { padding: 0; margin-bottom: 8px; }
  .opt { display: flex; align-items: center; gap: 14px; padding: 12px 16px; min-height: 60px; cursor: pointer; }
  .opt input { width: 22px; height: 22px; accent-color: var(--brand-ink); flex: none; }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name { font-weight: 600; }
  .warn-item { cursor: default; color: var(--warn); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 16px; }
  .save { align-self: flex-start; }
</style>
