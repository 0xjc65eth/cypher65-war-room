import axios, { type AxiosError, type AxiosInstance } from 'axios';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';
import { resolveMobileEnvironment } from '../config/environment';
import type {
  Device,
  FleetSummary,
  BlockHuntData,
  ShareDistData,
  MarketOffer,
  MarketData,
  PushPreferences,
  RentalsData,
} from '../types';

const mobileEnvironment = resolveMobileEnvironment(Constants.expoConfig?.extra, __DEV__);
const baseURL = mobileEnvironment.apiBaseUrl;

const api: AxiosInstance = axios.create({
  baseURL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use(async (config) => {
  const token = await SecureStore.getItemAsync('cypher65_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      SecureStore.deleteItemAsync('cypher65_token').catch(() => {});
    }
    return Promise.reject(error);
  }
);

export { api, mobileEnvironment };

export class AiOperatorResponseError extends Error {
  constructor(
    message: string,
    readonly code: 'backend_error' | 'invalid_response' | 'incomplete_response'
  ) {
    super(message);
    this.name = 'AiOperatorResponseError';
  }
}

type AiOperatorEvent =
  | { type: 'text'; content: string }
  | { type: 'action'; action: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'done' };

const AI_RESPONSE_MAX_BYTES = 512_000;
const AI_RESPONSE_MAX_EVENTS = 4_096;

const validateAiOperatorEvent = (value: unknown): AiOperatorEvent => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new AiOperatorResponseError('AI Operator returned an invalid response.', 'invalid_response');
  }
  const event = value as Record<string, unknown>;
  switch (event.type) {
    case 'text':
      if (typeof event.content === 'string') return { type: 'text', content: event.content };
      break;
    case 'action':
      if (event.action && typeof event.action === 'object' && !Array.isArray(event.action)) {
        return { type: 'action', action: event.action as Record<string, unknown> };
      }
      break;
    case 'error':
      if (typeof event.message === 'string') return { type: 'error', message: event.message };
      break;
    case 'done':
      return { type: 'done' };
  }
  throw new AiOperatorResponseError('AI Operator returned an invalid response.', 'invalid_response');
};

/**
 * Parse the backend's complete SSE response. React Native's axios adapter
 * buffers the response body, so the mobile client validates every event before
 * presenting any assistant text as real.
 */
export const parseAiOperatorResponse = (payload: unknown): string => {
  if (typeof payload !== 'string') {
    throw new AiOperatorResponseError('AI Operator returned an invalid response.', 'invalid_response');
  }
  if (payload.length > AI_RESPONSE_MAX_BYTES) {
    throw new AiOperatorResponseError('AI Operator response exceeded the safe limit.', 'invalid_response');
  }

  const events: AiOperatorEvent[] = [];
  let doneSeen = false;
  for (const rawLine of payload.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.startsWith('data:')) continue;

    const encoded = line.slice(5).trim();
    if (!encoded) continue;

    try {
      if (doneSeen || events.length >= AI_RESPONSE_MAX_EVENTS) {
        throw new AiOperatorResponseError('AI Operator returned an invalid response.', 'invalid_response');
      }
      const event = validateAiOperatorEvent(JSON.parse(encoded));
      events.push(event);
      doneSeen = event.type === 'done';
    } catch (error) {
      if (error instanceof AiOperatorResponseError) throw error;
      throw new AiOperatorResponseError('AI Operator returned an invalid response.', 'invalid_response');
    }
  }

  const backendError = events.find((event) => event.type === 'error');
  if (backendError?.type === 'error') {
    throw new AiOperatorResponseError('AI Operator is unavailable on this server.', 'backend_error');
  }
  if (!events.some((event) => event.type === 'done')) {
    throw new AiOperatorResponseError('AI Operator response was incomplete.', 'incomplete_response');
  }

  const text = events
    .filter((event): event is Extract<AiOperatorEvent, { type: 'text' }> => event.type === 'text')
    .map((event) => (typeof event.content === 'string' ? event.content : ''))
    .join('')
    .trim();

  if (!text) {
    throw new AiOperatorResponseError('AI Operator returned no answer.', 'invalid_response');
  }
  return text;
};

export const queryAiOperator = async (query: string): Promise<string> => {
  const normalized = query.trim();
  if (!normalized) {
    throw new AiOperatorResponseError('A question is required.', 'invalid_response');
  }

  const { data } = await api.post(
    '/ai/query',
    { query: normalized },
    {
      headers: { Accept: 'text/event-stream' },
      responseType: 'text',
      timeout: 35_000,
    }
  );
  return parseAiOperatorResponse(data);
};

// ── Snapshot & Command Center ───────────────────────────────────────────────
export const fetchSnapshot = async () => {
  const { data } = await api.get('/snapshot');
  return data;
};

export const fetchAlerts = async () => {
  const { data } = await api.get('/alerts');
  return data;
};

// ── Fleet ───────────────────────────────────────────────────────────────────
export const fetchDevices = async (): Promise<{ devices: Device[]; summary: FleetSummary }> => {
  const { data } = await api.get('/devices');
  return data;
};

export const fetchFleetSummary = async (): Promise<FleetSummary> => {
  const { data } = await api.get('/fleet/summary');
  return data;
};

export const fetchDevice = async (deviceId: string): Promise<{ success: boolean; device: Device }> => {
  const { data } = await api.get(`/devices/${deviceId}`);
  return data;
};

export const refreshDevice = async (deviceId: string): Promise<{ success: boolean; device: Device }> => {
  const { data } = await api.post(`/devices/${deviceId}/refresh`, {});
  return data;
};

export const sendDeviceCommand = async (
  deviceId: string,
  command: string,
  parameters: Record<string, unknown> = {},
  confirmationToken?: string,
  execute = false,
  idempotencyKey?: string
) => {
  const payload: Record<string, unknown> = {
    command,
    parameters,
    dry_run: !execute,
  };
  if (confirmationToken) payload.confirmation_token = confirmationToken;
  const { data } = await api.post(`/devices/${deviceId}/command`, payload, {
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
  });
  return data;
};

export const requestDeviceCommandConfirmation = async (
  deviceId: string,
  command: string,
  parameters: Record<string, unknown>,
  confirmation: string
) => {
  const { data } = await api.post(`/devices/${deviceId}/command/confirmation`, {
    command,
    parameters,
    confirmation,
  });
  return data;
};

export const fetchCommandHistory = async (deviceId: string) => {
  const { data } = await api.get(`/devices/${deviceId}/commands`);
  return data;
};

export const fetchDeviceCommandStatus = async (deviceId: string, operationId: string) => {
  const { data } = await api.get(`/devices/${deviceId}/commands/${operationId}`);
  return data;
};

export const fetchDeviceDiagnostics = async (deviceId: string) => {
  const { data } = await api.get(`/devices/${deviceId}/diagnostics`);
  return data;
};

export const fetchDeviceTimeline = async (deviceId: string) => {
  const { data } = await api.get(`/devices/${deviceId}/timeline`);
  return data;
};

export const createMaintenanceRecord = async (
  deviceId: string,
  record: { type: string; notes: string; performed_by: string }
) => {
  const { data } = await api.post(`/devices/${deviceId}/maintenance`, record);
  return data;
};

// ── Block Hunt ─────────────────────────────────────────────────────────────
export const fetchBlockHunt = async (): Promise<BlockHuntData> => {
  const { data } = await api.get('/block-hunt');
  return data;
};

export const fetchBestDiffHistory = async () => {
  const { data } = await api.get('/best-diff-history');
  return data;
};

// ── Live Mining → Probability (P0-1 parity) ────────────────────────────────
export const fetchShareDist = async (range = '1h'): Promise<ShareDistData> => {
  const { data } = await api.get('/chart-data', { params: { chart: 'share_dist', range } });
  return data;
};

// ── Market ──────────────────────────────────────────────────────────────────
// P0-4 parity: the server nests everything under `market_data` ({offers,
// best_price, updated_at, provider_count, affiliate}) — unwrap it so the
// screen gets offers AND the one-click affiliate link in one payload
// (same shape the web dashboard reads from the snapshot).
export const fetchHashrateMarket = async (): Promise<MarketData> => {
  const { data } = await api.get('/hashrate-market');
  return data?.market_data ?? { offers: data?.offers ?? [] };
};

export const fetchMarketHistory = async (limit = 100) => {
  const { data } = await api.get('/hashrate-market/history', { params: { limit } });
  return data;
};

export const compareOffers = async (providers?: string[]): Promise<{ offers: MarketOffer[] }> => {
  const params: Record<string, string> = {};
  if (providers && providers.length > 0) {
    params.providers = providers.join(',');
  }
  const { data } = await api.get('/opportunities/compare', { params });
  return data;
};

// ── Rentals (Rentals Hub) ────────────────────────────────────────────────
export const fetchRentals = async (): Promise<RentalsData> => {
  const { data } = await api.get('/rentals');
  return data;
};

// ── Push Notifications ───────────────────────────────────────────────────
export const registerPushToken = async (prefs: PushPreferences) => {
  const { data } = await api.post('/push/register', prefs);
  return data;
};

// ── Authentication ───────────────────────────────────────────────────────────
export const login = async (credentials: { username: string; password: string }) => {
  const { data } = await api.post('/auth/login', credentials);
  return data as { token: string };
};

export const logoutRemote = async () => {
  const { data } = await api.post('/auth/logout', {});
  return data;
};
