/** Issue #838: bounded local-history evidence lens; no hardware/control API. */
export const SESSION_KEY = '_cypher65_auth_session';
export const FIELDS = {
  temperature_c: { label: 'Temperatura', unit: '°C', min: -40, max: 150, color: '#f7931a' },
  hashrate_hs: { label: 'Hashrate', unit: 'H/s', min: 0, max: 1e18, color: '#eaeaea' },
  power_watts: { label: 'Potência', unit: 'W', min: 0, color: '#69d994' },
  fan_rpm: { label: 'Ventilação medida', unit: 'RPM', min: 0, max: 100000, color: '#ffcf64' },
  fan_speed: { label: 'PWM observado', unit: '%', min: 0, max: 100 },
  voltage_mv: { label: 'Tensão observada', unit: 'mV', min: 0 },
  frequency_mhz: { label: 'Frequência observada', unit: 'MHz', min: 0 },
};
export const STATES = { loading: 'Carregando histórico…', current: 'Histórico com observações recentes', stale: 'Última observação antiga — histórico, não capacidade atual',
  empty: 'Sem observações nesta janela', unknown: 'Sem observações válidas', offline: 'Dispositivo offline/pausado — somente histórico',
  auth: 'Sessão necessária — entre pelo painel neste navegador', error: 'Histórico indisponível — tente novamente', paused: 'Consulta interrompida' };

/** Existing-session reader. Invalid/unreadable storage never becomes anonymous.
 * @example readTimelineSession(() => localStorage)
 */
export function readTimelineSession(storage) {
  try {
    const store = typeof storage === 'function' ? storage() : storage;
    const key = store.getItem(SESSION_KEY);
    if (key === null) return { key: '', headers: {}, valid: true };
    const parsed = JSON.parse(key);
    if (typeof parsed?.access_token !== 'string' || !parsed.access_token) throw Error('invalid');
    return { key, headers: { Authorization: 'Bearer ' + parsed.access_token }, valid: true };
  } catch { return { key: 'invalid', headers: {}, valid: false }; }
}

/** Coalescing single-flight loader. New selections invalidate old JSON immediately,
 * but only the latest selection starts after the current bounded request settles.
 * @example const loader = createTimelineLoader({readSession, onData, onState}); loader.request({url});
 */
export function createTimelineLoader({ readSession, onData, onState, fetchImpl = fetch, schedule = setTimeout, cancel = clearTimeout,
  online = () => true, timeoutMs = 8000, intervalMs = 30000 }) {
  let version = 0, active = null, wanted = null, timer = null, stopped = false, failures = 0;
  function currentSession() { try { return readSession(); } catch { return { valid: false, key: 'unavailable', headers: {} }; } }
  function invalidate(state = 'paused') {
    version++; wanted = null; cancel(timer); timer = null; active?.abort(); onState(state);
  }
  async function drain() {
    if (active || !wanted || stopped) return;
    const selected = wanted; wanted = null;
    const lease = version, session = currentSession();
    if (!session.valid || !online()) { onState(session.valid ? 'offline' : 'auth'); return; }
    const controller = new AbortController(); active = controller;
    let deadline, retry = true;
    try {
      const body = (async () => {
        const response = await fetchImpl(selected.url, { method: 'GET', headers: session.headers, cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
        if ([401, 403].includes(response.status)) { const error = Error('auth'); error.auth = true; throw error; }
        if (!response.ok) throw Error('unavailable');
        return response.json();
      })();
      const data = await Promise.race([body, new Promise((_, reject) => {
        deadline = schedule(() => { controller.abort(); reject(Error('deadline')); }, timeoutMs);
      })]);
      if (lease !== version || stopped) return;
      if (session.key !== currentSession().key) { onState('auth'); retry = false; return; }
      onData(data, selected); failures = 0;
    } catch (error) {
      if (lease !== version || stopped) return;
      if (session.key !== currentSession().key) { onState('auth'); retry = false; return; }
      failures++; retry = !error.auth; onState(error.auth ? 'auth' : (online() ? 'error' : 'offline'));
    } finally {
      cancel(deadline); if (active === controller) active = null;
      if (!stopped && wanted) drain();
      else if (!stopped && lease === version && retry && online() && intervalMs > 0) timer = schedule(() => request(selected), Math.min(60000, intervalMs * 2 ** Math.min(failures, 2)));
    }
  }
  function request(selected) { if (stopped) return; invalidate('loading'); wanted = selected; return drain(); }
  return { request, invalidate, stop() { stopped = true; invalidate(); } };
}

/** Strictly validate finite, ordered observations before building any chart.
 * @example validTimeline(payload, {id:'fleet-id',hours:6})
 */
export function validTimeline(data, selected) {
  if (!data || data.schema_version !== 1 || data.device?.id !== selected.id || data.hours !== selected.hours ||
      !Number.isFinite(data.generated_at) || data.generated_at <= 0 || data.generated_at > 8.64e12 || data.stale_after_s !== 900 ||
      !['current', 'stale', 'empty', 'unknown', 'offline'].includes(data.state) ||
      !Array.isArray(data.samples) || data.samples.length > 300 || !Array.isArray(data.markers) || data.markers.length > 500 ||
      !data.coverage || !Number.isSafeInteger(data.coverage.returned) || data.coverage.returned !== data.samples.length) return false;
  if (!['returned', 'scanned', 'skipped', 'gaps'].every(key => Number.isSafeInteger(data.coverage[key]) && data.coverage[key] >= 0 && data.coverage[key] <= 300) ||
      typeof data.coverage.truncated !== 'boolean' || typeof data.maintenance_truncated !== 'boolean' ||
      !['available', 'unlinked', 'ambiguous', 'legacy_unscoped'].includes(data.maintenance_context) ||
      data.latest_sample_ts !== (data.samples.at(-1)?.ts ?? null)) return false;
  let previous = 0;
  return data.samples.every(sample => {
    if (!Number.isFinite(sample.ts) || sample.ts <= previous || sample.ts > data.generated_at || sample.ts < data.generated_at - selected.hours * 3600 || sample.source !== 'axe_telemetry' || sample.window_seconds !== null) return false;
    if (sample.gap_before_seconds !== null && (!Number.isFinite(sample.gap_before_seconds) || sample.gap_before_seconds <= 0)) return false;
    previous = sample.ts;
    return Object.entries(FIELDS).every(([key, field]) => sample[key] === null ||
      (Number.isFinite(sample[key]) && sample[key] >= field.min && (field.max === undefined || sample[key] <= field.max)));
  }) && data.markers.every(marker => Number.isFinite(marker.ts) && marker.ts >= data.generated_at - selected.hours * 3600 && marker.ts <= data.generated_at &&
    (marker.kind === 'maintenance' ? ['firmware_update', 'cleaning', 'hardware_check', 'repair', 'inspection', 'other'].includes(marker.type) :
      marker.kind === 'observed_configuration_change' && Array.isArray(marker.changes) && marker.changes.length > 0 && marker.changes.length <= 3 && marker.changes.every(change =>
        ['voltage_mv', 'frequency_mhz', 'fan_speed'].includes(change.field) &&
        Number.isFinite(change.before) && Number.isFinite(change.after) && change.before >= 0 && change.after >= 0 &&
        (change.field !== 'fan_speed' || change.before <= 100 && change.after <= 100))));
}

/** Preserve missing values and unit identity; RPM is never synthesized from PWM.
 * @example timelineValue(0, 'fan_rpm') // '0 RPM'
 */
export function timelineValue(value, key) {
  const field = Object.hasOwn(FIELDS, key) ? FIELDS[key] : null;
  if (!field || !Number.isFinite(value) || value < field.min || (field.max !== undefined && value > field.max)) return '—';
  let unit = field.unit;
  if (key === 'hashrate_hs' && value >= 1e12) { value /= 1e12; unit = 'TH/s'; }
  else if (key === 'hashrate_hs' && value >= 1e9) { value /= 1e9; unit = 'GH/s'; }
  return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(value) + ' ' + unit;
}

/** SVG lane segments use observation time, never connect nulls or gaps >900s.
 * @example timelineSegments(samples, 'temperature_c')
 */
export function timelineSegments(samples, field) {
  const groups = []; let current = [];
  for (const sample of samples) {
    const value = sample[field];
    if (!Number.isFinite(value)) { if (current.length) groups.push(current); current = []; continue; }
    if (current.length && (sample.ts - current.at(-1).ts > 900 || sample.gap_before_seconds !== null && sample.gap_before_seconds !== undefined)) { groups.push(current); current = []; }
    current.push({ ts: sample.ts, value });
  }
  if (current.length) groups.push(current);
  return groups;
}

/** Fit real observation timestamps without compressing any internal gaps.
 * The requested window remains available explicitly; no coverage is inferred.
 * @example timelineDomain(data, true)
 */
export function timelineDomain(data, focused = true) {
  const start = data.generated_at - data.hours * 3600, end = data.generated_at;
  if (!focused || !data.samples.length) return [start, end];
  const first = data.samples[0].ts, last = data.samples.at(-1).ts;
  return first === last ? [Math.max(start, first - 30), Math.min(end, last + 30)] : [first, last];
}
