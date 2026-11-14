<script>
  // Development simulator: the real app in a device frame (switch between
  // phone, tablet and desktop) next to a simulated Aroio and the outside world.
  import { onMount } from 'svelte';
  import { Smartphone, Tablet, Monitor, RotateCw, Columns2, Minus, Plus, Play, Pause, Power, RefreshCw, Volume2, VolumeX, Mic } from '@lucide/svelte';
  import { HostAudio } from './audio.js';
  import Toasts from '../components/Toasts.svelte';
  import { app, toast } from '../lib/state.svelte.js';
  import { sim, api, config } from '../lib/api.js';

  const DEVICES = [
    { id: 'mini', label: 'iPhone 13 mini', w: 375, h: 812, kind: 'phone' },
    { id: 'iphone', label: 'iPhone 15', w: 393, h: 852, kind: 'phone' },
    { id: 'pixel', label: 'Pixel 8', w: 412, h: 915, kind: 'phone' },
    { id: 'ipad', label: 'iPad', w: 820, h: 1180, kind: 'tablet' },
    { id: 'laptop', label: 'Laptop', w: 1280, h: 800, kind: 'desktop' },
    { id: 'desktop', label: 'Desktop', w: 1920, h: 1080, kind: 'desktop' },
  ];
  const saved = (() => { try { return JSON.parse(localStorage.getItem('aroio-sim') || '{}'); } catch { return {}; } })();
  let deviceId = $state(saved.deviceId || 'mini');
  let landscape = $state(saved.landscape || false);
  let both = $state(saved.both || false);
  let path = $state(saved.path || '/');
  let stage = $state(null), sw = $state(1000), sh = $state(800);
  let reloadKey = $state(0);

  // ── sound on the host + real microphone ──
  const audio = new HostAudio();
  let au = $state({ ...audio.state });
  audio.onState = (st) => (au = st);
  let mics = $state([]), micId = $state(saved.micId || ''), micLevel = $state(null);
  let autoUmik = $state(saved.autoUmik ?? true);
  const secure = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices;

  $effect(() => { audio.update(app.topics.sim, app.topics.player, app.now); });

  async function toggleAudio() {
    if (au.enabled) { await audio.disable(); return; }
    await audio.enable();
    audio.setHostDb(saved.hostDb ?? -12);
    await findMics(false);
  }
  async function findMics(ask) {
    if (!secure) { toast('Mikrofon nur über http://localhost (sicherer Kontext).', 'danger'); return; }
    try {
      if (ask) (await navigator.mediaDevices.getUserMedia({ audio: true })).getTracks().forEach((t) => t.stop());
      mics = (await navigator.mediaDevices.enumerateDevices()).filter((x) => x.kind === 'audioinput' && x.label);
    } catch (e) { toast('Mikrofon nicht freigegeben: ' + e.message, 'danger'); return; }
    if (!autoUmik || !au.enabled) return;
    const umik = mics.find((x) => /umik|minidsp/i.test(x.label));
    if (umik && (s?.mic_mode !== 'host' || micId !== umik.deviceId)) await chooseMic(umik.deviceId);
    else if (!umik && s?.mic_mode === 'host' && !mics.find((x) => x.deviceId === micId)) await setMode('sim');
  }
  async function chooseMic(id) {
    if (!au.enabled) await audio.enable();
    try {
      const trackLabel = await audio.useMic(id);
      const label = mics.find((x) => x.deviceId === id)?.label || trackLabel;
      micId = id;
      await ev('mic_mode', { mode: 'host', label });
    } catch (e) { toast('Mikrofon: ' + e.message, 'danger'); }
  }
  async function setMode(mode) {
    if (mode === 'host') { await findMics(true); const m = mics.find((x) => x.deviceId === micId) || mics.find((x) => /umik|minidsp/i.test(x.label)) || mics[0]; if (m) await chooseMic(m.deviceId); return; }
    audio.releaseMic();
    await ev('mic_mode', { mode, label: '' });
  }
  onMount(() => {
    if (!secure) return;
    const onChange = () => findMics(false);
    navigator.mediaDevices.addEventListener('devicechange', onChange);
    navigator.permissions?.query({ name: 'microphone' }).then((r) => { if (r.state === 'granted') findMics(false); }).catch(() => {});
    const t = setInterval(() => { micLevel = audio.micLevel(); }, 200);
    return () => { navigator.mediaDevices.removeEventListener('devicechange', onChange); clearInterval(t); audio.releaseMic(); };
  });

  $effect(() => { try { localStorage.setItem('aroio-sim', JSON.stringify({ deviceId, landscape, both, path, micId, autoUmik, hostDb: au.hostDb })); } catch { /* ignore */ } });
  $effect(() => {
    if (!stage) return;
    const ro = new ResizeObserver(([e]) => { sw = e.contentRect.width; sh = e.contentRect.height; });
    ro.observe(stage);
    return () => ro.disconnect();
  });

  const dev = $derived(DEVICES.find((d) => d.id === deviceId));
  function frame(d, rotate, share = 1) {
    const w = rotate ? d.h : d.w, h = rotate ? d.w : d.h;
    const bezel = d.kind === 'desktop' ? 24 : 28;
    const scale = Math.min(1, (sw * share - 32) / (w + bezel), (sh - 56) / (h + bezel));
    return { w, h, scale, bezel };
  }
  const frames = $derived(both
    ? [{ d: DEVICES[0], f: frame(DEVICES[0], false, 0.3) }, { d: DEVICES[4], f: frame(DEVICES[4], false, 0.7) }]
    : [{ d: dev, f: frame(dev, landscape && dev.kind !== 'desktop') }]);

  const s = $derived(app.topics.sim);
  const p = $derived(app.topics.player);
  const d = $derived(app.topics.device);
  const ev = async (name, data) => { try { await sim(name, data); } catch (e) { toast(e.message, 'danger'); } };
  const ext = (source) => ev('external_start', { source });
  const extNames = { airplay: 'AirPlay (iPhone)', spotify: 'Spotify Connect', bluetooth: 'Bluetooth-Handy', upnp: 'UPnP (BubbleUPnP)', roon: 'Roon', input: 'Eingang (Signal)' };
  const IR = [['KEY_PLAYPAUSE', '⏯'], ['KEY_PREVIOUS', '⏮'], ['KEY_NEXT', '⏭'], ['KEY_VOLUMEDOWN', 'Vol −'], ['KEY_VOLUMEUP', 'Vol +'], ['KEY_MUTE', 'Stumm'], ['KEY_1', '1'], ['KEY_2', '2'], ['KEY_3', '3']];
</script>

<Toasts />
<div class="sim">
  <aside class="panel" aria-label="Simulator-Steuerung">
    <header><img src="/icons/logo.svg" alt="" width="28" height="28" /><h1>Aroio Simulator</h1></header>

    <section>
      <h2>Ansicht</h2>
      <div class="devs">
        {#each DEVICES as x}
          <button class:on={!both && deviceId === x.id} onclick={() => { both = false; deviceId = x.id; }}>
            {#if x.kind === 'phone'}<Smartphone size={16} />{:else if x.kind === 'tablet'}<Tablet size={16} />{:else}<Monitor size={16} />{/if}
            {x.label} <small>{x.w}×{x.h}</small></button>
        {/each}
      </div>
      <div class="btns two">
        <button class:on={landscape} disabled={both || dev.kind === 'desktop'} onclick={() => (landscape = !landscape)}><RotateCw size={16} />Querformat</button>
        <button class:on={both} onclick={() => (both = !both)}><Columns2 size={16} />Mobil + Desktop</button>
      </div>
      <label class="lbl">Seite
        <select bind:value={path}>
          {#each [['/', 'Start'], ['/musik', 'Musik'], ['/klang', 'Klang'], ['/klang/raumkorrektur', 'Raumkorrektur'], ['/einstellungen', 'Einstellungen'], ['/einstellungen/dienste', 'Dienste']] as [v, l]}<option value={v}>{l}</option>{/each}
        </select></label>
      <div class="btns two">
        <button onclick={() => reloadKey++}><RefreshCw size={16} />App neu laden</button>
        <button onclick={() => config({ device: { theme: d?.theme === 'dark' ? 'light' : d?.theme === 'light' ? 'auto' : 'dark' } })}>Thema: {d?.theme}</button>
      </div>
    </section>

    <section>
      <h2>Ton am Rechner</h2>
      <button class:on={au.enabled} onclick={toggleAudio}>{#if au.enabled}<Volume2 size={16} />Ton ist an (ausschalten){:else}<VolumeX size={16} />Ton einschalten{/if}</button>
      {#if au.enabled}
        <label class="lbl">Lautstärke am Rechner: {au.hostDb} dB
          <input type="range" min="-40" max="0" step="1" value={au.hostDb} oninput={(e) => audio.setHostDb(+e.currentTarget.value)} /></label>
        <button class:on={au.roomOn} onclick={() => audio.setRoom(!au.roomOn)}>Virtueller Raum hörbar: {au.roomOn ? 'an' : 'aus'}</button>
        <p class="hint">Musik ist synthetisch (pro Titel anders). Der DSP-Weg ist die echte CamillaDSP-Konfiguration aus aroiod. Mit „virtuellem Raum“ hörst du die Raummoden des Simulators und damit die Wirkung der Raumkorrektur.</p>
      {/if}
    </section>

    {#if s}
      <section>
        <h2>Gerät</h2>
        <div class="row2">
          <label class="lbl">Modell<select value={s.model} onchange={(e) => ev('model', { model: e.currentTarget.value })}>
            {#each ['AroioSU', 'AroioEX', 'AroioLT', 'RaspberryPi'] as m}<option>{m}</option>{/each}</select></label>
          <label class="lbl">Pi<select value={s.board} onchange={(e) => ev('board', { board: e.currentTarget.value })}>
            {#each [['pi3b', 'Pi 3 B'], ['pi4', 'Pi 4'], ['pi5', 'Pi 5']] as [v, l]}<option value={v}>{l}</option>{/each}</select></label>
        </div>
        <div class="box">
          <div class="display" class:rot={false} aria-label="Display des Aroio">{#each s.display as line}<div>{line || ' '}</div>{/each}</div>
          <div class="leds">
            <span class="led {s.leds.network}"></span>Netz
            <span class="led {s.booting ? 'blink' : 'on'}"></span>Status
            {#if s.tone && Date.now() / 1000 - s.tone.at < 2}<span class="tone">♪ {s.tone.channel}</span>{/if}
          </div>
          <div class="knob">
            <button onclick={() => ev('encoder', { steps: -1 })} aria-label="Drehgeber links"><Minus size={16} /></button>
            <span>{p?.volume ?? '—'}{#if s.volume_db != null} <small>({s.volume_db} dB)</small>{/if}</span>
            <button onclick={() => ev('encoder', { steps: 1 })} aria-label="Drehgeber rechts"><Plus size={16} /></button>
            <button onclick={() => ev('key', { key: 'play_pause' })} aria-label="Taste Play/Pause">{#if p?.state === 'playing'}<Pause size={16} />{:else}<Play size={16} />{/if}</button>
          </div>
        </div>
        <h3>Fernbedienung (IR)</h3>
        <div class="ir">{#each IR as [k, l]}<button onclick={() => ev('key', { key: k })}>{l}</button>{/each}</div>
      </section>

      <section>
        <h2>Von außen abspielen</h2>
        {#each s.external as x}
          <div class="pair">
            <button class:on={p?.source === x && p?.state === 'playing'} onclick={() => ext(x)}>▶ {extNames[x]}</button>
            <button onclick={() => ev('external_stop', { source: x })} aria-label="{extNames[x]} stoppen">■</button>
          </div>
        {/each}
        <button onclick={() => ev('track_end')}>Titel fast zu Ende</button>
      </section>

      <section>
        <h2>Messmikrofon</h2>
        <button class:on={s.mic_mode === 'sim'} onclick={() => setMode('sim')}><Mic size={16} />Simulierter Raum (UMIK simuliert)</button>
        <button class:on={s.mic_mode === 'host'} disabled={!secure} onclick={() => setMode('host')}><Mic size={16} />Echtes Mikrofon am Rechner</button>
        <button class:on={s.mic_mode === 'none'} onclick={() => setMode('none')}>Kein Mikrofon</button>
        {#if s.mic_mode === 'host'}
          <label class="lbl">Mikrofon
            <select value={micId} onchange={(e) => chooseMic(e.currentTarget.value)}>
              {#each mics as m}<option value={m.deviceId}>{m.label}</option>{/each}
            </select></label>
          <div class="meter" aria-label="Eingangspegel"><i style="width:{micLevel == null ? 0 : Math.max(0, Math.min(100, (micLevel + 80) * 1.25))}%"></i></div>
          <p class="hint">{micLevel == null ? 'Kein Signal' : `${micLevel.toFixed(1)} dBFS`}{au.busy ? ` · ${au.busy} läuft` : ''}. Die Messung spielt die Sweeps über die Lautsprecher des Rechners. „Ton am Rechner“ muss an sein. Die Kalibrierdatei des UMIK im Assistenten hochladen.</p>
        {/if}
        <label class="check"><input type="checkbox" bind:checked={autoUmik} /> UMIK am Rechner automatisch verwenden, sonst simulieren</label>
        {#if !secure}<p class="hint">Echtes Mikrofon nur über http://localhost.</p>{/if}
        <button class:on={s.noise_next} onclick={() => ev('noise_next')}>Nächste Messung mit Störgeräusch</button>
      </section>

      <section>
        <h2>Netzwerk und Dienste</h2>
        <button class:on={s.lan} onclick={() => ev('lan', { on: !s.lan })}>LAN-Kabel {s.lan ? 'ziehen' : 'stecken'}</button>
        <button disabled={!s.wifi} onclick={() => ev('wifi_drop')}>WLAN trennen</button>
        <button class:on={s.internet} onclick={() => ev('internet', { on: !s.internet })}>Internet {s.internet ? 'weg' : 'da'}</button>
        <button class:on={!!s.lyrion_external} onclick={() => ev('lyrion_external', { server: s.lyrion_external ? '' : '192.168.1.10' })}>Lyrion im Netz: {s.lyrion_external || 'keiner'}</button>
        <button class:on={s.spotify_needs_key} onclick={() => ev('spotify_needs_key', { on: !s.spotify_needs_key })}>Spotify-Konto braucht Soloist-Key</button>
        <button onclick={() => ev('tidal_confirm')}>TIDAL-Code am Handy bestätigen</button>
        <button onclick={() => ev('bt_phone_pairs')}>Handy koppelt per Bluetooth</button>
      </section>

      <section>
        <h2>System</h2>
        <button onclick={() => ev('update_available', { version: '0.2.0' })}>Update anbieten</button>
        <button onclick={() => api.post('/system/reboot')}><Power size={16} />Neustart</button>
        <button onclick={() => ev('old_device')}>Altgerät migrieren (aroio-ng)</button>
        <button onclick={() => ev('first_boot', { lan: false })}>Erststart ohne Netz</button>
        <button onclick={() => ev('first_boot', { lan: true })}>Erststart mit LAN</button>
      </section>

      <section>
        <h2>CamillaDSP</h2>
        <p class="mono">{s.camilla.samplerate} Hz{#if s.camilla.capture_samplerate} ← {s.camilla.capture_samplerate} Hz{/if} · {s.camilla.loads}× geladen</p>
        <p class="mono">{s.camilla.pipeline.length ? JSON.stringify(s.camilla.pipeline) : 'Pipeline leer (bitgenau)'}</p>
        <p class="mono">{s.clients} App(s) verbunden</p>
      </section>

      <section>
        <h2>Ereignisse</h2>
        <ol class="log">{#each s.events as e}<li><span>{e.t}</span> {e.text}</li>{/each}</ol>
      </section>
    {:else}
      <p>Verbinde mit aroiod …</p>
    {/if}
  </aside>

  <main class="stage" bind:this={stage}>
    <div class="frames">
      {#each frames as { d: x, f } (x.id + both)}
        <figure style="width:{(f.w + f.bezel) * f.scale}px;height:{(f.h + f.bezel) * f.scale}px">
          <div class="device {x.kind}" style="width:{f.w + f.bezel}px;height:{f.h + f.bezel}px;transform:scale({f.scale})">
            {#key reloadKey + path}
              <iframe title="Aroio-App auf {x.label}" src={path} width={f.w} height={f.h}></iframe>
            {/key}
          </div>
          <figcaption>{x.label} · {f.w}×{f.h} · {Math.round(f.scale * 100)} %</figcaption>
        </figure>
      {/each}
    </div>
  </main>
</div>

<style>
  .sim { display: grid; grid-template-columns: 330px 1fr; height: 100dvh; background: var(--surface-3); }
  .panel { overflow: auto; background: var(--surface); border-right: 1px solid var(--border); padding: 16px; font-size: .875rem; }
  header { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
  h1 { font-size: 1.125rem; }
  h2 { font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; color: var(--text-2); margin: 20px 0 8px; }
  h3 { font-size: .8125rem; margin: 12px 0 6px; color: var(--text-2); }
  button { display: flex; align-items: center; gap: 6px; width: 100%; min-height: 36px; padding: 6px 10px; margin: 4px 0; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-2); text-align: left; font-size: .8125rem; }
  button:hover:not(:disabled) { background: var(--surface-3); }
  button.on { background: var(--brand); color: var(--on-brand); border-color: var(--brand-ink); }
  button:disabled { opacity: .45; }
  button small { margin-left: auto; color: inherit; opacity: .7; }
  .devs button { margin: 3px 0; }
  .btns { display: grid; grid-template-columns: 1fr 1fr; gap: 0 6px; }
  .btns.two button { justify-content: center; }
  .pair { display: grid; grid-template-columns: 1fr 40px; gap: 6px; }
  .pair button:last-child { justify-content: center; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .lbl { display: flex; flex-direction: column; gap: 2px; font-weight: 600; margin: 6px 0; }
  select { min-height: 36px; border-radius: 8px; border: 1px solid var(--border-strong); background: var(--surface); padding: 4px 8px; }
  .box { background: #1c2526; color: #e6f2f2; border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }
  .display { background: #061212; color: #62f0f0; font-family: var(--mono); font-size: .8125rem; padding: 8px 10px; border-radius: 6px; min-height: 84px; border: 1px solid #0b3a3a; }
  .display div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .leds { display: flex; align-items: center; gap: 6px; font-size: .75rem; }
  .led { width: 10px; height: 10px; border-radius: 50%; background: #3a4747; margin-left: 6px; }
  .led.on { background: #3ce07a; box-shadow: 0 0 8px #3ce07a; }
  .led.blink { background: #f0b43c; animation: blink 1s steps(2) infinite; }
  @keyframes blink { 50% { opacity: .2; } }
  .tone { margin-left: auto; color: #62f0f0; font-weight: 700; }
  .knob { display: grid; grid-template-columns: 40px 1fr 40px 40px; gap: 6px; align-items: center; text-align: center; }
  .knob button { justify-content: center; background: #2b3839; color: #fff; border-color: #475a5b; margin: 0; }
  .ir { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
  .ir button { justify-content: center; margin: 0; }
  .hint { font-size: .75rem; color: var(--text-2); margin: 4px 0; }
  .check { display: flex; gap: 8px; align-items: center; margin: 8px 0; font-size: .8125rem; }
  .meter { height: 8px; border-radius: 4px; background: var(--surface-3); overflow: hidden; margin: 6px 0; }
  .meter i { display: block; height: 100%; background: var(--brand); transition: width .15s; }
  input[type=range] { width: 100%; accent-color: var(--brand-ink); }
  .mono { font-family: var(--mono); font-size: .75rem; word-break: break-all; margin: 4px 0; }
  .log { list-style: none; padding: 0; margin: 0; font-size: .75rem; max-height: 220px; overflow: auto; }
  .log li { padding: 3px 0; border-bottom: 1px solid var(--border); }
  .log span { color: var(--text-2); font-family: var(--mono); }
  .stage { overflow: hidden; display: grid; place-items: center; padding: 16px; }
  .frames { display: flex; gap: 24px; align-items: center; justify-content: center; width: 100%; }
  figure { margin: 0; position: relative; }
  .device { transform-origin: top left; background: #101617; padding: 14px; border-radius: 48px; box-shadow: 0 20px 60px rgb(0 0 0 / .35); }
  .device.tablet { border-radius: 36px; }
  .device.desktop { border-radius: 14px; padding: 12px; }
  iframe { display: block; border: 0; background: var(--bg); border-radius: 36px; }
  .device.tablet iframe { border-radius: 22px; }
  .device.desktop iframe { border-radius: 4px; }
  figcaption { position: absolute; left: 0; right: 0; bottom: -26px; text-align: center; font-size: .75rem; color: var(--text-2); }
</style>
