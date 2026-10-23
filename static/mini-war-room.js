/** Issue #836: isolated read-only monitor; never loads the private dashboard bundle. */
export const SESSION_KEY = '_cypher65_auth_session';
const LABELS = {
  loading: 'Carregando observações…', current: 'Observações recentes', partial: 'Cobertura parcial',
  empty: 'Nenhum dispositivo cadastrado', unknown: 'Observações indisponíveis', stale: 'Dados antigos — capacidade atual indisponível',
  offline: 'Sem conexão — capacidade atual indisponível', error: 'Falha na consulta — tentativa automática limitada',
  auth: 'Sessão necessária — entre pelo painel neste navegador', paused: 'Consultas pausadas',
};

function validSnapshot(snapshot) {
  if (!snapshot || snapshot.schema_version !== 1 || !['current', 'partial', 'empty', 'unknown', 'stale', 'offline'].includes(snapshot.state) ||
      !Number.isFinite(snapshot.generated_at) || snapshot.generated_at <= 0 || snapshot.generated_at > 8.64e12 ||
      !snapshot.metrics || !snapshot.counts || snapshot.stale_after_s !== 900) return false;
  const counts = snapshot.counts;
  if (!['total', 'current', 'stale', 'offline', 'unknown'].every(key => Number.isSafeInteger(counts[key]) && counts[key] >= 0) ||
      counts.current + counts.stale + counts.offline + counts.unknown !== counts.total) return false;
  return [['hashrate', 'H/s'], ['power', 'W'], ['temperature', '°C']].every(([key, unit]) => {
    const metric = snapshot.metrics[key];
    if (!metric || metric.unit !== unit || !Number.isSafeInteger(metric.contributors) || metric.contributors < 0 || metric.contributors > counts.current) return false;
    if (metric.contributors === 0) return metric.value === null && metric.oldest_observed_at === null && metric.newest_observed_at === null;
    // Overflow may leave real contributor metadata but no representable sum.
    return (metric.value === null || (Number.isFinite(metric.value) && metric.value >= 0)) &&
      Number.isFinite(metric.oldest_observed_at) && metric.oldest_observed_at > 0 &&
      Number.isFinite(metric.newest_observed_at) && metric.newest_observed_at >= metric.oldest_observed_at && metric.newest_observed_at <= snapshot.generated_at;
  });
}

/** Read the existing session without copying credentials to URLs or another store.
 * @example readMiniSession(window.localStorage)
 */
export function readMiniSession(storage) {
  try {
    const raw = storage.getItem(SESSION_KEY);
    if (raw === null) return { key: '', headers: {}, valid: true };
    const session = JSON.parse(raw);
    if (!session || typeof session.access_token !== 'string' || !session.access_token) throw new Error('invalid');
    return { key: raw, headers: { Authorization: 'Bearer ' + session.access_token }, valid: true };
  } catch { return { key: 'invalid', headers: {}, valid: false }; }
}

/** Single-flight polling with session fencing and a deadline including JSON decoding.
 * Dependencies are injectable so tests run this production controller, not a mirror.
 * @example const monitor = createMiniController({ render, readSession }); monitor.refresh();
 */
export function createMiniController({ render, readSession, fetchImpl = fetch, now = () => Date.now() / 1000,
  schedule = setTimeout, cancel = clearTimeout, online = () => true, timeoutMs = 8000 }) {
  let active = null, next = null, expiry = null, generation = 0, stopped = false, paused = false, failures = 0;
  const clearTimers = () => { cancel(next); cancel(expiry); next = expiry = null; };
  const state = name => render({ state: name, snapshot: null, loading: false });
  const invalidate = name => {
    generation++; clearTimers(); active?.controller.abort(); state(name);
  };
  async function refresh() {
    if (stopped || paused || active) return;
    clearTimers();
    if (!online()) { state('offline'); return; }
    const session = readSession();
    if (!session.valid) { state('auth'); return; }
    const lease = generation;
    const job = { controller: new AbortController() };
    active = job;
    render({ state: 'loading', snapshot: null, loading: true });
    let deadline;
    let retry = true;
    try {
      const request = (async () => {
        const response = await fetchImpl('/api/mini-war-room', {
          method: 'GET', headers: session.headers, credentials: 'same-origin', cache: 'no-store', signal: job.controller.signal,
        });
        if (response.status === 401 || response.status === 403) { const error = new Error('auth'); error.auth = true; throw error; }
        if (!response.ok) throw new Error('unavailable');
        return response.json();
      })();
      const snapshot = await Promise.race([request, new Promise((_, reject) => {
        deadline = schedule(() => { job.controller.abort(); reject(new Error('deadline')); }, timeoutMs);
      })]);
      if (lease !== generation || session.key !== readSession().key || stopped || paused) return;
      if (!validSnapshot(snapshot)) throw new Error('schema');
      failures = 0;
      const timestamps = Object.values(snapshot.metrics).filter(m => m.value !== null).map(m => m.oldest_observed_at);
      if (timestamps.some(t => !Number.isFinite(t) || t > now())) throw new Error('timestamp');
      const remaining = timestamps.length ? Math.min(...timestamps) + snapshot.stale_after_s - now() : null;
      if (remaining !== null && remaining <= 0) state('stale');
      else {
        render({ state: snapshot.state, snapshot, loading: false });
        if (remaining !== null) expiry = schedule(() => state('stale'), remaining * 1000);
      }
    } catch (error) {
      if (lease !== generation || session.key !== readSession().key || stopped || paused) return;
      failures++;
      retry = !error.auth;
      state(error.auth ? 'auth' : (online() ? 'error' : 'offline'));
    } finally {
      cancel(deadline);
      if (active === job) active = null;
      if (!stopped && !paused && online() && retry) {
        next = schedule(refresh, Math.min(60000, 15000 * (2 ** Math.min(failures, 2))));
      }
    }
  }
  return {
    refresh,
    /** Invalidate pending responses before clearing any displayed observations. */
    invalidate,
    setPaused(value) { paused = value; invalidate(value ? 'paused' : 'loading'); if (!paused) refresh(); },
    sessionChanged() { invalidate('auth'); if (!active) refresh(); },
    connectivityChanged() { invalidate(online() ? 'loading' : 'offline'); if (online() && !active) refresh(); },
    stop() { stopped = true; invalidate('paused'); },
  };
}

/** Format only finite nonnegative values. Missing is never displayed as zero.
 * @example formatMiniMetric({value: 1e12, unit:'H/s'}) // '1 TH/s'
 */
export function formatMiniMetric(metric) {
  if (!metric || !Number.isFinite(metric.value) || metric.value < 0) return '—';
  let { value, unit } = metric;
  if (unit === 'H/s') {
    const scales = [[1e18, 'EH/s'], [1e15, 'PH/s'], [1e12, 'TH/s'], [1e9, 'GH/s'], [1e6, 'MH/s'], [1e3, 'kH/s']];
    const scale = scales.find(([threshold]) => value >= threshold);
    if (scale) { value /= scale[0]; unit = scale[1]; }
  }
  if (!['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s', 'W', '°C'].includes(unit)) return '—';
  return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(value) + ' ' + unit;
}

if (typeof document !== 'undefined' && document.getElementById('mini-war-room')) {
  const el = id => document.getElementById('mini-' + id);
  const render = ({ state, snapshot, loading }) => {
    el('state').textContent = LABELS[state] || LABELS.unknown;
    el('metrics').setAttribute('aria-busy', String(loading));
    el('refresh').disabled = loading;
    el('refresh').textContent = loading ? 'Consultando…' : 'Atualizar';
    el('coverage').textContent = snapshot ? `${snapshot.counts.current}/${snapshot.counts.total} dispositivos com observação recente; ${snapshot.counts.stale} antigos; ${snapshot.counts.offline} offline/pausados; ${snapshot.counts.unknown} sem observação elegível.` : 'Nenhuma capacidade atual confirmada nesta tela.';
    for (const key of ['hashrate', 'power', 'temperature']) {
      const metric = snapshot?.metrics[key];
      el(key).textContent = formatMiniMetric(metric);
      el(key + '-detail').textContent = metric && metric.value !== null ? `${metric.contributors} dispositivo(s) medido(s); observação mais antiga: ${new Date(metric.oldest_observed_at * 1000).toISOString()} (UTC); idade na consulta: ${Math.floor(snapshot.generated_at - metric.oldest_observed_at)} s.` : 'Medição indisponível; não equivale a zero.';
    }
    el('time').textContent = snapshot ? 'Consulta concluída: ' + new Date(snapshot.generated_at * 1000).toISOString() + ' (UTC). Leituras expiram em até 900 s.' : 'Sem consulta atual válida.';
  };
  const controller = createMiniController({ render, readSession: () => readMiniSession(localStorage), online: () => navigator.onLine });
  el('refresh').addEventListener('click', () => controller.refresh());
  el('pause').addEventListener('click', () => {
    const paused = el('pause').getAttribute('aria-pressed') !== 'true';
    el('pause').setAttribute('aria-pressed', String(paused)); el('pause').textContent = paused ? 'Retomar' : 'Pausar'; controller.setPaused(paused);
  });
  window.addEventListener('storage', event => { if (event.key === SESSION_KEY || event.key === null) controller.sessionChanged(); });
  window.addEventListener('offline', () => controller.connectivityChanged());
  window.addEventListener('online', () => controller.connectivityChanged());
  window.addEventListener('pagehide', () => controller.stop());
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  document.getElementById('mini-war-room').dataset.mounted = 'true';
  controller.refresh();
}
