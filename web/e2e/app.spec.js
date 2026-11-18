import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import AxeBuilder from '@axe-core/playwright';

const api = (request, path, data, method = 'post') => request[method]('/api/v1' + path, { data });

async function fresh(request, { setup = true } = {}) {
  await api(request, '/system/factory-reset', { confirm: 'zuruecksetzen' });
  await api(request, '/sim/lan', { on: true });
  if (setup) await api(request, '/config', { setup: { completed: true } }, 'patch');
}

async function axe(page, name) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const v = r.violations.map((x) => `${x.id} (${x.impact}): ${x.help}\n    ${x.nodes.slice(0, 3).map((n) => n.target.join(' ')).join('\n    ')}`);
  expect(v, `${name}: axe violations`).toEqual([]);
}

const ROUTES = ['/', '/musik', '/musik/b?path=local/albums', '/musik/b?path=local/album/3', '/musik/suche?q=licht', '/warteschlange',
  '/klang', '/einstellungen', '/einstellungen/allgemein', '/einstellungen/netzwerk', '/einstellungen/dienste',
  '/einstellungen/dienste/spotify', '/einstellungen/dienste/tidal', '/einstellungen/dienste/qobuz', '/einstellungen/dienste/lyrion',
  '/einstellungen/bluetooth', '/einstellungen/updates', '/einstellungen/geraet', '/einstellungen/lautsprecher', '/einstellungen/lizenzen',
  '/klang/preset/werk-bbcdip', '/klang/kopfhoerer'];
const EXPERT = ['/einstellungen/ton', '/einstellungen/hardware', '/einstellungen/system', '/klang/import'];

test('alle Seiten ohne Barrierefreiheits-Verstöße (hell und dunkel)', async ({ page, request }, info) => {
  await fresh(request);
  await api(request, '/queue', { id: 'local:album:3' });
  await api(request, '/config', { device: { expert_mode: true } }, 'patch');
  for (const scheme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const r of [...ROUTES, ...EXPERT]) {
      await page.goto(r);
      await expect(page.locator('main h1').first()).toBeVisible();
      await page.waitForTimeout(150);
      await axe(page, `${r} (${scheme})`);
      if (scheme === 'light' || r === '/') {
        await page.screenshot({ path: `test-results/shots/${info.project.name}-${scheme}${r.replace(/[/?=&]+/g, '_')}.png`, fullPage: true });
      }
    }
  }
});

test('kein horizontales Scrollen', async ({ page, request }) => {
  await fresh(request);
  await api(request, '/queue', { id: 'local:album:5' });
  for (const r of ROUTES) {
    await page.goto(r);
    await page.waitForTimeout(100);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over, r).toBeLessThanOrEqual(0);
  }
});

test('Einrichtung beim ersten Start', async ({ page, request }) => {
  await fresh(request, { setup: false });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Willkommen beim Aroio' })).toBeVisible();
  await axe(page, 'setup');
  await page.getByRole('button', { name: 'Los geht’s' }).click();
  await page.getByLabel('Name', { exact: true }).fill('Küche');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByText('per Kabel verbunden')).toBeVisible();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('switch', { name: /^NetJack/ })).toBeVisible();
  await axe(page, 'setup-services');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('heading', { name: 'Welches Gerät hast du?' })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Aroio LT' })).toBeChecked();          // the simulator is an Aroio LT
  await axe(page, 'setup-device');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('heading', { name: 'Welche Soundkarte steckt im Aroio?' })).toBeVisible();
  await expect(page.getByRole('radio', { name: /^Aroio DAC/ })).toBeChecked();         // preselected for an Aroio
  await axe(page, 'setup-dac');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('heading', { name: 'Fast fertig' })).toBeVisible();      // driver changed: reboot
  await axe(page, 'setup-end');
  await page.getByRole('button', { name: 'Neu starten und fertig' }).click();
  await expect(page.getByText('Der Aroio ist wieder da.')).toBeVisible({ timeout: 20000 });
  const s = await (await api(request, '/state', undefined, 'get')).json();
  expect(s.device.model).toBe('AroioLT');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Küche' })).toBeVisible();
});

test('Album abspielen, Lautstärke, Warteschlange', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/musik/b?path=local/album/2');
  await page.getByRole('button', { name: 'Abspielen', exact: true }).click();
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Pause' }).first()).toBeVisible();
  const slider = page.getByRole('slider', { name: 'Lautstärke' });
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).player.volume).toBe(31);
  await api(request, '/sim/external_start', { source: 'airplay' });
  await expect(page.getByText('AirPlay', { exact: false }).first()).toBeVisible();
});

test('Lautstärke im Miniplayer', async ({ page, request }, info) => {
  await fresh(request);
  await page.goto('/musik/b?path=local/album/2');
  await page.getByRole('button', { name: 'Abspielen', exact: true }).click();
  const mini = page.getByRole('region', { name: 'Wiedergabe' });
  await expect(mini).toBeVisible();
  if (info.project.name === 'mobil') {
    const btn = mini.getByRole('button', { name: /^Lautstärke: \d+ Prozent$/ });
    await btn.click();
    await expect(btn).toHaveAttribute('aria-expanded', 'true');
    await axe(page, 'mini-volume');
    await page.getByRole('button', { name: 'Lauter' }).click();
    await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).player.volume).toBe(35);
    await page.keyboard.press('Escape');
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
    await expect(btn).toBeFocused();
  } else {
    const slider = mini.getByRole('slider', { name: 'Lautstärke' });
    await slider.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).player.volume).toBe(31);
    await axe(page, 'mini-volume');
  }
});

test('Mono-Schalter unter Klang', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/klang');
  const mono = page.getByRole('switch', { name: 'Mono' });
  await mono.click();
  await expect(mono).toBeChecked();
  await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).dsp.mono).toBe(true);
  await axe(page, 'mono');
  await mono.click();
  await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).dsp.mono).toBe(false);
});

test('Raumkorrektur Schritt für Schritt', async ({ page, request }) => {
  test.setTimeout(180000);
  await fresh(request);
  await page.goto('/klang/raumkorrektur');
  await page.getByRole('button', { name: 'Los geht’s' }).click();
  await expect(page.getByRole('heading', { name: 'Mikrofon anschließen' })).toBeVisible();
  await axe(page, 'rc-mic');
  await api(request, '/sim/mic', { on: true });
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('button', { name: 'Mikrofon steht' }).click();
  await page.getByRole('button', { name: 'Lautstärke prüfen' }).click();
  await page.getByRole('button', { name: 'Weiter' }).click({ timeout: 15000 });
  const measured = async () => (await (await api(request, '/state', undefined, 'get')).json()).roomcorr.measured.length;
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: /^Messen$/ }).click();
    await expect.poll(measured, { timeout: 30000 }).toBe((i + 1) * 2);
  }
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('radio', { name: 'Warm' }).check();
  await page.getByRole('button', { name: 'Korrektur berechnen' }).click();
  await expect(page.getByRole('heading', { name: 'Ergebnis' })).toBeVisible({ timeout: 30000 });
  await axe(page, 'rc-result');
  // adjust a filter by hand: the preview on the device follows
  await page.getByText('Filter von Hand anpassen').click();
  await page.getByText(/^Glocke \(Peak\)/).first().click();
  await page.getByRole('spinbutton', { name: 'Pegel' }).first().fill('-2');
  await page.getByRole('spinbutton', { name: 'Pegel' }).first().blur();
  await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).roomcorr.result.channels.L.manual).toBe(true);
  await axe(page, 'rc-manual');
  await page.getByLabel('Name für diese Einstellung').fill('Testraum');
  await page.getByRole('button', { name: 'Speichern und verwenden' }).click();
  await expect(page.getByRole('heading', { name: /Fertig/ })).toBeVisible();
});

test('Altgerät übernehmen', async ({ page, request }) => {
  await fresh(request, { setup: false });
  await api(request, '/sim/old_device');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Einstellungen vom alten Aroio übernehmen' })).toBeVisible();
  await axe(page, 'migration');
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Fast fertig' })).toBeVisible();
  await page.getByRole('button', { name: 'Fertig' }).click();
  await expect(page.getByRole('heading', { name: 'Aroio Wohnzimmer' })).toBeVisible();
});


test('Klangeinstellung von Hand bearbeiten', async ({ page, request }) => {
  await fresh(request);
  const peq = { L: [{ type: 'peaking', freq: 60, gain: -6, q: 2 }], R: [{ type: 'peaking', freq: 60, gain: -6, q: 2 }] };
  const cfg = await (await api(request, '/config', undefined, 'get')).json();
  await api(request, '/config', { dsp: { presets: [...cfg.dsp.presets, { id: 'eq1', name: 'Mein EQ', kind: 'peq', peq }], active_preset: 'eq1' } }, 'patch');
  await page.goto('/klang/preset/eq1');
  await page.getByRole('button', { name: 'Filter bearbeiten' }).click();
  await expect(page.getByRole('button', { name: 'Links und rechts gleich' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Filter hinzufügen' }).click();
  await page.getByRole('spinbutton', { name: 'Frequenz' }).last().fill('220');
  await page.getByRole('spinbutton', { name: 'Frequenz' }).last().blur();
  const preset = async () => (await (await api(request, '/dsp/presets/eq1', undefined, 'get')).json());
  await expect.poll(async () => (await preset()).peq.R.map((f) => f.freq)).toEqual([60, 220]);
  await axe(page, 'peq-editor');
  await page.getByRole('button', { name: 'Rückgängig' }).click();
  await expect.poll(async () => (await preset()).peq.L.length).toBe(1);
  await page.getByRole('button', { name: 'Fertig' }).click();
  await expect(page.getByRole('button', { name: 'Filter bearbeiten' })).toBeVisible();
});

test('Eigener Equalizer ohne Messmikrofon', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/klang');
  await page.getByRole('button', { name: 'Equalizer anlegen' }).click();
  await expect(page.getByRole('heading', { name: 'Eigener Equalizer', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Filter bearbeiten' })).toBeVisible();   // editor opens directly
  await expect(page.getByText('Diese Einstellung ist gerade aktiv.')).toBeVisible();
  await page.locator('summary', { hasText: 'Bass-Shelf' }).click();
  await page.getByRole('spinbutton', { name: 'Pegel' }).first().fill('3');
  await page.getByRole('spinbutton', { name: 'Pegel' }).first().blur();
  const id = new URL(page.url()).pathname.split('/').pop();
  await expect.poll(async () => (await (await api(request, '/dsp/presets/' + id, undefined, 'get')).json()).peq.R[0].gain).toBe(3);
  await axe(page, 'eigener-equalizer');
  // in the chart: drag filter 2 (mids) to the right and up; keyboard on filter 3
  const preset = async () => (await (await api(request, '/dsp/presets/' + id, undefined, 'get')).json());
  const h2 = page.getByRole('button', { name: /^Filter 2:/ });
  const box = await h2.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 - 30, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => { const f = (await preset()).peq.L[1]; return f.freq > 1000 && f.gain > 0; }).toBe(true);
  const h3 = page.getByRole('button', { name: /^Filter 3:/ });
  await h3.focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Control+ArrowUp');
  await expect.poll(async () => { const f = (await preset()).peq.R[2]; return [f.gain, f.q]; }).toEqual([-0.5, 0.77]);
  // double click into the free chart adds a filter there, double click on its point removes it
  const area = page.locator('rect.area');
  const a = await area.boundingBox();
  await area.dblclick({ position: { x: a.width * 0.3, y: a.height * 0.15 } });
  await expect.poll(async () => (await preset()).peq.L.length).toBe(4);
  const added = (await preset()).peq.L[3];
  expect(added.type).toBe('peaking');
  expect(added.gain).toBeGreaterThan(5);
  await page.getByRole('button', { name: /^Filter 4:/ }).dblclick();
  await expect.poll(async () => (await preset()).peq.L.length).toBe(3);
});

test('Spotify Connect: Soloist-Schlüssel in den Einstellungen', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen/dienste/spotify');
  await expect(page.getByText(/eigenen Soloist-Schlüssel/)).toBeVisible();
  await page.getByLabel('Soloist-Schlüssel').fill('kurz');
  await page.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByRole('alert')).toContainText('zu kurz');
  await page.getByLabel('Soloist-Schlüssel').fill('0123456789abcdef0123456789abcdef');
  await page.getByRole('button', { name: 'Speichern' }).click();
  await expect(page.getByText(/Bereit\. Öffne Spotify/)).toBeVisible();
  await page.waitForTimeout(400);       // toast fades in
  await axe(page, 'spotify-bereit');
  await page.getByRole('button', { name: 'Schlüssel entfernen' }).click();
  await expect(page.getByLabel('Soloist-Schlüssel')).toBeVisible();
});

test('WLAN-Einrichtung über den Hotspot (Captive Portal)', async ({ page, request }) => {
  test.setTimeout(90000);
  await fresh(request);
  await api(request, '/sim/first_boot', { lan: false });
  const net = async () => (await (await api(request, '/state', undefined, 'get')).json()).network;
  await expect.poll(async () => (await net()).hotspot.active, { timeout: 15000 }).toBe(true);

  // what the phone sees: any page while on the hotspot -> setup page
  const probe = await request.get('/hotspot-detect.html', { headers: { Host: 'captive.apple.com' }, maxRedirects: 0 });
  expect(probe.status()).toBe(302);

  await page.goto('/einrichtung');
  await expect(page.getByRole('heading', { name: 'Mit dem WLAN verbinden' })).toBeVisible();
  await axe(page, 'wifi-1');
  await page.getByRole('radio', { name: /^Zuhause (sehr gut|gut|mittel|schwach)/ }).check();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByLabel('WLAN-Passwort').fill('falsch-1234');
  await axe(page, 'wifi-2');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await axe(page, 'wifi-3');
  await page.getByRole('button', { name: 'Jetzt verbinden' }).click();
  await expect(page.getByRole('heading', { name: 'Der Aroio verbindet sich' })).toBeVisible();
  await axe(page, 'wifi-4');

  // wrong password: hotspot is back, the page explains why after reconnecting
  await expect.poll(async () => (await net()).setup.state, { timeout: 15000 }).toBe('failed');
  await expect.poll(async () => (await net()).hotspot.active, { timeout: 15000 }).toBe(true);
  await page.goto('/einrichtung');
  await expect(page.getByRole('alert')).toContainText('Passwort ist falsch');

  await page.getByRole('radio', { name: /^Zuhause (sehr gut|gut|mittel|schwach)/ }).check();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByLabel('WLAN-Passwort').fill('richtig-1234');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('button', { name: 'Jetzt verbinden' }).click();
  await expect.poll(async () => (await net()).setup.state, { timeout: 15000 }).toBe('connected');
  expect((await net()).hotspot.active).toBe(false);
});


test('Einrichtung: anderer DAC verlangt Neustart, Neustart mit Fortschritt', async ({ page, request }) => {
  await fresh(request, { setup: false });
  await page.goto('/');
  await page.getByRole('button', { name: 'Los geht’s' }).click();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await page.getByRole('radio', { name: /^Anderes Gerät/ }).check();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('radio', { name: /^Automatisch/ })).toBeChecked();      // other device: no Aroio DAC
  await page.getByRole('radio', { name: /^Raspberry Pi DAC\+ \/ DAC Pro/ }).check();
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('heading', { name: 'Fast fertig' })).toBeVisible();
  await page.getByRole('button', { name: 'Neu starten und fertig' }).click();
  await expect(page.getByRole('progressbar', { name: 'Fortschritt des Neustarts' })).toBeVisible();
  await page.waitForTimeout(400);       // toasts fade in (0.2 s); check the settled screen
  await axe(page, 'reboot');
  await expect(page.getByText('Der Aroio ist wieder da.')).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('progressbar')).toBeHidden({ timeout: 5000 });
  const s = await (await api(request, '/state', undefined, 'get')).json();
  expect(s.device.setup_completed).toBe(true);
  expect(s.device.reboot_required).toBe(false);
});


test('App-Passwort: Anmeldung, falsches Passwort, Abmelden des Schutzes', async ({ page, request }) => {
  await fresh(request);
  const toastText = (text) => page.locator('.toast', { hasText: text }).or(page.locator('span.grow', { hasText: text })).first();
  try {
    await page.goto('/einstellungen/allgemein');
    await page.getByLabel('Passwort', { exact: true }).fill('geheim1');
    await page.getByRole('button', { name: 'Passwort setzen' }).click();
    await expect(toastText('App-Passwort gesetzt.')).toBeVisible();
    // a new browser (no session cookie) sees the login
    await page.context().clearCookies();
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Anmelden' })).toBeVisible();
    await axe(page, 'Anmeldung');
    await page.getByLabel('Passwort').fill('falsch');
    await page.getByRole('button', { name: 'Anmelden' }).click();
    await expect(page.getByRole('alert')).toContainText('stimmt nicht');
    await page.getByLabel('Passwort').fill('geheim1');
    await page.getByRole('button', { name: 'Anmelden' }).click();
    await expect(page.locator('main h1').first()).toBeVisible();
    await page.goto('/einstellungen/allgemein');
    await page.getByRole('button', { name: 'Passwort entfernen' }).click();
    await expect(toastText('App-Passwort entfernt.')).toBeVisible();
  } finally {
    // never leave a password behind for the other tests
    await page.request.post('/api/v1/auth/login', { data: { password: 'geheim1' } });
    await page.request.post('/api/v1/security/password', { data: { password: null } });
  }
});

test('Fernbedienung: Taste anlernen und Stummschalten', async ({ page, request }) => {
  await fresh(request);
  await api(request, '/config', { device: { expert_mode: true } }, 'patch');
  await page.goto('/einstellungen/hardware');
  await page.getByRole('button', { name: 'Stumm anlernen' }).click();
  await expect(page.getByRole('button', { name: 'Warte auf Taste für „Stumm“ …' })).toBeVisible();
  await api(request, '/sim/ir', { code: '0x4711' });
  await expect(page.locator('.toast', { hasText: 'Taste gespeichert (0x4711).' })).toBeVisible();
  await api(request, '/sim/ir', { code: '0x4711' });
  await page.goto('/');
  await api(request, '/queue', { id: 'local:album:3' });
  await expect(page.getByRole('button', { name: 'Stumm' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Stumm' }).click();
  await expect(page.getByRole('button', { name: 'Stumm' })).toHaveAttribute('aria-pressed', 'false');
});

test('NetJack einschalten, Rate wählen, Rechner spielt', async ({ page, request }) => {
  await fresh(request);
  await api(request, '/config', { device: { expert_mode: true } }, 'patch');
  await page.goto('/einstellungen/dienste');
  const sw = page.getByRole('switch', { name: 'NetJack' });
  await expect(sw).not.toBeChecked();
  await sw.click();
  await expect(sw).toBeChecked();
  await page.getByLabel('NetJack-Abtastrate').selectOption('96000');
  await expect.poll(async () => (await (await api(request, '/state', undefined, 'get')).json()).services.netjack.rate).toBe(96000);
  await axe(page, 'Dienste mit NetJack');
  await api(request, '/sim/external_start', { source: 'netjack' });
  await page.goto('/');
  await expect(page.getByText('Studio-PC').first()).toBeVisible();
  // NetJack can only be ended on the Aroio: no skip buttons, Stopp instead of Pause
  const main = page.getByRole('region', { name: 'Läuft gerade' });
  await expect(main.getByRole('button', { name: 'Nächster Titel' })).toHaveCount(0);
  await expect(main.getByRole('button', { name: 'Pause' })).toHaveCount(0);
  await main.getByRole('button', { name: 'Stopp' }).click();
  await expect(page.getByText('Weiter geht es in der App auf dem Zuspieler.')).toBeVisible();
  await expect(main.getByRole('button', { name: 'Abspielen' })).toBeDisabled();   // only the sender starts it
  await axe(page, 'NetJack gestoppt');
});

test('Kopfhörer-Korrektur unter Klang (ohne Expertenmodus)', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/klang');
  await page.getByRole('link', { name: 'Kopfhörer wählen' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Kopfhörer-Korrektur' })).toBeVisible();
  await page.getByRole('radio', { name: 'Harman (älter)' }).check();
  await page.getByLabel('Kopfhörer suchen').fill('k701');
  await expect(page.getByText('1 Kopfhörer')).toBeVisible();
  await axe(page, 'headphones');
  await page.getByRole('button', { name: 'Anwenden: AKG K701' }).click();
  await expect(page.getByText('aktiv', { exact: true })).toBeVisible({ timeout: 15000 });
  const s = await (await api(request, '/state', undefined, 'get')).json();
  expect(s.dsp.presets.find((p) => p.id === s.dsp.active_preset).name).toBe('Kopfhörer: AKG K701');
});

// stereo WAV, 48 kHz, 16 bit: an impulse (like a file from the headphone project)
function stereoWav(frames = 2048) {
  const b = Buffer.alloc(44 + frames * 4);
  b.write('RIFF', 0); b.writeUInt32LE(36 + frames * 4, 4); b.write('WAVEfmt ', 8);
  b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(2, 22); b.writeUInt32LE(48000, 24);
  b.writeUInt32LE(48000 * 4, 28); b.writeUInt16LE(4, 32); b.writeUInt16LE(16, 34);
  b.write('data', 36); b.writeUInt32LE(frames * 4, 40);
  b.writeInt16LE(16000, 44); b.writeInt16LE(16000, 46);
  return b;
}

test('Stereo-WAV aus dem Kopfhörer-Projekt hochladen', async ({ page, request }) => {
  await fresh(request);
  await api(request, '/config', { device: { expert_mode: true } }, 'patch');
  await page.goto('/klang');
  await page.getByRole('link', { name: 'FIR-Filter importieren' }).click();
  await page.getByLabel(/Dateien wählen/).setInputFiles({ name: 'Sennheiser_HD_600-filters-48k.wav', mimeType: 'audio/wav', buffer: stereoWav() });
  await expect(page.getByText('Stereo · alle Abtastraten')).toBeVisible();
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Sennheiser HD 600');
  await axe(page, 'stereo-wav');
  await page.getByRole('button', { name: 'Importieren' }).click();
  await expect(page).toHaveURL(/\/klang\/preset\//, { timeout: 15000 });
  const s = await (await api(request, '/state', undefined, 'get')).json();
  const preset = s.dsp.presets.find((p) => p.name === 'Sennheiser HD 600');
  expect(preset).toBeTruthy();
});

test('Firmenzertifikat für den Proxy hinterlegen', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen/netzwerk');
  const pem = fs.readFileSync(new URL('../../tests/data/test-root-ca.pem', import.meta.url));
  const leaf = fs.readFileSync(new URL('../../tests/data/test-server.pem', import.meta.url));
  await page.getByLabel('Zertifikat wählen').setInputFiles({ name: 'webseite.pem', mimeType: 'application/x-pem-file', buffer: leaf });
  await expect(page.getByRole('alert').filter({ hasText: 'kein Stammzertifikat' })).toBeVisible();
  await axe(page, 'firmenzertifikat');
  await page.getByLabel('Zertifikat wählen').setInputFiles({ name: 'firma.cer', mimeType: 'application/x-x509-ca-cert', buffer: pem });
  await expect(page.getByText('Hinterlegt: Testfirma Root CA')).toBeVisible();
  await page.getByRole('button', { name: 'Zertifikat entfernen' }).click();
  await expect(page.getByText(/^Hinterlegt:/)).toHaveCount(0);
});

test('Anleitung: Aroio als App auf den Home-Bildschirm', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen/allgemein');
  await expect(page.getByRole('heading', { name: 'Als App auf dem Handy' })).toBeVisible();
  await page.getByRole('radio', { name: 'iPhone / iPad' }).check();
  await expect(page.getByText('„Zum Home-Bildschirm“')).toBeVisible();
  await page.getByRole('radio', { name: 'Android' }).check();
  await expect(page.getByText('„Zum Startbildschirm hinzufügen“')).toBeVisible();
  await axe(page, 'install-guide');
});

test('WLAN ausschalten', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen/netzwerk');
  const wlan = page.getByRole('switch', { name: 'WLAN', exact: true });
  await expect(wlan).toHaveAttribute('aria-checked', 'true');
  await wlan.click();                                   // with cable: off at once
  await expect(wlan).toHaveAttribute('aria-checked', 'false');
  await expect(page.getByRole('button', { name: 'Nach WLANs suchen' })).toHaveCount(0);
  await axe(page, 'wlan-aus');
  await wlan.click();
  await expect(wlan).toHaveAttribute('aria-checked', 'true');

  await api(request, '/sim/lan', { on: false });       // without cable: ask first
  await wlan.click();
  const dlg = page.getByRole('dialog', { name: 'WLAN ausschalten?' });
  await expect(dlg).toBeVisible();
  await axe(page, 'wlan-aus-dialog');
  await dlg.getByRole('button', { name: 'Abbrechen' }).click();
  await expect(wlan).toHaveAttribute('aria-checked', 'true');
  await wlan.click();
  await dlg.getByRole('button', { name: 'Ausschalten' }).click();
  await expect(wlan).toHaveAttribute('aria-checked', 'false');
  await api(request, '/sim/lan', { on: true });
});

test('Proxy einrichten und Internet testen', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen/netzwerk');
  const field = page.getByLabel('Proxy-Adresse');
  await field.fill('https://proxy.firma.de:8080');
  await page.getByRole('button', { name: 'Speichern' }).first().click();
  await expect(page.getByRole('alert')).toContainText('http://');
  await field.fill('http://max:geheim@proxy.firma.de:8080');
  await page.getByRole('button', { name: 'Speichern' }).first().click();
  await expect(page.getByText('Aktiv: http://max:••••@proxy.firma.de:8080')).toBeVisible();
  await expect(page.getByText('geheim')).toHaveCount(0);
  await page.getByRole('button', { name: 'Internetverbindung testen' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Internet erreichbar.' })).toBeVisible();
  await axe(page, 'proxy');
  await page.getByRole('button', { name: 'Proxy entfernen' }).click();
  await expect(page.getByText(/^Aktiv:/)).toHaveCount(0);
});

test('Lautsprecher prüfen: Ton oder Rauschen, Seite und Dauer', async ({ page, request }) => {
  await fresh(request);
  await page.goto('/einstellungen');
  await page.getByRole('link', { name: /Lautsprecher prüfen/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Lautsprecher prüfen' })).toBeVisible();
  await page.getByRole('radio', { name: 'Rosa Rauschen' }).check();
  await page.getByRole('radio', { name: 'Rechts' }).check();
  await page.getByLabel('Dauer').selectOption('30');
  await page.getByRole('button', { name: 'Abspielen' }).click();
  await expect(page.getByRole('status')).toContainText('Rauschen rechts, 30 s');
  await axe(page, 'lautsprecher');
  await page.getByRole('button', { name: 'Stopp' }).click();
  await expect(page.getByRole('button', { name: 'Stopp' })).toBeDisabled();
  await page.getByRole('radio', { name: 'Ton (440 Hz)' }).check();
  await page.getByRole('radio', { name: 'Links' }).check();
  await page.getByLabel('Dauer').selectOption('1');
  await page.getByRole('button', { name: 'Abspielen' }).click();
  await expect(page.getByRole('status')).toContainText('Ton links, 1 s');
  await expect(page.getByRole('button', { name: 'Stopp' })).toBeDisabled({ timeout: 4000 });   // ends by itself
});
