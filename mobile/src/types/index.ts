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

export interface MarketOffer {
  id: string;
  provider: string;
  hashrate: number;
  price_per_th_day: number;
  duration_days: number;
  fee_pct: number;
  algorithm: string;
  metrics?: {
    daily_cost_btc: number;
    daily_revenue_btc: number;
    expected_value_btc: number;
    roi_pct: number;
    score: number;
    risk_level: string;
  };
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
