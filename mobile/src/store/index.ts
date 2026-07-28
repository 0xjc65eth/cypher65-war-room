import { create } from 'zustand';
import type { BatteryMode, Device, FleetSummary, Alert, AuthState, BlockHuntData, MarketOffer } from '../types';

interface AppState {
  // Auth
  auth: AuthState;
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

export const useAppStore = create<AppState>((set) => ({
  auth: { token: null, isAuthenticated: false },
  setToken: (token) => set({ auth: { token, isAuthenticated: !!token } }),
  logout: () => set({ auth: { token: null, isAuthenticated: false } }),

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
