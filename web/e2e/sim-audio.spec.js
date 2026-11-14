import { test, expect } from '@playwright/test';

// Simulator page with sound and a (fake) microphone on the host.
test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } });

// A fake "miniDSP UMIK-1" (noise generator), independent of the OS microphone permission.
const FAKE_UMIK = () => {
  const device = { deviceId: 'umik', kind: 'audioinput', label: 'miniDSP UMIK-1 (Test)', groupId: 'g' };
  navigator.mediaDevices.enumerateDevices = async () => [device];
  navigator.mediaDevices.getUserMedia = async () => {
    const ctx = new AudioContext({ sampleRate: 48000 });
    const buf = ctx.createBuffer(1, 48000, 48000);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.05;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const dest = ctx.createMediaStreamDestination();
    src.connect(dest);
    src.start();
    return dest.stream;
  };
  if (navigator.permissions) navigator.permissions.query = async () => ({ state: 'granted' });
};

const api = (request, path, data, method = 'post') => request[method]('/api/v1' + path, { data });
const state = async (request) => (await api(request, '/state', undefined, 'get')).json();

test('Simulator: Ton am Rechner und Messung mit Mikrofon am Rechner', async ({ page, request }, info) => {
  test.skip(info.project.name !== 'desktop', 'einmal reicht');
  test.setTimeout(90000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|404/.test(m.text())) errors.push(m.text()); });

  await api(request, '/system/factory-reset', { confirm: 'zuruecksetzen' });
  await api(request, '/config', { setup: { completed: true } }, 'patch');
  await page.addInitScript(FAKE_UMIK);
  await page.setViewportSize({ width: 1500, height: 950 });
  await page.goto('/sim');
  await page.getByRole('button', { name: 'Ton einschalten' }).click();
  await expect(page.getByRole('button', { name: /Ton ist an/ })).toBeVisible();

  // music through a DSP preset with Cleaner
  await api(request, '/config', { dsp: { ms_cleaner: true } }, 'patch');
  await api(request, '/queue', { id: 'local:album:2' });
  await expect.poll(() => page.evaluate(() => document.querySelector('.sim') !== null)).toBe(true);
  await page.waitForTimeout(1500);

  // the UMIK on the host is picked up automatically once sound is on
  await expect.poll(async () => (await state(request)).sim.mic_mode).toBe('host');
  expect((await state(request)).sim.host_mic).toContain('UMIK-1');
  const rc = (a, d) => api(request, '/roomcorr/' + a, d);
  await rc('start'); await rc('next');
  expect((await state(request)).roomcorr.mic.connected).toBe(true);
  await rc('next'); await rc('next');
  expect((await rc('level')).ok()).toBe(true);
  const level = (await state(request)).roomcorr.level;
  expect(level.unit).toBe('dBFS');
  await rc('next');
  await rc('set_positions', { count: 1 });
  const r = await rc('measure');
  const after = (await state(request)).roomcorr;
  // the fake microphone only hears noise, not our sweep: the wizard must either accept the
  // recording or report a problem, but the round trip page <-> aroiod must work
  expect(r.ok() || after.issue).toBeTruthy();
  expect(after.measured.length === 2 || !!after.issue).toBe(true);
  expect(errors).toEqual([]);
});
