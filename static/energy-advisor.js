// @ts-check
/** DOM-only Energy Advisor; all costs are returned by the tested backend. */
import { SESSION_KEY, readEnergySession, createEnergyClient, validEnergyDevice, validEnergySnapshot, validEnergyEvaluation, energyNumber, energyMoney } from './energy-advisor-core.js';

const app = document.getElementById('energy-app');
if (app) {
  /** @template {HTMLElement} T @param {string} id @returns {T} */
  const el = id => /** @type {T} */ (document.getElementById('energy-' + id));
  const picker = /** @type {HTMLSelectElement} */ (el('device'));
  const form = /** @type {HTMLFormElement} */ (el('form'));
  const compare = /** @type {HTMLButtonElement} */ (el('evaluate'));
  /** @type {import('./energy-advisor-core.js').EnergyDevice|null} */ let device = null;
  let rowSerial = 0;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let expiry;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let evidenceExpiry;
  let freshUntil = 0;
  /** @template {keyof HTMLElementTagNameMap} K @param {K} tag @param {string} value @param {string} [className] @returns {HTMLElementTagNameMap[K]} */
  const text = (tag, value, className = '') => { const node = document.createElement(tag); node.textContent = value; node.className = className; return node; };
  /** @param {number} ts */
  const utc = ts => new Date(ts * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC');
  /** @param {import('./energy-advisor-core.js').EnergyDevice} d */
  const fingerprint = d => JSON.stringify([d.id, d.model, d.firmware, d.firmware_version, [...d.capabilities].sort()]);
  /** @param {import('./energy-advisor-core.js').EnergyDevice|null} d */
  const knownIdentity = d => !!d && [d.model, d.firmware, d.firmware_version].every(value => value.length > 0);
  /** @type {Record<string,string>} */
  const states = { loading: 'Consultando evidência…', current: 'Evidência recente — cenário não é previsão', stale: 'Telemetria antiga — comparação bloqueada',
    offline: 'Sem conexão / dispositivo indisponível — comparação bloqueada', unknown: 'Sem medição válida de potência — comparação bloqueada', empty: 'Sem telemetria — comparação bloqueada',
    auth: 'Sessão necessária — entre pelo painel neste navegador', error: 'Evidência indisponível — tente novamente', invalid: 'Premissas inválidas — confira os campos', paused: 'Consulta interrompida', edited: 'Premissas alteradas — compare novamente' };
  /** @type {Record<string,string>} */
  const reasons = { telemetry_unavailable_or_stale: 'Telemetria ausente, antiga ou indisponível', tariff_not_current: 'Tarifa fora da validade', not_operator_approved: 'Revisão do operador pendente',
    model_mismatch: 'Modelo não corresponde', firmware_mismatch: 'Firmware não corresponde', firmware_version_mismatch: 'Versão de firmware não corresponde',
    capabilities_mismatch: 'Capacidade requerida não confirmada', power_limit_exceeded: 'Acima do teto de potência informado', cost_limit_exceeded: 'Acima do teto de custo informado',
    no_eligible_profiles: 'Nenhum perfil atende aos critérios', device_metadata_unknown: 'Modelo ou firmware não confirmado no cadastro' };
  function clearResults(message = 'Compare novamente com as premissas atuais.') {
    el('result-cards').replaceChildren(); el('result-state').textContent = message; el('results').setAttribute('aria-busy', 'false');
  }
  /** @param {string} label @param {string} value */
  function metric(label, value) { const dl = text('dl', ''); dl.append(text('dt', label), text('dd', value)); return dl; }
  /** @param {string} state */
  function onState(state) {
    clearTimeout(expiry); clearResults(states[state] || 'Aguardando comparação.');
    el('state').textContent = states[state] || states.unknown;
    compare.disabled = state === 'loading' || !knownIdentity(device) || freshUntil <= Date.now() / 1000;
    el('refresh').toggleAttribute('disabled', state === 'loading');
    el('evidence').setAttribute('aria-busy', String(state === 'loading'));
    if (state !== 'loading') el('baseline').querySelector('.energy-skeleton')?.remove();
    if (state === 'loading') { el('baseline').replaceChildren(text('div', '', 'energy-skeleton')); el('freshness').textContent = 'Consultando a amostra mais recente, sem recorrer a dados antigos.'; }
    if (['auth', 'paused', 'offline', 'error'].includes(state)) {
      clearTimeout(evidenceExpiry); freshUntil = 0;
      device = null; compare.disabled = true; el('baseline').replaceChildren(); el('freshness').textContent = 'Nenhuma evidência atual disponível.';
      el('identity').textContent = 'Identidade indisponível — revisão de perfis invalidada.';
      for (const box of document.querySelectorAll('.profile-approved')) /** @type {HTMLInputElement} */ (box).checked = false;
    }
    if (state === 'auth' || state === 'paused') { picker.replaceChildren(new Option('Sessão indisponível', '')); picker.disabled = true; }
  }
  /** @param {import('./energy-advisor-core.js').EnergySnapshot} data */
  function evidence(data) {
    clearTimeout(evidenceExpiry); freshUntil = 0;
    if (device && fingerprint(device) !== fingerprint(data.device)) {
      for (const box of document.querySelectorAll('.profile-approved')) /** @type {HTMLInputElement} */ (box).checked = false;
      clearResults('Modelo, firmware ou capacidades mudaram — revise os perfis novamente.');
    }
    const identity = data.device; device = identity;
    el('state').textContent = states[data.telemetry.state] || states.unknown;
    el('evidence').setAttribute('aria-busy', 'false'); el('baseline').replaceChildren(
      metric('Potência reportada pelo firmware', energyNumber(data.telemetry.power_watts, 'W')),
      metric('Hashrate do dispositivo', energyNumber(data.telemetry.hashrate_hs === null ? null : data.telemetry.hashrate_hs / 1e12, 'TH/s')));
    el('freshness').textContent = data.telemetry.observed_at === null ? 'Sem observação válida. Nenhum valor foi presumido.' :
      `Fonte: axe_telemetry · ${utc(data.telemetry.observed_at)} · idade na consulta: ${energyNumber(data.telemetry.age_seconds, 's')}. Validade: 900 s. Janela média desconhecida. Potência não é medição de tomada; perdas de fonte e refrigeração não incluídas.`;
    el('identity').textContent = `Cadastro: ${identity.model || 'modelo desconhecido'} · ${identity.firmware || 'firmware desconhecido'} · versão ${identity.firmware_version || 'desconhecida'}. Associação cadastral, não certificação física.`;
    compare.disabled = data.telemetry.state !== 'current' || !knownIdentity(identity); el('refresh').removeAttribute('disabled');
    if (data.telemetry.state === 'current' && data.telemetry.observed_at !== null) {
      freshUntil = data.telemetry.observed_at + 900;
      const remaining = freshUntil - Date.now() / 1000;
      compare.disabled = remaining <= 0 || !knownIdentity(identity);
      evidenceExpiry = setTimeout(() => { compare.disabled = true; clearResults('A evidência venceu — atualize antes de comparar.'); el('state').textContent = states.stale; }, Math.max(0, remaining * 1000));
    }
    if (!knownIdentity(identity)) el('state').textContent = 'Cadastro incompleto — revise modelo e firmware antes de comparar perfis.';
  }
  const session = () => readEnergySession(() => localStorage);
  const client = createEnergyClient({ readSession: session, online: () => navigator.onLine, onState, onData(data, request) {
    if (request.kind === 'devices') {
      const list = /** @type {{devices:import('./energy-advisor-core.js').EnergyDevice[],truncated:boolean}} */ (data);
      if (!list || !Array.isArray(list.devices) || list.devices.length > 100 || !list.devices.every(validEnergyDevice) || typeof list.truncated !== 'boolean') throw Error('schema');
      picker.replaceChildren(...list.devices.map(d => new Option(d.name || 'Sem nome', d.id))); picker.disabled = !list.devices.length;
      el('source').textContent = 'Fonte: cadastro e telemetria locais.' + (list.truncated ? ' Lista limitada aos 100 primeiros dispositivos.' : '');
      if (list.devices.length) refresh(); else { onState('empty'); compare.disabled = true; }
    } else if (request.kind === 'snapshot') {
      if (!validEnergySnapshot(data, request.id || '')) throw Error('schema'); evidence(data);
    } else {
      if (!validEnergyEvaluation(data, request.id || '')) throw Error('schema'); evidence(data); clearResults();
      const deadline = data.expires_at;
      const available = data.baseline.state === 'available' && deadline !== null && deadline > Date.now() / 1000;
      el('result-state').textContent = available ? `Cenário constante de ${data.hours} h · tarifa ${energyNumber(data.tariff.value, data.currency + '/kWh')} confirmada pelo operador em ${utc(data.tariff.observed_at)}, válida até ${utc(data.tariff.valid_until)}. Sem ranking de desempenho e sem aplicação.` : 'Comparação bloqueada: confira a validade da tarifa e da telemetria. Nenhum perfil foi aplicado.';
      if (!available || deadline === null) return;
      const base = text('article', '', 'scenario'); base.append(text('h3', 'Referência: potência medida constante'), text('p', energyMoney(data.baseline.cost, data.currency, data.baseline.cost_below_resolution), 'cost'), text('p', (data.baseline.energy_below_resolution ? '< 0,000001' : data.baseline.energy_kwh) + ' kWh'), text('p', 'Extrapolação da amostra, não energia já consumida.', 'fine')); el('result-cards').append(base);
      for (const profile of data.profiles) {
        const card = text('article', '', 'scenario'); card.dataset.eligible = String(profile.eligible);
        card.append(text('h3', profile.name), text('span', profile.eligible ? 'Atende aos critérios informados' : 'Não elegível', 'badge'),
          text('p', energyMoney(profile.cost, data.currency, profile.cost_below_resolution), 'cost'), text('p', energyNumber(profile.expected_power_watts, 'W') + ' supostos · ' + (profile.energy_below_resolution ? '< 0,000001' : profile.energy_kwh) + ' kWh'));
        const list = text('ul', '');
        for (const reason of profile.reasons) list.append(text('li', Object.hasOwn(reasons, reason) ? reasons[reason] : 'Critério não confirmado: ' + reason));
        if (!profile.reasons.length) list.append(text('li', 'Revisado pelo operador; modelo, firmware, versão e capacidades correspondem ao cadastro.'), text('li', 'Potência e tarifa dentro dos tetos informados; desempenho não avaliado.'));
        card.append(list); el('result-cards').append(card);
      }
      clearTimeout(expiry); expiry = setTimeout(() => clearResults('A tarifa ou a evidência venceu — atualize e compare novamente.'), Math.max(0, (deadline - Date.now() / 1000) * 1000));
    }
  } });
  function refresh() {
    if (!picker.value) { client.request({ url: '/api/energy-advisor/devices', kind: 'devices' }); return; }
    client.request({ url: '/api/energy-advisor/snapshot?device_id=' + encodeURIComponent(picker.value), id: picker.value, kind: 'snapshot' });
  }
  function addProfile() {
    const host = el('profile-rows'); if (host.children.length >= 3) return;
    const row = text('div', '', 'profile-row'), fields = text('div', '', 'form-grid'), id = ++rowSerial;
    row.dataset.id = 'profile-' + id;
    for (const [key, labelText, type] of [['name', 'Nome do perfil', 'text'], ['power', 'Potência esperada (W)', 'number']]) {
      const label = text('label', labelText), input = /** @type {HTMLInputElement} */ (text('input', ''));
      input.id = `energy-profile-${id}-${key}`; label.htmlFor = input.id; input.className = 'profile-' + key; input.type = type; input.required = true;
      if (type === 'number') { input.min = '0'; input.max = '1000000'; input.step = 'any'; } else input.maxLength = 128;
      label.append(input); fields.append(label);
    }
    const label = text('label', '', 'approval'), approve = /** @type {HTMLInputElement} */ (text('input', '')); approve.type = 'checkbox'; approve.className = 'profile-approved';
    label.append(approve, text('span', 'Revisei este cenário para o modelo e firmware exibidos. Isso não autoriza nem certifica alteração no hardware.'));
    const remove = /** @type {HTMLButtonElement} */ (text('button', 'Remover perfil', 'remove-profile')); remove.type = 'button';
    remove.addEventListener('click', () => { row.remove(); el('add-profile').removeAttribute('disabled'); client.invalidate('edited'); });
    row.append(fields, label, remove); host.append(row); el('add-profile').toggleAttribute('disabled', host.children.length >= 3);
  }
  form.addEventListener('input', event => {
    const row = /** @type {HTMLElement} */ (event.target)?.closest('.profile-row');
    if (row && !/** @type {HTMLElement} */ (event.target).classList.contains('profile-approved')) /** @type {HTMLInputElement} */ (row.querySelector('.profile-approved')).checked = false;
    if (row && /** @type {HTMLElement} */ (event.target).classList.contains('profile-approved') && device) /** @type {HTMLInputElement} */ (event.target).dataset.identity = fingerprint(device);
    client.invalidate('edited');
  });
  form.addEventListener('submit', event => {
    event.preventDefault(); if (!device || !form.reportValidity()) return;
    /** @param {string} id */
    const input = id => /** @type {HTMLInputElement} */ (el(id)).value;
    const now = Math.floor(Date.now() / 1000), identity = device;
    const profiles = [...document.querySelectorAll('.profile-row')].map(row => ({ id: /** @type {HTMLElement} */ (row).dataset.id,
      name: /** @type {HTMLInputElement} */ (row.querySelector('.profile-name')).value.trim(),
      expected_power_watts: Number(/** @type {HTMLInputElement} */ (row.querySelector('.profile-power')).value),
      approved: /** @type {HTMLInputElement} */ (row.querySelector('.profile-approved')).checked && /** @type {HTMLInputElement} */ (row.querySelector('.profile-approved')).dataset.identity === fingerprint(identity),
      model: identity.model, firmware: identity.firmware, firmware_version: identity.firmware_version, required_capabilities: ['telemetry'] }));
    const constraints = { max_power_watts: Number(input('max-power')), ...(input('max-cost') === '' ? {} : { max_cost: Number(input('max-cost')) }) };
    client.request({ url: '/api/energy-advisor/evaluate', id: identity.id, kind: 'evaluate', body: { device_id: identity.id, hours: Number(input('hours')),
      tariff: { value: Number(input('tariff')), currency: input('currency'), observed_at: now, valid_until: now + Number(input('validity')) * 60, source: 'operator' }, constraints, profiles } });
  });
  picker.addEventListener('change', () => { device = null; for (const box of document.querySelectorAll('.profile-approved')) /** @type {HTMLInputElement} */ (box).checked = false; refresh(); });
  el('add-profile').addEventListener('click', () => { addProfile(); client.invalidate('edited'); }); el('refresh').addEventListener('click', refresh);
  window.addEventListener('storage', event => { if (event.key === SESSION_KEY || event.key === null) { client.invalidate('auth'); client.request({ url: '/api/energy-advisor/devices', kind: 'devices' }); } });
  window.addEventListener('offline', () => client.invalidate('offline')); window.addEventListener('online', refresh);
  window.addEventListener('pagehide', () => client.stop()); window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  addProfile(); app.dataset.mounted = 'true'; client.request({ url: '/api/energy-advisor/devices', kind: 'devices' });
}
