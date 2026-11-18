export function time(sec) {
  if (sec == null || !isFinite(sec)) return '–:––';
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + ':' + String(s).padStart(2, '0');
}

// "3 Minuten 5 Sekunden" for screen readers
export function timeSpoken(sec, t) {
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return t('{m} Minuten {s} Sekunden', { m, s });
}

export function rate(hz) {
  if (!hz) return '';
  if (hz > 1000000) return `DSD${Math.round(hz / 44100)}`;
  return `${(hz / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1 })} kHz`;
}

export function quality(fmt) {
  if (!fmt) return '';
  const { codec, bits, rate: r } = fmt;
  if (codec === 'DSD') return `DSD${Math.round(r / 44100)}`;
  if (!codec) return rate(r);
  if (!bits) return `${codec} · ${rate(r)}`;
  return `${codec} · ${bits} Bit · ${rate(r)}`;
}

export function hz(f) {
  return f >= 1000 ? `${(f / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1 })} kHz` : `${Math.round(f)} Hz`;
}

export function db(v, digits = 1) {
  if (v == null) return '';
  const s = v.toLocaleString('de-DE', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return (v > 0 ? '+' : '') + s + ' dB';
}
