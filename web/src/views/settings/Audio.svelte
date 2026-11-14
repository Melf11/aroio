<script>
  import PageHeader from '../../components/PageHeader.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  let cfg = $state(null), errors = $state({});
  $effect(() => { api.get('/config').then((c) => (cfg = c.audio)); });
  async function save(patch) {
    try { const c = await config({ audio: patch }); cfg = c.audio; errors = {}; toast(t('Gespeichert.'), 'ok'); }
    catch (e) { errors = { [e.field?.split('.').pop()]: e.message }; }
  }
  const numbers = [
    ['start_volume', 'Startlautstärke (%)', 'Lautstärke nach dem Einschalten.'],
    ['volume_limit', 'Höchste Lautstärke (%)', 'Schützt Lautsprecher und Ohren.'],
    ['chunksize', 'CamillaDSP chunksize', '0 = gemessener Standard für dieses Gerät.'],
    ['target_level', 'CamillaDSP target_level', '0 = doppelte chunksize.'],
    ['lms_buffer_kb', 'Squeezelite-Puffer (kB)', '0 = Standard.'],
    ['airplay_latency_ms', 'AirPlay-Puffer (ms)', '0 = Standard.'],
  ];
</script>

<div class="page">
  <PageHeader title={t('Ton (Experten)')} backTo="/einstellungen" />
  {#if cfg}
    <div class="stack">
      <Segmented legend={t('Abtastrate')} value={cfg.rate_mode} options={[{ value: 'follow', label: t('Folgt der Musik') }, { value: 'fixed', label: t('Fest') }]} onchange={(v) => save({ rate_mode: v })} />
      <p class="muted small">{cfg.rate_mode === 'follow' ? t('Jede Datei spielt in ihrer eigenen Abtastrate, ohne Umrechnung. Empfohlen.') : t('Alles wird auf eine feste Rate umgerechnet (CamillaDSP AsyncSinc).')}</p>
      {#if cfg.rate_mode === 'fixed'}
        <div class="field"><label for="fr">{t('Feste Abtastrate')}</label>
          <select id="fr" class="input" value={cfg.fixed_rate} onchange={(e) => save({ fixed_rate: +e.currentTarget.value })}>
            {#each [44100, 48000, 88200, 96000, 176400, 192000] as r}<option value={r}>{r / 1000} kHz</option>{/each}
          </select></div>
      {/if}
      <Segmented legend={t('Resampler-Qualität')} value={cfg.resampler} options={[{ value: 'fast', label: t('Schnell') }, { value: 'balanced', label: t('Ausgewogen') }, { value: 'best', label: t('Beste') }]} onchange={(v) => save({ resampler: v })} />
      {#each numbers as [key, label, hint]}
        <form class="field" onsubmit={(e) => { e.preventDefault(); save({ [key]: +new FormData(e.currentTarget).get('v') }); }}>
          <label for={'n-' + key}>{t(label)}</label>
          <div class="row"><input id={'n-' + key} name="v" class="input mono" type="number" inputmode="numeric" value={cfg[key]} aria-invalid={!!errors[key]} aria-describedby={'h-' + key} /><button class="btn" type="submit">{t('Speichern')}</button></div>
          <span id={'h-' + key} class="hint">{t(hint)}</span>
          {#if errors[key]}<span class="error-text" role="alert">{errors[key]}</span>{/if}
        </form>
      {/each}
    </div>
  {/if}
</div>
