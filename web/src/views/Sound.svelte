<script>
  import { AudioWaveform, ChevronRight, Mic, Upload, BadgeCheck, Ear } from '@lucide/svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import Toggle from '../components/Toggle.svelte';
  import Segmented from '../components/Segmented.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { api, config } from '../lib/api.js';
  import { rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';

  const dsp = $derived(app.topics.dsp);
  const d = $derived(app.topics.device);
  const rc = $derived(app.topics.roomcorr);
  const hasRoom = $derived(dsp?.presets.some((p) => p.origin === 'roomcorr'));
  const kinds = { bypass: t('unverändert'), peq: t('Equalizer'), fir: t('FIR-Filter') };
  const origins = { roomcorr: t('Raumkorrektur'), import: t('Importiert'), migration: t('Vom alten Aroio'), builtin: '', user: t('Eigene') };

  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
  const activate = async (id) => {
    try { await api.post(`/dsp/presets/${id}/activate`); toast(t('Klang: {name}', { name: dsp.presets.find((p) => p.id === id)?.name })); }
    catch (e) { toast(e.message, 'danger'); }
  };
  const compare = async (on) => { try { await api.post('/dsp/compare', { bypass: on }); } catch (e) { toast(e.message, 'danger'); } };
</script>

<div class="page">
  <PageHeader title={t('Klang')} />

  {#if dsp}
    <section class="card room">
      <div class="row"><span class="ic"><Mic size={22} aria-hidden="true" /></span>
        <div class="grow">
          <h2>{t('Raumkorrektur')}</h2>
          <p class="muted small">{hasRoom ? t('Dein Raum ist eingemessen. Nach dem Umstellen von Möbeln oder Lautsprechern lohnt sich eine neue Messung.') : t('Der Aroio misst deinen Raum mit einem Messmikrofon ein und gleicht störende Raumresonanzen aus. Dauert etwa 10 Minuten.')}</p>
        </div>
      </div>
      <a class="btn primary" href="/klang/raumkorrektur">{rc?.active ? t('Messung fortsetzen') : hasRoom ? t('Neu einmessen') : t('Raum einmessen')}</a>
    </section>

    <fieldset class="presets" disabled={!dsp.enabled}>
      <legend class="section-title">{t('Klangeinstellung')}</legend>
      <ul class="list">
        {#each dsp.presets as p (p.id)}
          <li class="preset">
            <label class="pick">
              <input type="radio" name="preset" checked={dsp.active_preset === p.id} onchange={() => activate(p.id)} />
              <span class="text">
                <span class="name">{p.id === 'bypass' ? t('Ohne Korrektur') : p.name}</span>
                <span class="muted small">{p.id === 'bypass' ? t('Musik bleibt unverändert (bitgenau)') : [origins[p.origin], kinds[p.kind], p.rates ? p.rates.map((r) => rate(r)).join(', ') : ''].filter(Boolean).join(' · ')}</span>
              </span>
            </label>
            {#if p.id !== 'bypass'}
              <a class="icon-btn" href={'/klang/preset/' + p.id} aria-label={t('Details zu {name}', { name: p.name })}><ChevronRight size={20} aria-hidden="true" /></a>
            {/if}
          </li>
        {/each}
      </ul>
    </fieldset>

    {#if dsp.active_preset !== 'bypass' && dsp.enabled}
      <div class="ab card">
        <Ear size={22} aria-hidden="true" />
        <p class="grow">{t('Höre den Unterschied: kurz ohne Korrektur vergleichen.')}</p>
        <button class="btn" type="button" aria-pressed={dsp.compare_bypass} onclick={() => compare(!dsp.compare_bypass)}>
          {dsp.compare_bypass ? t('Korrektur wieder an') : t('Ohne Korrektur hören')}
        </button>
      </div>
    {/if}

    {#if dsp.status?.too_heavy}
      <p class="notice warn">{t('Dieser Filter ist für diesen Raspberry Pi bei {r} zu lang. Es kann zu Aussetzern kommen.', { r: rate(dsp.status.rate_out) })}</p>
    {/if}

    <h2 class="section-title">{t('Weitere Einstellungen')}</h2>
    <ul class="list">
      <li><Toggle label={t('Klangkorrektur')} description={t('Aus: Alle Klangeinstellungen werden umgangen.')} checked={dsp.enabled} onchange={(v) => save({ dsp: { enabled: v } })} /></li>
      <li><Toggle label={t('Cleaner (M/S)')} description={t('Wandelt das Stereosignal in Mitte und Seite um (M/S-Codierung). Nur einschalten, wenn deine Lautsprecher oder dein Verstärker ein M/S-Signal erwarten.')} checked={dsp.ms_cleaner} onchange={(v) => save({ dsp: { ms_cleaner: v } })} /></li>
    </ul>

    {#if d?.expert_mode}
      <h2 class="section-title">{t('Expertenmodus')}</h2>
      <ul class="list">
        <li><a class="link-row" href="/klang/import"><Upload size={20} aria-hidden="true" /><span class="grow">{t('FIR-Filter importieren (Acourate, Audiovero, REW)')}</span><ChevronRight size={20} aria-hidden="true" /></a></li>
      </ul>
      {#if dsp.status}
        <dl class="status card">
          <div><dt>{t('Eingang')}</dt><dd>{rate(dsp.status.rate_in)}</dd></div>
          <div><dt>{t('Ausgang')}</dt><dd>{rate(dsp.status.rate_out)}{dsp.status.resampled ? ' (' + t('umgerechnet') + ')' : ''}</dd></div>
          <div><dt>{t('DSP-Last')}</dt><dd>{dsp.status.load} %</dd></div>
          {#if dsp.status.fir_taps}<div><dt>{t('FIR-Länge')}</dt><dd>{dsp.status.fir_taps.toLocaleString('de-DE')} Taps ({t('Grenze {n}', { n: dsp.status.fir_limit.toLocaleString('de-DE') })})</dd></div>{/if}
          <div><dt>{t('Weg')}</dt><dd>{#if dsp.status.pipeline_empty}<BadgeCheck size={16} aria-hidden="true" /> {t('ohne Bearbeitung')}{:else}<AudioWaveform size={16} aria-hidden="true" /> {t('mit Bearbeitung')}{/if}</dd></div>
        </dl>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .room { display: flex; flex-direction: column; gap: 14px; }
  .room .row { align-items: flex-start; }
  .ic { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px; background: var(--brand-soft); color: var(--brand-soft-ink); flex: none; }
  .room h2 { margin-bottom: 4px; }
  fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
  fieldset:disabled { opacity: .55; }
  legend { padding: 0; }
  .presets { margin-top: 12px; }
  .preset { display: flex; align-items: center; padding-right: 4px; }
  .pick { flex: 1; display: flex; align-items: center; gap: 14px; padding: 12px 16px; min-height: 64px; cursor: pointer; }
  .pick input { width: 22px; height: 22px; accent-color: var(--brand-ink); flex: none; }
  .text { display: flex; flex-direction: column; }
  .name { font-weight: 600; }
  .ab { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
  .ab .btn[aria-pressed="true"] { background: var(--warn-soft); border-color: var(--warn); color: var(--warn); }
  .notice { margin-top: 12px; }
  .link-row { display: flex; align-items: center; gap: 12px; padding: 14px 16px; min-height: 56px; color: inherit; text-decoration: none; font-weight: 600; }
  .status { display: grid; gap: 8px; margin: 12px 0 0; }
  .status div { display: flex; justify-content: space-between; gap: 12px; }
  dt { color: var(--text-2); }
  dd { margin: 0; font-weight: 600; display: flex; gap: 6px; align-items: center; text-align: right; }
</style>
