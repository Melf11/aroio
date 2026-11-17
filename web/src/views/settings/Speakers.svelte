<script>
  // One speaker check for everyone: 440 Hz tone or pink noise, left/right/both, duration.
  // The device topic says what is playing, so every open app shows the stop button.
  import { Play, Square } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';

  let kind = $state('tone'), channel = $state('L'), seconds = $state(2);
  const running = $derived(app.topics.device?.test_signal);
  const durations = [[1, '1 s'], [2, '2 s'], [5, '5 s'], [10, '10 s'], [30, '30 s'], [60, '1 min'], [300, '5 min']];
  const side = (c) => (c === 'L' ? t('links') : c === 'R' ? t('rechts') : t('beide Seiten'));

  const send = (body) => api.post('/system/test-signal', body).catch((e) => toast(e.message, 'danger'));
  const start = () => send({ kind, channel, seconds });
  const stop = () => send({ kind: null });
</script>

<div class="page">
  <PageHeader title={t('Lautsprecher prüfen')} backTo="/einstellungen" />
  <p class="muted">{t('Kommt der Ton aus dem richtigen Lautsprecher? Mit Rauschen lassen sich Pegel und Aufstellung vergleichen. Musik wird dafür angehalten.')}</p>
  <div class="card stack">
    <Segmented legend={t('Signal')} value={kind} onchange={(v) => (kind = v)}
               options={[{ value: 'tone', label: t('Ton (440 Hz)') }, { value: 'noise', label: t('Rosa Rauschen') }]} />
    <Segmented legend={t('Lautsprecher')} value={channel} onchange={(v) => (channel = v)}
               options={[{ value: 'L', label: t('Links') }, { value: 'R', label: t('Rechts') }, { value: 'both', label: t('Beide') }]} />
    <div class="field">
      <label for="dur">{t('Dauer')}</label>
      <select id="dur" class="input" value={seconds} onchange={(e) => (seconds = +e.currentTarget.value)}>
        {#each durations as [s, label]}<option value={s}>{label}</option>{/each}
      </select>
    </div>
    {#if kind === 'noise' || seconds > 10}<p class="notice warn small">{t('Vorsicht mit der Lautstärke: Rauschen und lange Töne sind anstrengend für Ohren und Hochtöner.')}</p>{/if}
    <div class="row wrap">
      <button class="btn primary" type="button" onclick={start}><Play size={18} aria-hidden="true" />{t('Abspielen')}</button>
      <button class="btn" type="button" onclick={stop} disabled={!running}><Square size={18} aria-hidden="true" />{t('Stopp')}</button>
    </div>
    <p role="status" class="small">{#if running}{t('Spielt: {signal} {side}, {s} s', { signal: running.kind === 'tone' ? t('Ton') : t('Rauschen'), side: side(running.channel), s: running.seconds })}{/if}</p>
  </div>
</div>

<style>
  .wrap { flex-wrap: wrap; gap: 8px; }
</style>
