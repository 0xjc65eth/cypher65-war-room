/** Issue #838: DOM presentation only; tested core is the production import below. */
import { SESSION_KEY, STATES, FIELDS, readTimelineSession, createTimelineLoader, validTimeline, timelineValue, timelineSegments, timelineDomain } from './thermal-timeline-core.js';

if (typeof document !== 'undefined' && document.getElementById('thermal-app')) {
  const el = id => document.getElementById('thermal-' + id);
  let model = null, expiry = null, focused = true;
  const utc = ts => new Date(ts * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC');
  const text = (tag, value, className) => { const node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; };
  const placeholder = label => { const option = text('option', label); option.value = ''; return option; };
  function state(name) {
    clearTimeout(expiry); el('state').textContent = STATES[name] || STATES.unknown;
    el('workspace').setAttribute('aria-busy', String(name === 'loading')); el('refresh').disabled = name === 'loading';
    if (name === 'stale' && model) return;
    if (name === 'auth' || name === 'paused') { el('device').replaceChildren(placeholder('Sessão indisponível')); el('device').disabled = true; }
    model = null; el('charts').replaceChildren(); el('values').replaceChildren(); el('events').replaceChildren();
    el('cursor').disabled = true; el('focus').disabled = true; el('selected-time').textContent = '—';
    el('coverage').textContent = 'Nenhuma observação válida selecionada.'; el('config').textContent = 'Configuração observada: indisponível.';
    el('maintenance').textContent = 'Contexto de manutenção indisponível.';
  }
  function drawLanes(index) {
    el('charts').replaceChildren();
    const samples = model.samples, [start, end] = timelineDomain(model, focused);
    const x = ts => ((ts - start) / (end - start)) * 1000;
    for (const key of ['temperature_c', 'hashrate_hs', 'power_watts', 'fan_rpm']) {
      const field = FIELDS[key], groups = timelineSegments(samples, key), values = groups.flat().map(p => p.value);
      const min = values.length ? Math.min(...values) : 0, max = values.length ? Math.max(...values) : 0;
      const row = text('div', '', 'thermal-lane'), label = text('div', field.label, 'thermal-lane-label');
      label.append(text('small', values.length ? timelineValue(min, key) + ' → ' + timelineValue(max, key) : 'Sem medição'));
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 1000 80'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
      for (let i = 1; i < samples.length; i++) {
        if (!samples[i].gap_before_seconds) continue;
        const region = document.createElementNS(svg.namespaceURI, 'rect'); region.setAttribute('x', String(x(samples[i - 1].ts))); region.setAttribute('y', '0'); region.setAttribute('width', String(x(samples[i].ts) - x(samples[i - 1].ts))); region.setAttribute('height', '80'); region.setAttribute('fill', '#53575d'); region.setAttribute('opacity', '.22'); region.setAttribute('data-gap', 'true'); svg.append(region);
      }
      for (const group of groups) {
        const points = group.map(point => `${x(point.ts)},${max === min ? 40 : 68 - ((point.value - min) / (max - min)) * 56}`).join(' ');
        const line = document.createElementNS(svg.namespaceURI, 'polyline'); line.setAttribute('points', points); line.setAttribute('stroke', field.color); line.setAttribute('stroke-width', '2'); line.setAttribute('fill', 'none'); line.setAttribute('vector-effect', 'non-scaling-stroke'); svg.append(line);
        if (group.length === 1) { const dot = document.createElementNS(svg.namespaceURI, 'circle'); dot.setAttribute('cx', String(x(group[0].ts))); dot.setAttribute('cy', String(max === min ? 40 : 68 - ((group[0].value - min) / (max - min)) * 56)); dot.setAttribute('r', '3'); dot.setAttribute('fill', field.color); svg.append(dot); }
      }
      if (samples[index]) { const cursor = document.createElementNS(svg.namespaceURI, 'line'); cursor.setAttribute('x1', String(x(samples[index].ts))); cursor.setAttribute('x2', String(x(samples[index].ts))); cursor.setAttribute('y1', '0'); cursor.setAttribute('y2', '80'); cursor.setAttribute('stroke', '#b4c8dd'); cursor.setAttribute('stroke-dasharray', '3 4'); svg.append(cursor); }
      row.append(label, svg); el('charts').append(row);
    }
    el('charts').append(text('p', utc(start) + ' → ' + utc(end) + (focused ? ` · Recorte observado; janela consultada: ${model.hours} h. Fora do recorte não há cobertura comprovada.` : ' · Janela inteira consultada.') + ' Escala independente por faixa; áreas cinzas são lacunas de observação, não diagnóstico de falha.'));
  }
  function inspect(index) {
    if (!model?.samples.length) return;
    const sample = model.samples[index]; if (!sample) return;
    el('values').replaceChildren();
    for (const key of ['temperature_c', 'hashrate_hs', 'power_watts', 'fan_rpm', 'fan_speed']) {
      const card = text('dl', '', 'thermal-value'); card.append(text('dt', FIELDS[key].label), text('dd', timelineValue(sample[key], key))); el('values').append(card);
    }
    el('selected-time').textContent = utc(sample.ts); el('cursor').setAttribute('aria-valuetext', utc(sample.ts) + ', temperatura ' + timelineValue(sample.temperature_c, 'temperature_c'));
    el('config').textContent = 'Configuração observada: ' + timelineValue(sample.frequency_mhz, 'frequency_mhz') + ' · ' + timelineValue(sample.voltage_mv, 'voltage_mv') + '. Fonte: ' + sample.source + '; janela média não informada.';
    drawLanes(index);
  }
  const session = () => readTimelineSession(() => localStorage);
  const loader = createTimelineLoader({ readSession: session, online: () => navigator.onLine, onState: state, onData(data, selected) {
    if (!validTimeline(data, selected)) throw Error('invalid schema');
    state(data.state); model = data;
    el('coverage').textContent = `${data.coverage.returned} observações · ${data.coverage.gaps} lacunas de observação · ${data.coverage.skipped} registros ignorados${data.coverage.truncated ? ' · Limite atingido: este recorte não cobre necessariamente toda a janela.' : ''} Consulta: ${utc(data.generated_at)}.`;
    const context = { available: 'Manutenção vinculada por tenant e MAC único no cadastro; não é atestado físico.', unlinked: 'Sem associação inequívoca entre os cadastros de frota e manutenção.', ambiguous: 'Associação ambígua: manutenção não vinculada.', legacy_unscoped: 'Há registros legados sem tenant; eles não foram associados.' };
    el('maintenance').textContent = context[data.maintenance_context] + (data.maintenance_truncated ? ' Limite: 200 manutenções mais recentes neste recorte.' : '');
    const maintenance = { cleaning: 'Limpeza registrada', firmware_update: 'Atualização de firmware registrada', hardware_check: 'Verificação de hardware registrada', repair: 'Reparo registrado', inspection: 'Inspeção registrada' };
    for (const marker of data.markers) {
      let title = Object.hasOwn(maintenance, marker.type) ? maintenance[marker.type] : 'Manutenção registrada';
      if (marker.kind === 'observed_configuration_change') title = 'Mudança observada: ' + (Array.isArray(marker.changes) ? marker.changes : []).filter(change => Object.hasOwn(FIELDS, change.field)).map(change => FIELDS[change.field].label + ' ' + timelineValue(change.before, change.field) + ' → ' + timelineValue(change.after, change.field)).join('; ');
      el('events').append(text('li', utc(marker.ts) + ' — ' + title));
    }
    if (!data.markers.length) el('events').append(text('li', 'Nenhum marco comprovado disponível neste recorte.'));
    el('cursor').disabled = !data.samples.length; el('focus').disabled = !data.samples.length; el('cursor').max = String(Math.max(0, data.samples.length - 1)); el('cursor').value = el('cursor').max;
    if (data.samples.length) inspect(data.samples.length - 1);
    const remaining = data.latest_sample_ts + 900 - Date.now() / 1000;
    if (data.state === 'current' && Number.isFinite(remaining)) { if (remaining <= 0) state('stale'); else expiry = setTimeout(() => state('stale'), remaining * 1000); }
  } });
  function refresh() {
    const id = el('device').value, hours = Number(el('hours').value);
    if (!id) { state('empty'); return; }
    loader.request({ id, hours, url: '/api/thermal-timeline?device_id=' + encodeURIComponent(id) + '&hours=' + hours });
  }
  const devices = createTimelineLoader({ readSession: session, intervalMs: 0, online: () => navigator.onLine,
    onState(name) { state(name); el('device').replaceChildren(placeholder(name === 'loading' ? 'Carregando dispositivos…' : 'Dispositivos indisponíveis')); el('device').disabled = true; },
    onData(data) {
      if (!Array.isArray(data.devices) || data.devices.length > 100 || !data.devices.every(device => typeof device.id === 'string' && device.id && typeof device.name === 'string')) throw Error('schema');
      el('device').replaceChildren();
      for (const device of data.devices) { const option = text('option', device.name || 'Dispositivo sem nome'); option.value = device.id; el('device').append(option); }
      el('source').textContent = 'Fonte: histórico local de telemetria. Janela média do firmware: não informada.' + (data.truncated ? ' Lista limitada aos 100 primeiros dispositivos; outros não foram carregados.' : '');
      el('device').disabled = !data.devices.length; if (data.devices.length) refresh(); else state('empty');
    } });
  el('cursor').addEventListener('input', () => inspect(Number(el('cursor').value)));
  el('focus').addEventListener('click', () => { focused = !focused; el('focus').setAttribute('aria-pressed', String(focused)); el('focus').textContent = focused ? 'Ver janela inteira' : 'Focar recorte observado'; if (model) drawLanes(Number(el('cursor').value)); });
  el('device').addEventListener('change', refresh); el('hours').addEventListener('change', refresh);
  el('refresh').addEventListener('click', () => el('device').value ? refresh() : devices.request({ url: '/api/thermal-timeline/devices' }));
  function sessionChanged() { loader.invalidate('auth'); devices.invalidate('auth'); devices.request({ url: '/api/thermal-timeline/devices' }); }
  window.addEventListener('storage', event => { if (event.key === SESSION_KEY || event.key === null) sessionChanged(); });
  window.addEventListener('offline', () => { loader.invalidate('offline'); devices.invalidate('offline'); });
  window.addEventListener('online', sessionChanged);
  window.addEventListener('pagehide', () => { loader.stop(); devices.stop(); clearTimeout(expiry); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  document.getElementById('thermal-app').dataset.mounted = 'true'; devices.request({ url: '/api/thermal-timeline/devices' });
}
