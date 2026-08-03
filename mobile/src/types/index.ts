export type DeviceStatus = 'ONLINE' | 'OFFLINE' | 'WARNING' | 'CRITICAL';

export interface Telemetry {
  hashrate: number;
  temperature: number;
  fan_speed?: number;
  power?: number;
  voltage?: number;
  frequency?: number;
  accepted_shares?: number;
  rejected_shares?: number;
  stale_shares?: number;
  best_difficulty?: string;
  uptime?: number;
  pool?: string;
  worker?: string;
  source: string;
  timestamp: number;
  freshness: number;
}

export interface Capability {
  name: string;
  supported: boolean;
  requires_confirmation: boolean;
  risk_level: 'low' | 'medium' | 'high';
}

export interface Device {
  id: string;
  name: string;
  model: string;
  manufacturer: string;
  ip_address: string;
  status: DeviceStatus;
  last_seen: number;
  current_telemetry: Telemetry | null;
  health_score?: number;
  active_issues?: string[];
  capabilities?: Capability[];
}

export interface FleetSummary {
  total: number;
  status_counts: Record<DeviceStatus | 'UNKNOWN', number>;
  devices_with_recent_telemetry: number;
  total_hashrate: number;
}

export interface Alert {
  id: number;
  ts: number;
  severity: 'CRIT' | 'WARN' | 'GOLD' | 'SUCCESS' | 'INFO';
  category: string;
  message: string;
}

export interface BlockHuntData {
  network_hashrate: number;
  network_difficulty: number;
  block_height: number;
  user_hashrate: number;
  best_difficulty: string;
  probability_1h: number;
  probability_24h: number;
  probability_7d: number;
  expected_time: string;
  user_vs_network_pct: number;
}

export interface ShareDistDataset {
  label: string;
  data: number[];
  fill: boolean;
  borderColor: string;
  backgroundColor: string;
  tension: number;
}

// /api/chart-data?chart=share_dist — Live→Probability parity (P0-1).
// `target_diff` is the network difficulty and `target_bucket` its histogram
// bucket, both null when unavailable — mirrors the web dashboard overlay.
export interface ShareDistData {
  labels: string[];
  count: number | null;
  target_diff: number | null;
  target_bucket: number | null;
  datasets: ShareDistDataset[];
}

export interface MarketOffer {
  id: string;
  provider: string;
  source?: string;
  hashrate: number;
  price_per_th_day: number;
  duration_days: number;
  fee_pct: number;
  algorithm: string;
  estimated?: boolean;
  metrics?: {
    daily_cost_btc: number;
    daily_revenue_btc: number;
    expected_value_btc: number;
    roi_pct: number;
    score: number;
    risk_level: string;
  };
}

// P0-3/P0-4 — one-click affiliate link resolved by the backend
// (market_data.affiliate, same shape the web dashboard renders as the
// ⚡ BUY button on the matching offer card). Honest: only present when the
// operator configured HASH_MARKET_AFFILIATE_URLS — never fabricated.
export interface MarketAffiliate {
  provider: string;
  url: string;
  price_per_th_day?: number;
}

export interface MarketData {
  offers: MarketOffer[];
  best_price?: string | null;
  updated_at?: number;
  provider_count?: number;
  affiliate?: MarketAffiliate | null;
}

export interface PushPreferences {
  token: string;
  platform: 'ios' | 'android';
  categories: Record<string, boolean>;
}

export type BatteryMode = 'max_battery' | 'balanced' | 'real_time';

export interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
}
