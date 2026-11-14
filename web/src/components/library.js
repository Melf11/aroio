import { api } from '../lib/api.js';
import { toast } from '../lib/state.svelte.js';
import { t } from '../lib/i18n.svelte.js';

export async function play(id, mode = 'play', start = 0) {
  try {
    await api.post('/queue', { id, mode, start });
  } catch (e) {
    toast(e.message, 'danger');
  }
}

export async function favorite(id) {
  try {
    const r = await api.post('/library/favorite', { id });
    toast(r.favorite ? t('Zu Favoriten hinzugefügt.') : t('Aus Favoriten entfernt.'), 'ok');
    return r.favorite;
  } catch (e) {
    toast(e.message, 'danger');
  }
}

export const browseHref = (path) => '/musik/b?path=' + encodeURIComponent(path);
