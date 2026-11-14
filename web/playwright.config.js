import { defineConfig } from '@playwright/test';

// End-to-end + accessibility tests against the built app served by aroiod
// with simulated hardware (fresh data directory per run).
export default defineConfig({
  testDir: 'e2e',
  timeout: 60000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8150', locale: 'de-DE', colorScheme: 'light' },
  projects: [
    { name: 'mobil', use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } },
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: 'cd .. && rm -rf .dev/e2e && .venv/bin/python -m aroiod --sim --data .dev/e2e --host 127.0.0.1 --port 8150 --static web/dist',
    url: 'http://127.0.0.1:8150/api/v1/state',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
