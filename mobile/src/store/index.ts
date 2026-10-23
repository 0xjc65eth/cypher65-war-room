import { create } from 'zustand';
import type { BatteryMode, Device, FleetSummary, Alert, AuthState, BlockHuntData, MarketOffer } from '../types';

interface AppState {
  // Auth
  auth: AuthState;
  authRevision: number;
  authReady: boolean;
  authPending: boolean;
  authNotice: string | null;
  credentialRestoreAllowed: boolean;
  setToken: (token: string | null) => void;
  logout: () => void;

  // Battery / Polling
  batteryMode: BatteryMode;
  setBatteryMode: (mode: BatteryMode) => void;

  // Fleet
  devices: Device[];
  fleetSummary: FleetSummary | null;
  setDevices: (devices: Device[]) => void;
  setFleetSummary: (summary: FleetSummary) => void;
  updateDevice: (device: Device) => void;

  // Alerts
  alerts: Alert[];
  setAlerts: (alerts: Alert[]) => void;

  // Command Center
  snapshot: Record<string, unknown> | null;
  setSnapshot: (snapshot: Record<string, unknown>) => void;

  // Block Hunt
  blockHunt: BlockHuntData | null;
  setBlockHunt: (data: BlockHuntData) => void;

  // Market
  marketOffers: MarketOffer[];
  setMarketOffers: (offers: MarketOffer[]) => void;

  // AI Chat
  aiContext: Record<string, unknown>;
  setAiContext: (ctx: Record<string, unknown>) => void;

  // Settings
  pushCategories: Record<string, boolean>;
  setPushCategories: (categories: Record<string, boolean>) => void;
}

const emptyPrivateState = () => ({
  devices: [] as Device[],
  fleetSummary: null,
  alerts: [] as Alert[],
  snapshot: null,
  blockHunt: null,
  marketOffers: [] as MarketOffer[],
  aiContext: {},
  pushCategories: {
    temperature: true,
    hashrate_drop: true,
    worker_offline: true,
    device_offline: true,
    best_diff_bump: true,
    new_block: true,
  },
});

export const useAppStore = create<AppState>((set) => ({
  auth: { token: null, isAuthenticated: false },
  authRevision: 0,
  authReady: false,
  authPending: false,
  authNotice: null,
  credentialRestoreAllowed: true,
  // Rehydration with an identical credential is not a new identity.
  setToken: (token) => set((state) => state.auth.token === token
    ? { authReady: true }
    : {
      ...emptyPrivateState(),
      auth: { token, isAuthenticated: !!token },
      authRevision: state.authRevision + 1,
      authReady: true,
      authPending: false,
      authNotice: null,
      credentialRestoreAllowed: token ? true : state.credentialRestoreAllowed,
    }),
  // Even an already logged-out session must invalidate pending auth intents.
  logout: () => set((state) => ({
    ...emptyPrivateState(),
    auth: { token: null, isAuthenticated: false },
    authRevision: state.authRevision + 1,
    authReady: true,
    authPending: false,
    authNotice: null,
    credentialRestoreAllowed: false,
  })),

  batteryMode: 'balanced',
  setBatteryMode: (mode) => set({ batteryMode: mode }),

  devices: [],
  fleetSummary: null,
  setDevices: (devices) => set({ devices }),
  setFleetSummary: (fleetSummary) => set({ fleetSummary }),
  updateDevice: (device) =>
    set((state) => ({
      devices: state.devices.map((d) => (d.id === device.id ? device : d)),
    })),

  alerts: [],
  setAlerts: (alerts) => set({ alerts }),

  snapshot: null,
  setSnapshot: (snapshot) => set({ snapshot }),

  blockHunt: null,
  setBlockHunt: (blockHunt) => set({ blockHunt }),

  marketOffers: [],
  setMarketOffers: (marketOffers) => set({ marketOffers }),

  aiContext: {},
  setAiContext: (aiContext) => set({ aiContext }),

  pushCategories: {
    temperature: true,
    hashrate_drop: true,
    worker_offline: true,
    device_offline: true,
    best_diff_bump: true,
    new_block: true,
  },
  setPushCategories: (categories) => set({ pushCategories: categories }),
}));
