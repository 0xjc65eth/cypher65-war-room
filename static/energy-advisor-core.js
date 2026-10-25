// @ts-check
/** Read-only Energy Advisor contracts and bounded transport (Issue #837). */
export const SESSION_KEY = '_cypher65_auth_session';
export const CURRENCIES = ['EUR', 'USD', 'BRL', 'GBP'];
/** @typedef {{key:string, valid:boolean, headers:Record<string,string>}} EnergySession */
/** @typedef {{id:string,name:string,model:string,firmware:string,firmware_version:string,capabilities:string[]}} EnergyDevice */
/** @typedef {{state:string,source:string,observed_at:number|null,age_seconds:number|null,stale_after_s:number,power_watts:number|null,hashrate_hs:number|null,temperature_c:number|null}} EnergyTelemetry */
/** @typedef {{schema_version:number,generated_at:number,device:EnergyDevice,telemetry:EnergyTelemetry,solar:{state:string,power_watts:number|null}}} EnergySnapshot */
/** @typedef {{id:string,name:string,eligible:boolean,reasons:string[],expected_power_watts:number,energy_kwh:string,cost:string,cost_below_resolution:boolean,energy_below_resolution:boolean}} EnergyProfileResult */
/** @typedef {EnergySnapshot & {mode:string,currency:string,hours:number,tariff_state:string,tariff:{value:number,currency:string,source:string,observed_at:number,valid_until:number},expires_at:number|null,baseline:{state:string,energy_kwh:string|null,cost:string|null,cost_below_resolution:boolean,energy_below_resolution:boolean},profiles:EnergyProfileResult[],suggestion:{type:string,profile_id:null,eligible_profile_ids:string[]}}} EnergyEvaluation */
/** @typedef {{url:string,kind:'devices'|'snapshot'|'evaluate',id?:string,body?:object}} EnergyRequest */

/** Read the existing session without falling back to anonymous on storage errors.
 * @param {()=>Storage} storage
 * @returns {EnergySession}
 * @example readEnergySession(() => localStorage)
 */
export function readEnergySession(storage) {
  try {
    const key = storage().getItem(SESSION_KEY);
    if (key === null) return { key: '', valid: true, headers: {} };
    const parsed = JSON.parse(key);
    if (typeof parsed?.access_token !== 'string' || !parsed.access_token) throw Error('session');
    return { key, valid: true, headers: { Authorization: 'Bearer ' + parsed.access_token } };
  } catch { return { key: 'unavailable', valid: false, headers: {} }; }
}

/** Coalesce requests and fence delayed JSON by session and selection. Computational
 * POSTs are not replayed automatically; GETs retry once with bounded backoff.
 * @param {{readSession:()=>EnergySession,onData:(data:unknown,request:EnergyRequest)=>void,onState:(state:string)=>void,fetchImpl?:typeof fetch,online?:()=>boolean,timeoutMs?:number,retryMs?:number}} options
 * @example const client = createEnergyClient(options); client.request({url:'/api/energy-advisor/devices',kind:'devices'});
 */
export function createEnergyClient({ readSession, onData, onState, fetchImpl = fetch, online = () => true, timeoutMs = 8000, retryMs = 1000 }) {
  let version = 0, stopped = false;
  /** @type {AbortController|null} */ let active = null;
  /** @type {EnergyRequest|null} */ let wanted = null;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let retry;
  const session = () => { try { return readSession(); } catch { return { key: 'unavailable', valid: false, headers: {} }; } };
  function invalidate(state = 'paused') {
    version++; wanted = null; clearTimeout(retry); active?.abort(); onState(state);
  }
  async function drain(attempt = 0) {
    if (active || !wanted || stopped) return;
    const selected = wanted; wanted = null;
    const lease = version, auth = session();
    if (!auth.valid || !online()) { onState(auth.valid ? 'offline' : 'auth'); return; }
    const controller = new AbortController(); active = controller;
    /** @type {ReturnType<typeof setTimeout>|undefined} */ let deadline;
    try {
      const payload = (async () => {
        const response = await fetchImpl(selected.url, { method: selected.body ? 'POST' : 'GET',
          headers: { ...auth.headers, ...(selected.body ? { 'Content-Type': 'application/json' } : {}) },
          ...(selected.body ? { body: JSON.stringify(selected.body) } : {}),
          credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw Error([401, 403].includes(response.status) ? 'auth' : response.status === 400 ? 'invalid' : 'error');
        return response.json();
      })();
      const data = await Promise.race([payload, new Promise((_, reject) => { deadline = setTimeout(() => { controller.abort(); reject(Error('error')); }, timeoutMs); })]);
      if (lease !== version || stopped) return;
      if (auth.key !== session().key) { onState('auth'); return; }
      onData(data, selected);
    } catch (error) {
      if (lease !== version || stopped) return;
      if (auth.key !== session().key) { onState('auth'); return; }
      const code = error instanceof Error ? error.message : 'error';
      if (!selected.body && attempt === 0 && online() && !['auth', 'invalid'].includes(code)) {
        retry = setTimeout(() => { if (lease === version && !stopped) { wanted = selected; drain(1); } }, retryMs);
      } else onState(code === 'auth' ? 'auth' : code === 'invalid' ? 'invalid' : online() ? 'error' : 'offline');
    } finally {
      clearTimeout(deadline); active = null;
      if (wanted && !stopped) drain();
    }
  }
  return {
    /** @param {EnergyRequest} request */ request(request) { if (stopped) return; invalidate('loading'); wanted = request; return drain(); },
    invalidate,
    stop() { stopped = true; invalidate(); },
  };
}

/** Validate a decimal wire value before formatting; null is not zero.
 * @param {unknown} value
 * @returns {value is string}
 * @example validDecimal('0.25') // true
 */
export function validDecimal(value) {
  return typeof value === 'string' && /^\d{1,16}(?:\.\d{1,12})?$/.test(value) && Number.isFinite(Number(value));
}

/** Validate a minimal public device, not hardware attestation.
 * @param {unknown} value
 * @returns {value is EnergyDevice}
 * @example validEnergyDevice({id:'a',name:'Lab',model:'',firmware:'',firmware_version:'',capabilities:[]})
 */
export function validEnergyDevice(value) {
  if (!value || typeof value !== 'object') return false;
  const d = /** @type {Record<string,unknown>} */ (value);
  return ['id', 'name', 'model', 'firmware', 'firmware_version'].every(k => typeof d[k] === 'string' && d[k].length <= 128) &&
    typeof d.id === 'string' && d.id.length > 0 && Array.isArray(d.capabilities) && d.capabilities.length <= 14 && d.capabilities.every(c => typeof c === 'string');
}

/** Validate source identity and units before showing private evidence.
 * @param {unknown} value
 * @param {string} id
 * @returns {value is EnergySnapshot}
 * @example validEnergySnapshot(payload, 'fleet-id')
 */
export function validEnergySnapshot(value, id) {
  if (!value || typeof value !== 'object') return false;
  const d = /** @type {EnergySnapshot} */ (value), t = d.telemetry;
  return d.schema_version === 1 && Number.isSafeInteger(d.generated_at) && d.generated_at > 0 && validEnergyDevice(d.device) && d.device.id === id &&
    !!t && t.source === 'axe_telemetry' && t.stale_after_s === 900 && ['current', 'stale', 'offline', 'unknown', 'empty'].includes(t.state) &&
    (t.observed_at === null || Number.isSafeInteger(t.observed_at) && t.observed_at > 0 && t.observed_at <= d.generated_at) &&
    (t.observed_at === null ? t.age_seconds === null : Number.isSafeInteger(t.age_seconds) && t.age_seconds === d.generated_at - t.observed_at) &&
    /** @type {const} */ (['power_watts', 'hashrate_hs', 'temperature_c']).every(k => t[k] === null || typeof t[k] === 'number' && Number.isFinite(t[k]) && t[k] >= (k === 'temperature_c' ? -40 : 0) && t[k] <= (k === 'temperature_c' ? 150 : k === 'hashrate_hs' ? 1e18 : 1e9)) &&
    (t.state !== 'current' || t.observed_at !== null && t.age_seconds !== null && t.age_seconds < 900 && typeof t.power_watts === 'number' && typeof t.hashrate_hs === 'number') &&
    d.solar?.state === 'not_configured' && d.solar.power_watts === null;
}

/** Validate the server's explainable scenario response before any cost display.
 * @param {unknown} value
 * @param {string} id
 * @returns {value is EnergyEvaluation}
 * @example validEnergyEvaluation(payload, 'fleet-id')
 */
export function validEnergyEvaluation(value, id) {
  if (!validEnergySnapshot(value, id)) return false;
  const d = /** @type {EnergyEvaluation} */ (value);
  return d.mode === 'read_only' && CURRENCIES.includes(d.currency) && Number.isSafeInteger(d.hours) && d.hours >= 1 && d.hours <= 24 &&
    ['current', 'expired', 'future'].includes(d.tariff_state) && !!d.tariff && d.tariff.source === 'operator' &&
    typeof d.tariff.value === 'number' && Number.isFinite(d.tariff.value) && d.tariff.value >= 0 && d.tariff.currency === d.currency &&
    Number.isSafeInteger(d.tariff.observed_at) && Number.isSafeInteger(d.tariff.valid_until) && d.tariff.valid_until > d.tariff.observed_at &&
    !!d.baseline && ['available', 'blocked'].includes(d.baseline.state) && typeof d.baseline.cost_below_resolution === 'boolean' && typeof d.baseline.energy_below_resolution === 'boolean' &&
    (d.baseline.state === 'available' ? d.telemetry.state === 'current' && d.tariff_state === 'current' && validDecimal(d.baseline.cost) && validDecimal(d.baseline.energy_kwh) &&
      typeof d.expires_at === 'number' && d.telemetry.observed_at !== null && Number.isSafeInteger(d.expires_at) && d.expires_at > d.generated_at && d.expires_at <= d.tariff.valid_until && d.expires_at <= d.telemetry.observed_at + 900 : d.expires_at === null && d.baseline.cost === null && d.baseline.energy_kwh === null) &&
    Array.isArray(d.profiles) && d.profiles.length <= 8 && d.profiles.every(p => typeof p.id === 'string' && p.id.length <= 128 && typeof p.name === 'string' && p.name.length <= 128 &&
      typeof p.eligible === 'boolean' && (!p.eligible || d.baseline.state === 'available') && Array.isArray(p.reasons) && p.reasons.length <= 16 && p.reasons.every(r => typeof r === 'string') &&
      typeof p.expected_power_watts === 'number' && Number.isFinite(p.expected_power_watts) && p.expected_power_watts >= 0 && validDecimal(p.cost) && validDecimal(p.energy_kwh) && typeof p.cost_below_resolution === 'boolean' && typeof p.energy_below_resolution === 'boolean') &&
    d.suggestion?.type === 'review_candidates' && d.suggestion.profile_id === null && Array.isArray(d.suggestion.eligible_profile_ids) &&
    d.suggestion.eligible_profile_ids.length <= 8 && d.suggestion.eligible_profile_ids.every(id => d.profiles.some(p => p.id === id && p.eligible));
}

/** Format source-backed numeric values without coercing missing data.
 * @param {unknown} value
 * @param {string} unit
 * @example energyNumber(0, 'W') // '0 W'
 */
export function energyNumber(value, unit) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return (value > 0 && value < .001 ? '< 0,001' : new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 }).format(value)) + ' ' + unit;
}

/** Format bounded modelled costs, never a profit claim.
 * @param {unknown} value
 * @param {string} currency
 * @param {boolean} [belowResolution]
 * @example energyMoney('0.10', 'EUR')
 */
export function energyMoney(value, currency, belowResolution = false) {
  if (!validDecimal(value) || !CURRENCIES.includes(currency)) return '—';
  if (belowResolution) return '< ' + new Intl.NumberFormat('pt-BR', { style: 'currency', currency, minimumFractionDigits: 6, maximumFractionDigits: 6 }).format(.000001);
  const tiny = Number(value) > 0 && Number(value) < .0001;
  return (tiny ? '< ' : '') + new Intl.NumberFormat('pt-BR', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(tiny ? .0001 : Number(value));
}
