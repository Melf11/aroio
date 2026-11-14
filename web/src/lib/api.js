// Thin JSON client for aroiod. Errors carry the server's text for people.

export class ApiError extends Error {
  constructor(message, status, field) {
    super(message);
    this.status = status;
    this.field = field;
  }
}

async function call(method, path, data, opts = {}) {
  const init = { method, headers: {} };
  if (data instanceof FormData) init.body = data;
  else if (data !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(data);
  }
  let res;
  try {
    res = await fetch('/api/v1' + path, init);
  } catch {
    throw new ApiError('Der Aroio ist gerade nicht erreichbar.', 0);
  }
  if (opts.raw) return res;
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new ApiError(body?.error || `Fehler ${res.status}`, res.status, body?.field);
  return body;
}

export const api = {
  get: (p) => call('GET', p),
  post: (p, d = {}) => call('POST', p, d),
  patch: (p, d) => call('PATCH', p, d),
  del: (p) => call('DELETE', p),
  upload: (p, form) => call('POST', p, form),
  raw: (p) => call('GET', p, undefined, { raw: true }),
};

export const config = (patch) => api.patch('/config', patch);
export const player = (action, data) => api.post('/player/' + action, data);
export const roomcorr = (action, data) => api.post('/roomcorr/' + action, data);
export const sim = (event, data) => api.post('/sim/' + event, data);
