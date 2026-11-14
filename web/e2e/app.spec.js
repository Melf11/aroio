import { test, expect } from '@playwright/test';
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
  '/einstellungen/bluetooth', '/einstellungen/updates', '/einstellungen/geraet'];
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
  await page.getByRole('button', { name: 'Weiter' }).click();
  await expect(page.getByRole('heading', { name: 'Welche Soundkarte steckt im Aroio?' })).toBeVisible();
  await expect(page.getByRole('radio', { name: /^Aroio DAC/ })).toBeChecked();         // default
  await axe(page, 'setup-dac');
  await page.getByRole('button', { name: 'Weiter' }).click();
  await axe(page, 'setup-end');
  await page.getByRole('button', { name: 'Zum Aroio' }).click();
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
