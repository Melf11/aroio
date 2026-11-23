// Which device and browser the app runs in: for Einstellungen › Als App nutzen.
const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
const touchMac = /Macintosh/.test(ua) && typeof navigator !== 'undefined' && navigator.maxTouchPoints > 1;

export const os = /iPhone|iPad|iPod/.test(ua) || touchMac ? 'ios'
  : /Android/.test(ua) ? 'android'
  : /Macintosh|Mac OS X/.test(ua) ? 'mac'
  : /Windows/.test(ua) ? 'windows' : 'linux';

export const browser = /Edg\//.test(ua) ? 'edge'
  : /SamsungBrowser/.test(ua) ? 'samsung'
  : /Firefox|FxiOS/.test(ua) ? 'firefox'
  : /CriOS|Chrome|Chromium/.test(ua) ? 'chrome'
  : /Safari/.test(ua) ? 'safari' : 'other';

export const mobile = os === 'ios' || os === 'android';

export const installed = typeof window !== 'undefined'
  && (window.matchMedia?.('(display-mode: standalone)').matches
      || window.matchMedia?.('(display-mode: window-controls-overlay)').matches
      || navigator.standalone === true);
