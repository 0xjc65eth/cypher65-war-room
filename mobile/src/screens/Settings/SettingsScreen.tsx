import { View, Text, StyleSheet, Switch, TouchableOpacity } from 'react-native';
import { useAppStore } from '../../store';
import { useAuth } from '../../hooks/useAuth';
import type { BatteryMode } from '../../types';
import { theme } from '../../theme';

const BATTERY_MODES: { key: BatteryMode; label: string }[] = [
  { key: 'max_battery', label: 'Max Battery' },
  { key: 'balanced', label: 'Balanced' },
  { key: 'real_time', label: 'Real-time' },
];

const CATEGORIES = [
  { key: 'temperature', label: 'Temperature Alerts' },
  { key: 'hashrate_drop', label: 'Hashrate Drop' },
  { key: 'worker_offline', label: 'Worker Offline' },
  { key: 'device_offline', label: 'Device Offline' },
  { key: 'best_diff_bump', label: 'Best Difficulty' },
  { key: 'new_block', label: 'New Block' },
];

/**
 * Settings screen.
 *
 * Push notification categories and battery mode are persisted in the local
 * Zustand store. Once the backend exposes endpoints for user preferences, the
 * toggle handlers below should be wired to sync with the server.
 */
export const SettingsScreen = () => {
  const { logout } = useAuth();
  const batteryMode = useAppStore((state) => state.batteryMode);
  const setBatteryMode = useAppStore((state) => state.setBatteryMode);
  const pushCategories = useAppStore((state) => state.pushCategories);
  const setPushCategories = useAppStore((state) => state.setPushCategories);

  const toggleCategory = (key: string, value: boolean) => {
    setPushCategories({ ...pushCategories, [key]: value });
    // TODO: POST updated preferences to backend when /api/settings is available.
  };

  const handleBatteryModeChange = (mode: BatteryMode) => {
    setBatteryMode(mode);
    // TODO: POST battery_mode to backend when /api/settings is available.
  };

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Settings</Text>

      <Text style={styles.section}>Battery Mode</Text>
      {BATTERY_MODES.map((mode) => (
        <TouchableOpacity
          key={mode.key}
          style={[styles.modeRow, batteryMode === mode.key && styles.modeRowActive]}
          onPress={() => handleBatteryModeChange(mode.key)}
        >
          <Text style={styles.modeText}>{mode.label}</Text>
          {batteryMode === mode.key && <Text style={styles.check}>●</Text>}
        </TouchableOpacity>
      ))}

      <Text style={styles.section}>Push Notifications</Text>
      {CATEGORIES.map((cat) => (
        <View key={cat.key} style={styles.row}>
          <Text style={styles.label}>{cat.label}</Text>
          <Switch
            value={!!pushCategories[cat.key]}
            onValueChange={(value) => toggleCategory(cat.key, value)}
            thumbColor={theme.bg.brand}
            trackColor={{ false: theme.border.strong, true: theme.bg.brandDeep }}
          />
        </View>
      ))}

      <TouchableOpacity style={styles.logout} onPress={logout}>
        <Text style={styles.logoutText}>Logout</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg.deep,
    padding: 16,
  },
  heading: {
    color: theme.text.primary,
    fontSize: 24,
    fontWeight: '700',
    marginTop: 16,
  },
  section: {
    color: theme.text.tertiary,
    fontSize: 13,
    textTransform: 'uppercase',
    marginTop: 24,
    marginBottom: 12,
  },
  modeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 14,
    marginBottom: 8,
  },
  modeRowActive: {
    borderColor: theme.bg.brand,
    borderWidth: 1,
  },
  modeText: {
    color: theme.text.primary,
    fontSize: 15,
  },
  check: {
    color: theme.bg.brand,
    fontSize: 18,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 14,
    marginBottom: 8,
  },
  label: {
    color: theme.text.faint,
    fontSize: 14,
  },
  logout: {
    marginTop: 32,
    backgroundColor: theme.bg.red,
    borderRadius: 8,
    padding: 14,
    alignItems: 'center',
  },
  logoutText: {
    color: theme.red.DEFAULT,
    fontSize: 16,
    fontWeight: '600',
  },
});
