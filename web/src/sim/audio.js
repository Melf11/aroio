// Sound on the development machine for the simulator page (Web Audio).
//
//   music (synthesised per track) ─▶ CamillaDSP clone ─▶ volume ─┐
//   test tones, noise, sweeps (sim) ─────────────────────────────┼▶ virtual room ─▶ host volume ─▶ limiter ─▶ speakers
//   measurement signals (real mic) ─▶ measurement level ─────────┘ (bypassed: the real room is real)
//
// The DSP part is rebuilt from the exact CamillaDSP config aroiod generated
// (Biquad, Gain, Delay, Conv, Mixer), so presets, room correction and the
// Cleaner (M/S) are audible. The virtual room adds the simulator's room modes,
// so the effect of a room correction can be heard with A/B.

const RATE = 48000;

export class HostAudio {
  constructor() {
    this.ctx = null;
    this.handled = new Set();
    this.cfgKey = '';
    this.synth = null;
    this.trackKey = '';
    this.micStream = null;
    this.onState = () => {};
    this.state = { enabled: false, roomOn: true, hostDb: -12, playing: false, busy: null };
  }

  // ── setup (must be called from a click: browsers block audio before that) ──
  async enable() {
    if (this.ctx) { await this.ctx.resume(); return; }
    const ctx = new AudioContext({ sampleRate: RATE, latencyHint: 'playback' });
    this.ctx = ctx;
    this.musicIn = ctx.createGain();
    this.volume = ctx.createGain();
    this.fxIn = ctx.createGain();
    this.roomIn = ctx.createGain();
    this.roomOut = ctx.createGain();
    this.host = ctx.createGain();
    this.limiter = ctx.createDynamicsCompressor();
    this.limiter.threshold.value = -3;
    this.limiter.ratio.value = 20;
    this.limiter.attack.value = 0.002;
    this.limiter.release.value = 0.1;
    this.dspIn = ctx.createGain();
    this.dspOut = ctx.createGain();
    this.musicIn.connect(this.dspIn);
    this.dspIn.connect(this.dspOut);           // until the first config arrives
    this.dspOut.connect(this.volume).connect(this.roomIn);
    this.fxIn.connect(this.roomIn);
    this.roomIn.connect(this.roomOut);
    this.roomOut.connect(this.host).connect(this.limiter).connect(ctx.destination);
    this.host.gain.value = dbToGain(this.state.hostDb);
    const worklet = `class R extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor('aroio-rec',R)`;
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([worklet], { type: 'text/javascript' })));
    this.noise = pinkNoise(ctx, 4);
    this.state.enabled = true;
    this.emit();
  }

  async disable() {
    this.stopMusic();
    if (this.ctx) await this.ctx.suspend();
    this.state.enabled = false;
    this.emit();
  }

  emit() { this.onState({ ...this.state }); }

  setHostDb(db) {
    this.state.hostDb = db;
    if (this.ctx) this.host.gain.setTargetAtTime(dbToGain(db), this.ctx.currentTime, 0.05);
    this.emit();
  }

  // ── state from aroiod ──
  update(sim, player, now) {
    if (!this.ctx || !this.state.enabled || !sim) return;
    this.applyCamilla(sim.camilla_config);
    this.applyRoom(sim.room);
    const db = sim.fixed_level ? 0 : sim.volume_db;
    this.volume.gain.setTargetAtTime(db == null ? 0 : dbToGain(db), this.ctx.currentTime, 0.03);
    this.applyPlayer(player, now);
    const req = sim.request;
    if (req && !this.handled.has(req.id)) {
      this.handled.add(req.id);
      if (Date.now() / 1000 - req.at < 10) this.handle(req, sim).catch((e) => console.error(e));
    }
  }

  // ── CamillaDSP clone ──
  applyCamilla(cfg) {
    const key = JSON.stringify(cfg);
    if (!cfg || key === this.cfgKey) return;
    this.cfgKey = key;
    const ctx = this.ctx;
    this.dspIn.disconnect();
    const split = ctx.createChannelSplitter(2);
    const merge = ctx.createChannelMerger(2);
    this.dspIn.connect(split);
    let cur = [mono(ctx.createGain()), mono(ctx.createGain())];
    split.connect(cur[0], 0);
    split.connect(cur[1], 1);
    for (const step of cfg.pipeline) {
      if (step.type === 'Filter') {
        for (const ch of step.channels) {
          for (const name of step.names) {
            const node = this.filterNode(cfg.filters[name], cfg.devices.samplerate);
            cur[ch].connect(node.in);
            cur[ch] = node.out;
          }
        }
      } else if (step.type === 'Mixer') {
        const mixer = cfg.mixers[step.name];
        const next = [mono(ctx.createGain()), mono(ctx.createGain())];
        for (const m of mixer.mapping) {
          for (const src of m.sources) {
            const g = mono(ctx.createGain());
            g.gain.value = dbToGain(src.gain) * (src.inverted ? -1 : 1);
            cur[src.channel].connect(g).connect(next[m.dest]);
          }
        }
        cur = next;
      }
    }
    cur[0].connect(merge, 0, 0);
    cur[1].connect(merge, 0, 1);
    this.dspOut.disconnect();
    this.dspOut = merge;
    merge.connect(this.volume);
  }

  filterNode(f, rate) {
    const ctx = this.ctx;
    const p = f.parameters;
    if (f.type === 'Gain') {
      const g = mono(ctx.createGain());
      g.gain.value = dbToGain(p.gain) * (p.inverted ? -1 : 1);
      return { in: g, out: g };
    }
    if (f.type === 'Delay') {
      const d = mono(ctx.createDelay(1));
      d.delayTime.value = p.unit === 'ms' ? p.delay / 1000 : p.delay / rate;
      return { in: d, out: d };
    }
    if (f.type === 'Biquad') {
      const b = mono(ctx.createBiquadFilter());
      b.type = { Peaking: 'peaking', Lowshelf: 'lowshelf', Highshelf: 'highshelf', Lowpass: 'lowpass', Highpass: 'highpass' }[p.type];
      b.frequency.value = p.freq;
      if (p.gain != null) b.gain.value = p.gain;
      // Web Audio: Q of low/highpass is resonance in dB, peaking Q is the RBJ Q
      b.Q.value = b.type === 'lowpass' || b.type === 'highpass' ? 20 * Math.log10(p.q) : p.q;
      return { in: b, out: b };
    }
    if (f.type === 'Conv') {
      const c = mono(ctx.createConvolver());
      c.normalize = false;
      const name = p.filename.split('/').pop();
      fetch('/api/v1/sim/fir/' + encodeURIComponent(name)).then((r) => r.arrayBuffer()).then((buf) => {
        const taps = new Float64Array(buf);
        const ab = ctx.createBuffer(1, taps.length, rate);
        ab.getChannelData(0).set(Float32Array.from(taps));
        c.buffer = ab;
      }).catch(() => {});
      return { in: c, out: c };
    }
    const g = mono(ctx.createGain());
    return { in: g, out: g };
  }

  // ── virtual room (the simulator's room modes, position 1) ──
  applyRoom(room) {
    const key = JSON.stringify([room, this.state.roomOn]);
    if (!room || key === this.roomKey) return;
    this.roomKey = key;
    this.roomIn.disconnect();
    if (!this.state.roomOn) { this.roomIn.connect(this.roomOut); return; }
    const ctx = this.ctx;
    let node = ctx.createBiquadFilter();
    node.type = 'highpass';
    node.frequency.value = room.highpass;
    node.Q.value = -3.01;
    this.roomIn.connect(node);
    for (const [freq, gain, q] of room.modes) {
      const b = ctx.createBiquadFilter();
      b.type = 'peaking';
      b.frequency.value = freq;
      b.gain.value = gain;
      b.Q.value = q;
      node.connect(b);
      node = b;
    }
    node.connect(this.roomOut);
  }

  setRoom(on) {
    this.state.roomOn = on;
    this.roomKey = '';
    this.emit();
  }

  // ── music ──
  applyPlayer(p, now) {
    const playing = p?.state === 'playing' && p.track;
    const key = playing ? `${p.source}|${p.track.id}` : '';
    let pos = 0;
    if (playing) {
      pos = p.position + Math.max(0, now - p.position_at);
    }
    if (!playing) { this.stopMusic(); return; }
    if (key !== this.trackKey || !this.synth || Math.abs(this.synth.position() - pos) > 2) {
      this.stopMusic();
      this.trackKey = key;
      this.synth = new Synth(this.ctx, this.musicIn, this.noise, p.track.id || key);
      this.synth.start(pos);
      this.state.playing = true;
      this.emit();
    }
  }

  stopMusic() {
    if (this.synth) this.synth.stop();
    this.synth = null;
    this.trackKey = '';
    if (this.state.playing) { this.state.playing = false; this.emit(); }
  }

  stopSignal() {
    const t = this.testSignal;
    this.testSignal = null;
    if (!t) return;
    const now = this.ctx.currentTime;
    t.g.gain.cancelScheduledValues(now);
    t.g.gain.setTargetAtTime(0, now, 0.01);
    try { t.src.stop(now + 0.1); } catch { /* already stopped */ }
  }

  // ── requests from aroiod: tones, noise, sweeps, real measurements ──
  async handle(req, sim) {
    const ctx = this.ctx;
    if (req.kind === 'tone') {
      const osc = ctx.createOscillator();
      osc.frequency.value = 440;
      const g = ctx.createGain();
      envelope(g.gain, ctx.currentTime, req.seconds, 0.25);
      osc.connect(g);
      route(ctx, g, req.channel, this.fxIn);
      osc.start();
      osc.stop(ctx.currentTime + req.seconds + 0.1);
    } else if (req.kind === 'signal') {
      // speaker check: 440 Hz or pink noise (looped) for the chosen time, like on the device
      this.stopSignal();
      const src = req.signal_kind === 'tone' ? ctx.createOscillator() : ctx.createBufferSource();
      if (req.signal_kind === 'tone') src.frequency.value = 440;
      else { src.buffer = this.noise; src.loop = true; }
      const g = ctx.createGain();
      envelope(g.gain, ctx.currentTime, req.seconds, req.signal_kind === 'tone' ? 0.25 : dbToGain(-15));
      src.connect(g);
      route(ctx, g, req.channel, this.fxIn);
      src.start();
      src.stop(ctx.currentTime + req.seconds + 0.1);
      this.testSignal = { src, g };
    } else if (req.kind === 'signal_stop') {
      this.stopSignal();
    } else if (req.kind === 'noise') {
      const src = ctx.createBufferSource();
      src.buffer = this.noise;
      const g = ctx.createGain();
      const t = ctx.currentTime;
      g.gain.setValueAtTime(dbToGain(-40), t);
      g.gain.exponentialRampToValueAtTime(dbToGain(-18), t + req.seconds);
      g.gain.setTargetAtTime(0, t + req.seconds, 0.05);
      src.connect(g).connect(this.fxIn);
      src.start();
      src.stop(t + req.seconds + 0.3);
    } else if (req.kind === 'play') {
      const buf = await this.signal(req.id);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      route(ctx, src, req.channel, this.fxIn);
      src.start();
    } else if (req.kind === 'level') {
      await this.report(req.id, () => this.levelCheck(req));
    } else if (req.kind === 'measure') {
      await this.report(req.id, () => this.record(req), true);
    }
  }

  async signal(id) {
    const r = await fetch('/api/v1/sim/signal/' + id);
    const f = new Float32Array(await r.arrayBuffer());
    const buf = this.ctx.createBuffer(1, f.length, RATE);
    buf.getChannelData(0).set(f);
    return buf;
  }

  async report(id, fn, binary = false) {
    let body, type;
    try {
      const res = await fn();
      body = binary ? res : JSON.stringify(res);
      type = binary ? 'application/octet-stream' : 'application/json';
    } catch (e) {
      body = JSON.stringify({ error: e.message || String(e) });
      type = 'application/json';
    }
    await fetch('/api/v1/sim/result/' + id, { method: 'POST', headers: { 'Content-Type': type }, body });
  }

  // ── real microphone on the host ──
  async useMic(deviceId) {
    this.releaseMic();
    this.micStream = await navigator.mediaDevices.getUserMedia({ audio: {
      deviceId: deviceId ? { exact: deviceId } : undefined, channelCount: 1,
      echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    if (this.ctx) {
      this.micSource = this.ctx.createMediaStreamSource(this.micStream);
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 4096;
      this.micSource.connect(this.analyser);
    }
    return this.micStream.getAudioTracks()[0]?.label || 'Mikrofon';
  }

  releaseMic() {
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micStream = null;
    this.micSource = null;
    this.analyser = null;
  }

  micLevel() {
    if (!this.analyser) return null;
    const d = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(d);
    return rmsDb(d);
  }

  measurePath(gainDb) {
    // measurement signals skip DSP, volume and the virtual room: the real room is measured
    const g = this.ctx.createGain();
    g.gain.value = dbToGain(gainDb);
    g.connect(this.host);
    return g;
  }

  async levelCheck() {
    if (!this.micSource) throw new Error('Kein Mikrofon freigegeben.');
    this.state.busy = 'Pegel';
    this.emit();
    const ctx = this.ctx;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    const path = this.measurePath(-50);
    src.connect(path);
    src.start();
    let gain = -50, level = -120;
    try {
      while (gain < -6) {
        await sleep(300);
        level = this.micLevel();
        if (level > -30) break;
        gain += 3;
        path.gain.setTargetAtTime(dbToGain(gain), ctx.currentTime, 0.05);
      }
      await sleep(400);
      level = this.micLevel();
    } finally {
      path.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
      src.stop(ctx.currentTime + 0.3);
      this.state.busy = null;
      this.emit();
    }
    // the sweep (−12 dBFS peak) needs a bit less than the noise level
    return { rms_dbfs: Math.round(level * 10) / 10, gain_db: gain };
  }

  async record(req) {
    if (!this.micSource) throw new Error('Kein Mikrofon freigegeben.');
    this.state.busy = 'Messung';
    this.emit();
    const ctx = this.ctx;
    const chunks = [];
    const rec = new AudioWorkletNode(ctx, 'aroio-rec');
    rec.port.onmessage = (e) => chunks.push(e.data);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    this.micSource.connect(rec).connect(sink).connect(ctx.destination);
    try {
      await sleep(300);
      const src = ctx.createBufferSource();
      src.buffer = await this.signal(req.id);
      route(ctx, src, req.channel, this.measurePath(req.gain_db + 6));
      src.start();
      await sleep(req.record_seconds * 1000);
    } finally {
      this.micSource.disconnect(rec);
      rec.disconnect();
      this.state.busy = null;
      this.emit();
    }
    let out = concat(chunks);
    if (ctx.sampleRate !== RATE) out = await resample(out, ctx.sampleRate, RATE);
    return out.buffer;
  }
}

// ── music synthesiser: a few bars of bass, kick, pad, hats and arpeggio per track ──
class Synth {
  constructor(ctx, out, noise, seed) {
    this.ctx = ctx;
    this.noise = noise;
    const rnd = rng(hash(String(seed)));
    this.bpm = 72 + Math.floor(rnd() * 40);
    this.stepDur = 60 / this.bpm / 4;
    this.root = 33 + Math.floor(rnd() * 10);
    const minor = rnd() < 0.5;
    this.scale = minor ? [0, 2, 3, 5, 7, 8, 10] : [0, 2, 4, 5, 7, 9, 11];
    this.prog = [[0, 5, 3, 4], [0, 3, 4, 0], [0, 5, 2, 4], [5, 3, 0, 4], [0, 4, 5, 3]][Math.floor(rnd() * 5)];
    this.kickExtra = rnd() < 0.5 ? 6 : 10;
    this.out = ctx.createGain();
    this.out.gain.value = 0.55;
    this.out.connect(out);
  }

  note(degree, octave) {
    const n = this.scale.length;
    const d = ((degree % n) + n) % n;
    return this.root + 12 * (octave + Math.floor(degree / n)) + this.scale[d];
  }

  position() { return this.startPos + (this.ctx.currentTime - this.startTime); }

  start(pos) {
    this.startPos = pos;
    this.startTime = this.ctx.currentTime + 0.05;
    this.step = Math.floor(pos / this.stepDur);
    this.next = this.startTime + (this.step + 1) * this.stepDur - pos;
    this.step += 1;
    this.timer = setInterval(() => this.schedule(), 25);
    this.schedule();
  }

  stop() {
    clearInterval(this.timer);
    const t = this.ctx.currentTime;
    this.out.gain.setTargetAtTime(0, t, 0.05);
    setTimeout(() => this.out.disconnect(), 400);
  }

  schedule() {
    while (this.next < this.ctx.currentTime + 0.15) {
      this.play(this.step, this.next);
      this.step++;
      this.next += this.stepDur;
    }
  }

  play(step, t) {
    const s = step % 16;
    const chord = this.prog[Math.floor(step / 16) % this.prog.length];
    const tones = [chord, chord + 2, chord + 4];
    if (s === 0 || s === 8 || s === this.kickExtra) this.kick(t);
    if (s % 4 === 2) this.hat(t, 0.12);
    else if (s % 2 === 1) this.hat(t, 0.04);
    if ([0, 3, 6, 8, 11, 14].includes(s)) this.bass(midi(this.note(chord, 0)), t, this.stepDur * 2.5);
    if (s === 0) for (const [i, d] of tones.entries()) this.pad(midi(this.note(d, 2)), t, this.stepDur * 16, i - 1);
    if (s % 2 === 0) this.arp(midi(this.note(tones[(s / 2) % 3] + (s >= 8 ? 7 : 0), 3)), t, s % 4 === 0 ? -0.4 : 0.4);
  }

  kick(t) {
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.frequency.setValueAtTime(110, t);
    o.frequency.exponentialRampToValueAtTime(42, t + 0.12);
    g.gain.setValueAtTime(0.9, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
    o.connect(g).connect(this.out);
    o.start(t);
    o.stop(t + 0.45);
  }

  hat(t, level) {
    const src = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    src.buffer = this.noise;
    f.type = 'highpass';
    f.frequency.value = 7000;
    g.gain.setValueAtTime(level, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
    src.connect(f).connect(g).connect(this.out);
    src.start(t, Math.random() * 3);
    src.stop(t + 0.08);
  }

  bass(freq, t, dur) {
    const o = this.ctx.createOscillator(), sub = this.ctx.createOscillator(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    o.type = 'triangle';
    o.frequency.value = freq;
    sub.frequency.value = freq;
    f.type = 'lowpass';
    f.frequency.value = 320;
    envelope(g.gain, t, dur, 0.35, 0.01);
    o.connect(f);
    sub.connect(f);
    f.connect(g).connect(this.out);
    for (const x of [o, sub]) { x.start(t); x.stop(t + dur + 0.1); }
  }

  pad(freq, t, dur, pan) {
    const o = this.ctx.createOscillator(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain(), p = this.ctx.createStereoPanner();
    o.type = 'sawtooth';
    o.frequency.value = freq;
    o.detune.value = pan * 6;
    f.type = 'lowpass';
    f.frequency.value = 1400;
    p.pan.value = pan * 0.5;
    envelope(g.gain, t, dur, 0.05, 0.4);
    o.connect(f).connect(g).connect(p).connect(this.out);
    o.start(t);
    o.stop(t + dur + 0.5);
  }

  arp(freq, t, pan) {
    const o = this.ctx.createOscillator(), g = this.ctx.createGain(), p = this.ctx.createStereoPanner();
    o.type = 'triangle';
    o.frequency.value = freq;
    p.pan.value = pan;
    g.gain.setValueAtTime(0.06, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
    o.connect(g).connect(p).connect(this.out);
    o.start(t);
    o.stop(t + 0.3);
  }
}

// ── helpers ──
const dbToGain = (db) => Math.pow(10, db / 20);
const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function mono(node) {
  node.channelCount = 1;
  node.channelCountMode = 'explicit';
  return node;
}

function route(ctx, node, channel, dest) {
  const merge = ctx.createChannelMerger(2);
  if (channel !== 'R') node.connect(merge, 0, 0);
  if (channel !== 'L') node.connect(merge, 0, 1);
  merge.connect(dest);
}

function envelope(param, t, dur, peak, attack = 0.02) {
  param.setValueAtTime(0.0001, t);
  param.exponentialRampToValueAtTime(peak, t + attack);
  param.setValueAtTime(peak, t + Math.max(attack, dur - 0.1));
  param.exponentialRampToValueAtTime(0.0001, t + dur);
}

function pinkNoise(ctx, seconds) {
  const buf = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate);
  const d = buf.getChannelData(0);
  let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
  for (let i = 0; i < d.length; i++) {           // Paul Kellet's pink noise filter
    const w = Math.random() * 2 - 1;
    b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759; b2 = 0.969 * b2 + w * 0.153852;
    b3 = 0.8665 * b3 + w * 0.3104856; b4 = 0.55 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.016898;
    d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
    b6 = w * 0.115926;
  }
  return buf;
}

function rmsDb(d) {
  let s = 0;
  for (const x of d) s += x * x;
  return 10 * Math.log10(Math.max(s / d.length, 1e-12));
}

function concat(chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

async function resample(data, from, to) {
  const off = new OfflineAudioContext(1, Math.ceil(data.length * to / from), to);
  const buf = off.createBuffer(1, data.length, from);
  buf.getChannelData(0).set(data);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
