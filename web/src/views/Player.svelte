<script>
  import { logoUrl } from '../lib/assets.js';
  import { Play, Pause, Square, SkipBack, SkipForward, Shuffle, Repeat, Repeat1, ListMusic, ChevronDown, BadgeCheck, AudioWaveform, Radio, Smartphone, TriangleAlert } from '@lucide/svelte';
  import Cover from '../components/Cover.svelte';
  import VolumeSlider from '../components/VolumeSlider.svelte';
  import QueueList from '../components/QueueList.svelte';
  import LevelMeter from '../components/LevelMeter.svelte';
  import { app, position, toast } from '../lib/state.svelte.js';
  import { player } from '../lib/api.js';
  import { time, timeSpoken, quality, rate } from '../lib/format.js';
  import { t } from '../lib/i18n.svelte.js';

  const p = $derived(app.topics.player);
  const d = $derived(app.topics.device);
  const sig = $derived(p?.signal || {});
  const pos = $derived(position(p, app.now));
  const dur = $derived(p?.track?.duration || 0);
  const enabled = $derived((app.topics.sources || []).filter((s) => s.enabled));
  let seeking = $state(null);

  const act = async (a, data) => { try { await player(a, data); } catch (e) { toast(e.message, 'danger'); } };
  const repeatNext = { off: 'all', all: 'one', one: 'off' };
  const repeatLabel = $derived({ off: t('Wiederholen: aus'), all: t('Wiederholen: alle'), one: t('Wiederholen: einen Titel') }[p?.repeat || 'off']);

  const hints = $derived({
    spotify: t('Öffne Spotify und wähle „{name}“ als Lautsprecher.', { name: d?.name }),
    airplay: t('Wähle auf dem iPhone oder Mac „{name}“ als AirPlay-Lautsprecher.', { name: d?.name }),
    bluetooth: t('Verbinde dein Handy per Bluetooth mit „{name}“.', { name: d?.name }),
    upnp: t('Wähle „{name}“ in deiner UPnP-App (z. B. BubbleUPnP) als Renderer.', { name: d?.name }),
    roon: t('Wähle „{name}“ in Roon als Zone.', { name: d?.name }),
    input: t('Der Eingang spielt automatisch, sobald ein Signal anliegt.'),
    netjack: t('Starte auf dem Rechner „jackd -d net“, dann spielt sein Ton über „{name}“.', { name: d?.name }),
  });
</script>

<div class="player-page" class:empty={!p?.track}>
  <h1 class="sr-only">{t('Wiedergabe')}</h1>
  {#if d?.sound_card_missing}
    <p class="notice warn card-missing"><TriangleAlert size={20} aria-hidden="true" /><span>{t('Keine Soundkarte gefunden. Manche Karten melden sich nicht selbst: Wähle deine unter')} <a href="/einstellungen/ton">{t('Einstellungen › Ton')}</a>.</span></p>
  {/if}

  {#if !p?.track}
    <section class="page idle">
      <div class="hello">
        <img src={logoUrl} alt="" width="64" height="64" />
        <h2>{d?.name}</h2>
        <p class="muted">{t('Gerade läuft nichts.')}</p>
      </div>
      {#if enabled.some((s) => s.id === 'lms')}<a class="btn primary block" href="/musik">{t('Musik auswählen')}</a>{/if}
      <h2 class="section-title">{t('Oder vom Handy abspielen')}</h2>
      <ul class="list">
        {#each enabled.filter((s) => s.id !== 'lms') as s}
          <li class="hint"><Smartphone size={20} aria-hidden="true" /><span><strong>{s.name}</strong><br /><span class="muted small">{hints[s.id]}</span></span></li>
        {/each}
      </ul>
    </section>
  {:else}
    <section class="now page" aria-label={t('Läuft gerade')}>
      <div class="art"><Cover src={p.track.image} size={480} radius={20} alt={t('Cover von {album}', { album: p.track.album || p.track.title })} /></div>

      <div class="meta">
        <p class="source"><span class="badge">{#if p.track.live}<Radio size={14} aria-hidden="true" />{/if}{p.source_name}{#if p.track.controller && p.source !== 'lms'}{' · '}{p.track.controller}{/if}</span>
          {#if p.state !== 'playing'}<span class="badge">{p.state === 'paused' ? t('Pausiert') : t('Gestoppt')}</span>{/if}</p>
        <h2 class="title">{p.track.title}</h2>
        <p class="artist">{p.track.artist}{#if p.track.album}{' · '}<span class="muted">{p.track.album}</span>{/if}</p>
        <p class="quality">
          {#if p.track.format}<span class="badge brand">{quality(p.track.format)}</span>{/if}
          {#if sig.bit_perfect}<span class="badge ok"><BadgeCheck size={14} aria-hidden="true" />{t('Bitgenau')}</span>
          {:else if sig.processing}<span class="badge"><AudioWaveform size={14} aria-hidden="true" />{sig.preset}</span>{/if}
          {#if sig.resampled}<span class="badge warn">{t('umgerechnet auf {r}', { r: rate(sig.rate_out) })}</span>{/if}
        </p>
      </div>

      <div class="meter"><LevelMeter /></div>

      <div class="progress">
        {#if dur}
          <input type="range" min="0" max={Math.floor(dur)} step="1" value={Math.floor(seeking ?? pos)}
                 disabled={!p.can?.seek} aria-label={t('Position im Titel')}
                 aria-valuetext={t('{pos} von {dur}', { pos: timeSpoken(seeking ?? pos, t), dur: timeSpoken(dur, t) })}
                 style="--p:{((seeking ?? pos) / dur) * 100}%"
                 oninput={(e) => (seeking = +e.currentTarget.value)}
                 onchange={async (e) => { await act('seek', { position: +e.currentTarget.value }); seeking = null; }} />
          <div class="times" aria-hidden="true"><span>{time(seeking ?? pos)}</span><span>−{time(dur - (seeking ?? pos))}</span></div>
        {:else}
          <p class="muted small live">{p.track.live ? t('Live') : time(pos)}</p>
        {/if}
      </div>

      <!-- only buttons that work with this source (p.can comes from the Aroio) -->
      <div class="transport" class:few={!p.can?.shuffle && !p.can?.queue}>
        {#if p.can?.shuffle}
          <button class="icon-btn side" type="button" aria-pressed={p.shuffle}
                  onclick={() => act('shuffle', { on: !p.shuffle })} aria-label={t('Zufällige Reihenfolge')}><Shuffle size={22} aria-hidden="true" /></button>
        {:else if p.can?.queue}<span class="slot side" aria-hidden="true"></span>{/if}
        {#if p.can?.previous}
          <button class="icon-btn" type="button" onclick={() => act('previous')} aria-label={t('Vorheriger Titel')}><SkipBack size={30} fill="currentColor" aria-hidden="true" /></button>
        {:else if p.can?.next}<span class="slot" aria-hidden="true"></span>{/if}
        {#if p.state === 'playing' && p.can?.pause}
          <button class="play" type="button" onclick={() => act('pause')} aria-label={t('Pause')}><Pause size={34} fill="currentColor" aria-hidden="true" /></button>
        {:else if p.state === 'playing' && p.can?.stop}
          <button class="play" type="button" onclick={() => act('stop')} aria-label={t('Stopp')}><Square size={28} fill="currentColor" aria-hidden="true" /></button>
        {:else if p.state !== 'playing'}
          <!-- greyed out when only the sender can start it again -->
          <button class="play" type="button" disabled={!p.can?.play} onclick={() => act('play')} aria-label={t('Abspielen')}
                  aria-describedby={p.can?.play ? undefined : 'control-hint'}><Play size={34} fill="currentColor" aria-hidden="true" /></button>
        {/if}
        {#if p.can?.next}
          <button class="icon-btn" type="button" onclick={() => act('next')} aria-label={t('Nächster Titel')}><SkipForward size={30} fill="currentColor" aria-hidden="true" /></button>
        {:else if p.can?.previous}<span class="slot" aria-hidden="true"></span>{/if}
        {#if p.can?.queue}
          <button class="icon-btn side" type="button" aria-pressed={p.repeat !== 'off'}
                  onclick={() => act('repeat', { mode: repeatNext[p.repeat] })} aria-label={repeatLabel}>
            {#if p.repeat === 'one'}<Repeat1 size={22} aria-hidden="true" />{:else}<Repeat size={22} aria-hidden="true" />{/if}
          </button>
        {:else if p.can?.shuffle}<span class="slot side" aria-hidden="true"></span>{/if}
      </div>
      {#if p.state !== 'playing' && !p.can?.play && p.source !== 'lms'}
        <p class="muted small control-hint" id="control-hint">{t('Weiter geht es in der App auf dem Zuspieler.')}</p>
      {/if}

      <div class="volume">
        {#if d?.fixed_level}
          <p class="notice small">{t('Dieses Modell gibt einen festen Pegel aus. Die Lautstärke stellst du am Verstärker oder an den Lautsprechern.')}</p>
        {:else}
          <VolumeSlider value={p.volume} limit={p.volume_limit} muted={p.muted} />
        {/if}
      </div>

      <details class="signal">
        <summary><span>{t('Signalweg')}</span><ChevronDown size={18} aria-hidden="true" /></summary>
        <ol>
          <li><strong>{t('Quelle')}</strong><span>{p.source_name}: {quality(p.track.format) || '–'}</span></li>
          <li><strong>{t('Aroio')}</strong><span>
            {#if sig.processing}{t('Klang: {preset}', { preset: sig.preset })}{#if sig.cleaner}{', '}Cleaner{/if}{#if sig.mono}{', '}{t('Mono')}{/if}{:else}{t('Unverändert durchgereicht')}{/if}
            {#if sig.resampled}{' · '}{t('Umrechnung {a} → {b}', { a: rate(sig.rate_in), b: rate(sig.rate_out) })}{/if}
            {#if sig.note === 'missing_rate'}{' · '}{t('Für diese Abtastrate gibt es keinen Filter.')}{/if}
          </span></li>
          <li><strong>{t('Wandler')}</strong><span>{rate(sig.rate_out)}{#if d?.expert_mode && sig.load != null}{' · '}{t('DSP-Last {l} %', { l: sig.load })}{/if}</span></li>
        </ol>
        <p class="muted small">{sig.bit_perfect ? t('Bitgenau: Die Musik erreicht den Wandler genau so, wie sie in der Datei steht.') : t('Bitgenau wird es ohne Klangkorrektur und bei voller Lautstärke am Aroio (oder mit Lautstärkeregelung im Wandler).')}</p>
      </details>

      <a class="btn queue-link" href="/warteschlange"><ListMusic size={20} aria-hidden="true" />{t('Warteschlange')}</a>
    </section>

    {#if p.can?.queue}
      <section class="queue-side" aria-labelledby="qs-h">
        <h2 id="qs-h">{t('Warteschlange')}</h2>
        <QueueList />
      </section>
    {/if}
  {/if}
</div>

<style>
  .player-page { display: grid; }
  .idle { display: flex; flex-direction: column; gap: 12px; max-width: 560px; }
  .hello { display: grid; justify-items: center; text-align: center; gap: 6px; padding: 32px 0 16px; }
  .hint { display: flex; gap: 12px; padding: 12px 16px; align-items: flex-start; }
  .hint :global(svg) { margin-top: 3px; color: var(--brand-ink); flex: none; }

  .now { display: flex; flex-direction: column; gap: 14px; max-width: 560px; }
  .art { width: min(100%, 46vh); margin: 4px auto 0; aspect-ratio: 1; box-shadow: 0 12px 40px rgb(0 0 0 / .25); border-radius: 20px; }
  .art :global(img), .art :global(.ph) { width: 100%; height: 100%; }
  .meta { display: flex; flex-direction: column; gap: 4px; }
  .source { display: flex; gap: 6px; flex-wrap: wrap; }
  .title { font-size: 1.5rem; }
  .artist { font-size: 1.0625rem; }
  .quality { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }

  .meter { padding-top: 6px; }
  .progress input { width: 100%; height: 32px; -webkit-appearance: none; appearance: none; background: transparent; margin: 0; }
  .progress input::-webkit-slider-runnable-track { height: 6px; border-radius: 3px; background: linear-gradient(to right, var(--text) var(--p), var(--surface-3) var(--p)); }
  .progress input::-moz-range-track { height: 6px; border-radius: 3px; background: var(--surface-3); }
  .progress input::-moz-range-progress { height: 6px; border-radius: 3px; background: var(--text); }
  .progress input::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; margin-top: -6px; border-radius: 50%; background: var(--text); }
  .progress input::-moz-range-thumb { width: 16px; height: 16px; border-radius: 50%; background: var(--text); border: 0; }
  .progress input:focus-visible { outline: 3px solid var(--focus); }
  .times { display: flex; justify-content: space-between; font-size: .8125rem; color: var(--text-2); font-variant-numeric: tabular-nums; }

  .transport { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; }
  .transport .icon-btn { width: 56px; height: 56px; }
  .transport .icon-btn.side { width: 48px; height: 48px; color: var(--text-2); }
  .transport .icon-btn[aria-pressed="true"] { color: var(--brand-ink); background: var(--brand-soft); }
  .transport.few { justify-content: center; gap: 28px; }
  .transport .slot { width: 56px; height: 56px; }
  .transport .slot.side { width: 48px; height: 48px; }
  .control-hint { text-align: center; margin: 0; }
  .play:disabled { background: var(--surface-2, var(--border)); color: var(--text-2); box-shadow: none; cursor: default; }
  .play { width: 76px; height: 76px; border-radius: 50%; border: 0; background: var(--brand); color: var(--on-brand); display: grid; place-items: center; box-shadow: 0 6px 20px rgb(0 170 170 / .35); }
  .play:active { transform: scale(.96); }

  .signal { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 0 16px; }
  .signal summary { list-style: none; display: flex; justify-content: space-between; align-items: center; min-height: 52px; font-weight: 650; cursor: pointer; }
  .signal summary::-webkit-details-marker { display: none; }
  .signal[open] summary :global(svg) { transform: rotate(180deg); }
  .signal ol { margin: 0 0 8px; padding: 0 0 0 20px; display: flex; flex-direction: column; gap: 8px; }
  .signal li { display: flex; flex-direction: column; }
  .signal p { padding-bottom: 14px; }
  .queue-link { align-self: center; }
  .queue-side { display: none; }

  @media (min-width: 1100px) {
    .player-page:not(.empty) { grid-template-columns: minmax(0, 560px) minmax(0, 1fr); gap: 24px; padding: 0 24px; max-width: 1280px; margin: 0 auto; }
    .now { padding-top: 32px; }
    .queue-side { display: flex; flex-direction: column; gap: 12px; padding-top: 40px; min-width: 0; }
    .queue-link { display: none; }
  }
  @media (min-width: 900px) and (max-height: 820px) { .art { width: min(100%, 38vh); } }
  .card-missing { margin: 12px 16px 0; }
  .card-missing a { color: inherit; font-weight: 600; }
</style>
