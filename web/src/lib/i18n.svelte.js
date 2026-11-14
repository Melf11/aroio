// German text is the key; other languages map it. Missing entries fall back to
// German. tools/i18n-check.mjs lists keys without an English entry.
//
//   t('Lautstärke {v} Prozent', { v: 30 })
//   t('Hell|Darstellung')   same German word, different meaning: add a context

import { app } from './state.svelte.js';
import en from './en.js';

const dicts = { en };

export const lang = () => app.topics.device?.language || (navigator.language?.startsWith('de') ? 'de' : 'en');

export function t(text, vars) {
  const l = lang();
  // "Hell|Darstellung": the part after | is context for translators only
  let s = (l !== 'de' && dicts[l]?.[text]) || text.split('|')[0];
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''));
  return s;
}
