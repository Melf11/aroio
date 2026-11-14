<script>
  // Room correction, one task per screen. State lives in aroiod (topic
  // "roomcorr"); this view renders it and sends actions.
  import { Mic, CircleCheck, TriangleAlert, Volume2, LoaderCircle, Usb, FileUp, Check } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import Stepper from '../components/Stepper.svelte';
  import Dialog from '../components/Dialog.svelte';
  import FrequencyChart from '../components/FrequencyChart.svelte';
  import Segmented from '../components/Segmented.svelte';
  import { app, toast, announce } from '../lib/state.svelte.js';
  import { roomcorr } from '../lib/api.js';
  import { focusHeading, go } from '../lib/router.svelte.js';
  import { db } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';

  const s = $derived(app.topics.roomcorr);
  const expert = $derived(app.topics.device?.expert_mode);
  let confirmCancel = $state(false);
  let name = $state(t('Wohnzimmer'));
  let channel = $state('L');
  let listen = $state('new');
  let lastStep = null;

  $effect(() => {
    if (s && !s.active && !s.saved) act('start');
  });
  $effect(() => {
    if (s?.step && s.step !== lastStep) { lastStep = s.step; focusHeading(); }
  });

  async function act(name, data) {
    try { await roomcorr(name, data); } catch (e) { toast(e.message, 'danger'); }
  }
  async function calibration(e) {
    const f = e.currentTarget.files?.[0];
    if (f) await act('calibration', { text: await f.text(), name: f.name });
  }
  async function cancel() {
    confirmCancel = false;
    await act('cancel');
    go('/klang', { replace: true });
  }

  const positionText = (i) => [
    t('Am Hörplatz, auf Ohrhöhe.'),
    t('30 cm links vom Hörplatz.'),
    t('30 cm rechts vom Hörplatz.'),
    t('30 cm vor dem Hörplatz.'),
    t('30 cm hinter dem Hörplatz.'),
    t('Etwas höher am Hörplatz (+15 cm).'),
    t('Etwas tiefer am Hörplatz (−15 cm).'),
    t('Links neben dem Hörplatz (60 cm).'),
    t('Rechts neben dem Hörplatz (60 cm).'),
  ][i];
  const measuredAt = (p) => s?.measured.filter((m) => m.position === p).length || 0;
  const allMeasured = $derived(s && s.measured.length >= s.positions * 2);
  const characters = $derived([
    { value: 'neutral', label: t('Neutral') }, { value: 'warm', label: t('Warm') }, { value: 'bright', label: t('Hell') },
  ]);
  const charText = $derived({
    neutral: t('Ausgewogen, mit einem leichten Bassfundament, wie in einem guten Studio.'),
    warm: t('Mehr Bass und sanftere Höhen. Angenehm bei lauterem und langem Hören.'),
    bright: t('Schlanker Bass und offene Höhen. Viele Details, klingt direkt.'),
  });
  const r = $derived(s?.result);
  const ch = $derived(r?.channels?.[channel]);
</script>

<div class="page wiz">
  <PageHeader title={t('Raum einmessen')} backTo="/klang">
    {#if s?.active}<button class="btn ghost" type="button" onclick={() => (confirmCancel = true)}>{t('Abbrechen')}</button>{/if}
  </PageHeader>

  {#if s?.saved}
    <section class="done stack">
      <CircleCheck size={56} class="ok-ic" aria-hidden="true" />
      <h2>{t('Fertig! „{name}“ ist aktiv.', { name: s.saved.name })}</h2>
      <p>{t('Dein Aroio gleicht jetzt deinen Raum aus. Du kannst jederzeit unter Klang zwischen den Einstellungen wechseln oder die Korrektur ausschalten.')}</p>
      <a class="btn primary" href="/klang">{t('Zu den Klangeinstellungen')}</a>
      <button class="btn ghost" type="button" onclick={() => act('start')}>{t('Neue Messung')}</button>
    </section>
  {:else if s?.active}
    <Stepper steps={s.steps} current={s.step_index} />

    {#if s.step === 'intro'}
      <section class="stack">
        <h2 class="step-h">{t('So funktioniert es')}</h2>
        <p>{t('Der Aroio spielt über jeden Lautsprecher einen kurzen Ton („Sweep“) und hört mit einem Messmikrofon zu. Daraus berechnet er, welche Frequenzen dein Raum zu stark oder zu schwach wiedergibt, und gleicht das aus.')}</p>
        <ul class="need">
          <li><Mic size={20} aria-hidden="true" />{t('Ein Messmikrofon (miniDSP UMIK-1)')}</li>
          <li><Volume2 size={20} aria-hidden="true" />{t('Etwa 10 Minuten Ruhe im Raum')}</li>
          <li><Check size={20} aria-hidden="true" />{t('Die Lautsprecher stehen an ihrem endgültigen Platz')}</li>
        </ul>
        <button class="btn primary block" type="button" onclick={() => act('next')}>{t('Los geht’s')}</button>
      </section>

    {:else if s.step === 'mic'}
      <section class="stack">
        <h2 class="step-h">{t('Mikrofon anschließen')}</h2>
        <p>{t('Stecke das Messmikrofon in einen USB-Anschluss am Aroio.')}</p>
        <div class="status-box" role="status">
          {#if s.mic.connected}
            <CircleCheck size={28} class="ok-ic" aria-hidden="true" />
            <div><strong>{t('{name} erkannt', { name: s.mic.name })}</strong><br />
              <span class="muted small">{t('Seriennummer {sn}', { sn: s.mic.serial })}</span></div>
          {:else}
            <Usb size={28} aria-hidden="true" />
            <div><strong>{t('Warte auf das Mikrofon …')}</strong><br /><span class="muted small">{t('Das wird automatisch erkannt.')}</span></div>
          {/if}
        </div>
        {#if s.mic.connected}
          {#if s.mic.calibration}
            <p class="notice ok"><CircleCheck size={18} aria-hidden="true" /><span>{t('Kalibrierung geladen: {n}', { n: s.mic.calibration_name })}</span></p>
          {:else}
            <div class="notice warn"><TriangleAlert size={18} aria-hidden="true" /><span>{t('Die Kalibrierdatei konnte nicht automatisch geladen werden (kein Internet?). Du findest sie auf der Website von miniDSP unter deiner Seriennummer.')}</span></div>
            <label class="btn"><FileUp size={18} aria-hidden="true" />{t('Kalibrierdatei wählen')}<input class="sr-only" type="file" accept=".txt,.cal,.frd" onchange={calibration} /></label>
          {/if}
        {/if}
        <button class="btn primary block" type="button" disabled={!s.mic.connected} onclick={() => act('next')}>{t('Weiter')}</button>
      </section>

    {:else if s.step === 'placement'}
      <section class="stack">
        <h2 class="step-h">{t('Mikrofon aufstellen')}</h2>
        <svg class="room-pic" viewBox="0 0 320 200" role="img" aria-label={t('Skizze: zwei Lautsprecher oben, das Mikrofon am Hörplatz unten in der Mitte')}>
          <rect x="4" y="4" width="312" height="192" rx="12" fill="var(--surface-2)" stroke="var(--border-strong)" />
          <rect x="50" y="22" width="34" height="48" rx="6" fill="var(--text-2)" /><text x="67" y="88" text-anchor="middle" font-size="12" fill="var(--text)">L</text>
          <rect x="236" y="22" width="34" height="48" rx="6" fill="var(--text-2)" /><text x="253" y="88" text-anchor="middle" font-size="12" fill="var(--text)">R</text>
          <path d="M67 70 L160 150 L253 70" fill="none" stroke="var(--brand-ink)" stroke-dasharray="4 4" />
          <circle cx="160" cy="152" r="10" fill="var(--brand)" stroke="var(--brand-ink)" stroke-width="2" />
          <text x="160" y="182" text-anchor="middle" font-size="12" fill="var(--text)">{t('Hörplatz')}</text>
        </svg>
        <ol class="steps-text">
          <li>{t('Stelle das Mikrofon dorthin, wo du sonst hörst, auf Ohrhöhe (am besten auf ein Stativ).')}</li>
          <li>{t('Das Mikrofon zeigt senkrecht zur Decke.')}</li>
          <li>{t('Während der Messung bitte nicht sprechen und nicht im Raum herumlaufen.')}</li>
        </ol>
        {#if expert}
          <div class="field">
            <label for="pos">{t('Anzahl Messpositionen')}</label>
            <select id="pos" class="input" value={s.positions} onchange={(e) => act('set_positions', { count: +e.currentTarget.value })}>
              {#each [1, 3, 5, 7, 9] as n}<option value={n}>{n}</option>{/each}
            </select>
            <span class="hint">{t('Mehr Positionen ergeben eine Korrektur, die für einen größeren Bereich passt.')}</span>
          </div>
        {/if}
        <button class="btn primary block" type="button" onclick={() => act('next')}>{t('Mikrofon steht')}</button>
      </section>

    {:else if s.step === 'level'}
      <section class="stack">
        <h2 class="step-h">{t('Lautstärke prüfen')}</h2>
        <p>{t('Der Aroio spielt ein Rauschen und macht es langsam lauter, bis das Mikrofon genug hört. Es wird nicht unangenehm laut.')}</p>
        {#if s.busy}
          <div class="status-box" role="status"><LoaderCircle size={28} class="spin" aria-hidden="true" /><span>{s.busy}</span></div>
          <progress max="1" value={s.progress} aria-label={t('Fortschritt')}></progress>
        {:else if s.level}
          <p class="notice {s.level.status === 'ok' ? 'ok' : 'warn'}" role="status">
            {#if s.level.status === 'ok'}<CircleCheck size={18} aria-hidden="true" />{:else}<TriangleAlert size={18} aria-hidden="true" />{/if}
            <span>{s.level.text} ({Math.round(s.level.spl)} {s.level.unit || 'dB SPL'})</span></p>
        {/if}
        <button class="btn {s.level?.status === 'ok' ? '' : 'primary'} block" type="button" disabled={!!s.busy} onclick={() => act('level')}>{s.level ? t('Noch einmal prüfen') : t('Lautstärke prüfen')}</button>
        {#if s.level?.status === 'ok'}<button class="btn primary block" type="button" onclick={() => act('next')}>{t('Weiter')}</button>{/if}
      </section>

    {:else if s.step === 'measure'}
      <section class="stack">
        <h2 class="step-h">{allMeasured ? t('Alle Messungen fertig') : t('Messung {n} von {total}', { n: s.current + 1, total: s.positions })}</h2>
        {#if !allMeasured}
          <p class="where"><strong>{positionText(s.current)}</strong></p>
        {/if}
        {#if s.issue}
          <p class="notice warn" role="alert"><TriangleAlert size={18} aria-hidden="true" /><span>{s.issue.text}</span></p>
        {/if}
        {#if s.busy}
          <div class="status-box" role="status"><LoaderCircle size={28} class="spin" aria-hidden="true" /><span>{s.busy}</span></div>
          <progress max="1" value={s.progress} aria-label={t('Fortschritt der Messung')}></progress>
        {/if}
        <ol class="positions" aria-label={t('Messpositionen')}>
          {#each Array(s.positions) as _, i}
            {@const n = measuredAt(i)}
            <li class:current={i === s.current && !allMeasured}>
              <button type="button" disabled={!!s.busy} onclick={() => act('select_position', { position: i })}
                      aria-label={t('Position {n}: {state}', { n: i + 1, state: n === 2 ? t('gemessen') : t('offen') })}>
                {#if n === 2}<Check size={18} aria-hidden="true" />{:else}{i + 1}{/if}
              </button>
            </li>
          {/each}
        </ol>
        {#if !allMeasured}
          <button class="btn primary block" type="button" disabled={!!s.busy} onclick={() => act('measure')}>
            {measuredAt(s.current) === 2 ? t('Diese Position neu messen') : t('Messen')}</button>
        {:else}
          <button class="btn primary block" type="button" onclick={() => act('next')}>{t('Weiter')}</button>
        {/if}
      </section>

    {:else if s.step === 'character'}
      <section class="stack">
        <h2 class="step-h">{t('Wie soll es klingen?')}</h2>
        <Segmented legend={t('Klangcharakter')} options={characters} value={s.character} onchange={(v) => act('set_character', { character: v })} />
        <p>{charText[s.character]}</p>
        <p class="muted small">{t('Du kannst das später ändern, indem du neu einmisst.')}</p>
        {#if s.busy}
          <div class="status-box" role="status"><LoaderCircle size={28} class="spin" aria-hidden="true" /><span>{s.busy}</span></div>
        {/if}
        <button class="btn primary block" type="button" disabled={!!s.busy} onclick={() => act('compute')}>{t('Korrektur berechnen')}</button>
      </section>

    {:else if s.step === 'result' && r}
      <section class="stack">
        <h2 class="step-h">{t('Ergebnis')}</h2>
        <p>{t('Abweichung vom Ziel im Bass: vorher {a}, mit Korrektur {b}.', { a: db(ch.deviation_before), b: db(ch.deviation_after) })}</p>
        <Segmented legend={t('Lautsprecher')} options={[{ value: 'L', label: t('Links') }, { value: 'R', label: t('Rechts') }]} value={channel} onchange={(v) => (channel = v)} />
        <FrequencyChart freqs={r.freqs} fmin={20} fmax={expert ? 20000 : 1000} ymin={-20} ymax={15}
          summary={t('Frequenzgang {ch}: gemessen, Ziel und mit Korrektur', { ch: channel === 'L' ? t('links') : t('rechts') })}
          series={[
            { label: t('Gemessen'), values: ch.before, color: 'var(--text-2)', width: 2 },
            { label: t('Ziel'), values: ch.target, color: 'var(--warn)', dash: '6 4', width: 2 },
            { label: t('Mit Korrektur'), values: ch.after, color: 'var(--brand-ink)', width: 3 },
          ]} />
        {#if r.distance_cm > 2}<p class="muted small">{t('Ein Lautsprecher steht {cm} cm weiter weg. Der Aroio gleicht die Laufzeit aus.', { cm: r.distance_cm.toLocaleString('de-DE') })}</p>{/if}
        {#if expert}
          <details><summary>{t('Filter ({n})', { n: ch.filters.length })}</summary>
            <table class="filters"><thead><tr><th>{t('Frequenz')}</th><th>{t('Pegel')}</th><th>Q</th></tr></thead>
              <tbody>{#each ch.filters as f}<tr><td>{f.freq} Hz</td><td>{db(f.gain)}</td><td>{f.q}</td></tr>{/each}</tbody></table>
          </details>
        {/if}

        <div class="card stack">
          <h3>{t('Probehören')}</h3>
          <Segmented legend={t('Was soll spielen?')} hideLegend options={[{ value: 'new', label: t('Mit neuer Korrektur') }, { value: 'old', label: t('Wie vorher') }]}
                     value={listen} onchange={(v) => { listen = v; act('listen', { which: v }); announce(v === 'new' ? t('Neue Korrektur aktiv') : t('Vorherige Einstellung aktiv')); }} />
          <p class="muted small">{t('Starte Musik und schalte hin und her.')}</p>
        </div>

        <div class="field">
          <label for="rcname">{t('Name für diese Einstellung')}</label>
          <input id="rcname" class="input" bind:value={name} maxlength="40" autocomplete="off" />
        </div>
        <button class="btn primary block" type="button" onclick={() => act('save', { name })}>{t('Speichern und verwenden')}</button>
        <button class="btn ghost block" type="button" onclick={() => act('goto', { step: 'measure' })}>{t('Noch einmal messen')}</button>
      </section>
    {/if}

    {#if s.step_index > 0 && s.step !== 'result' && !s.busy}
      <button class="btn ghost back" type="button" onclick={() => act('back')}>{t('Zurück')}</button>
    {/if}
  {:else}
    <p class="muted" role="status">{t('Lädt …')}</p>
  {/if}
</div>

<Dialog bind:open={confirmCancel} title={t('Messung abbrechen?')}>
  <p>{t('Die bisherigen Messungen gehen verloren. Deine Klangeinstellung bleibt wie vorher.')}</p>
  {#snippet actions()}
    <button class="btn" type="button" onclick={() => (confirmCancel = false)}>{t('Weiter messen')}</button>
    <button class="btn danger" type="button" onclick={cancel}>{t('Abbrechen')}</button>
  {/snippet}
</Dialog>

<style>
  .wiz { max-width: 640px; }
  .step-h { font-size: 1.375rem; }
  .need { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
  .need li { display: flex; gap: 12px; align-items: center; padding: 12px 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  .need :global(svg) { color: var(--brand-ink); flex: none; }
  .status-box { display: flex; gap: 14px; align-items: center; padding: 16px; border-radius: var(--radius); background: var(--surface); border: 1px solid var(--border); }
  :global(.ok-ic) { color: var(--ok); }
  progress { width: 100%; height: 10px; accent-color: var(--brand-ink); }
  .room-pic { width: 100%; max-width: 420px; align-self: center; }
  .steps-text { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; }
  .where { font-size: 1.125rem; }
  .positions { list-style: none; padding: 0; margin: 0; display: flex; gap: 8px; flex-wrap: wrap; }
  .positions button { width: 48px; height: 48px; border-radius: 50%; border: 2px solid var(--border-strong); background: var(--surface); font-weight: 700; display: grid; place-items: center; }
  .positions li.current button { border-color: var(--brand-ink); background: var(--brand-soft); color: var(--brand-soft-ink); }
  .filters { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  .filters th, .filters td { text-align: right; padding: 6px; border-bottom: 1px solid var(--border); }
  details summary { cursor: pointer; font-weight: 600; color: var(--brand-ink); min-height: var(--tap); display: flex; align-items: center; }
  .done { align-items: flex-start; padding-top: 16px; }
  .back { margin-top: 12px; }
  label.btn { cursor: pointer; }
  label.btn:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
</style>
