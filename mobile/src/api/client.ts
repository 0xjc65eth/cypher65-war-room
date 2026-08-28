import axios, { type AxiosError, type AxiosInstance } from 'axios';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';
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

const isDev = __DEV__;
const baseURL =
  (isDev
    ? Constants.expoConfig?.extra?.apiBaseUrlDev
    : Constants.expoConfig?.extra?.apiBaseUrl) || 'http://127.0.0.1:8765/api';

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

export { api };

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
  execute = false
) => {
  const payload: Record<string, unknown> = {
    command,
    parameters,
    dry_run: !execute,
  };
  if (confirmationToken) payload.confirmation_token = confirmationToken;
  const { data } = await api.post(`/devices/${deviceId}/command`, payload);
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
