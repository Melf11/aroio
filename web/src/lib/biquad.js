// Same maths as aroiod/dsp.py (RBJ Audio EQ Cookbook), for instant previews in the browser.

export const TYPES = ['peaking', 'lowshelf', 'highshelf', 'lowpass', 'highpass'];
export const hasGain = (type) => type === 'peaking' || type === 'lowshelf' || type === 'highshelf';

function coeffs(f, rate) {
  const w0 = (2 * Math.PI * f.freq) / rate, cw = Math.cos(w0), sw = Math.sin(w0);
  const alpha = sw / (2 * f.q), A = Math.pow(10, (f.gain || 0) / 40), sq = 2 * Math.sqrt(A) * alpha;
  switch (f.type) {
    case 'peaking': return [[1 + alpha * A, -2 * cw, 1 - alpha * A], [1 + alpha / A, -2 * cw, 1 - alpha / A]];
    case 'lowshelf': return [[A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)],
      [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]];
    case 'highshelf': return [[A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)],
      [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]];
    case 'lowpass': return [[(1 - cw) / 2, 1 - cw, (1 - cw) / 2], [1 + alpha, -2 * cw, 1 - alpha]];
    case 'highpass': return [[(1 + cw) / 2, -(1 + cw), (1 + cw) / 2], [1 + alpha, -2 * cw, 1 - alpha]];
  }
  return [[1, 0, 0], [1, 0, 0]];
}

// dB response of a filter chain at the given frequencies
export function response(filters, freqs, rate = 48000) {
  const out = new Array(freqs.length).fill(0);
  for (const f of filters) {
    const [b, a] = coeffs(f, rate);
    freqs.forEach((fr, i) => {
      const w = (2 * Math.PI * fr) / rate;
      const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
      const nr = b[0] + b[1] * c1 + b[2] * c2, ni = -(b[1] * s1 + b[2] * s2);
      const dr = a[0] + a[1] * c1 + a[2] * c2, di = -(a[1] * s1 + a[2] * s2);
      out[i] += 10 * Math.log10(Math.max((nr * nr + ni * ni) / (dr * dr + di * di), 1e-24));
    });
  }
  return out;
}

export const logFreqs = (n = 160, lo = 20, hi = 20000) => Array.from({ length: n }, (_, i) => lo * Math.pow(hi / lo, i / (n - 1)));
