import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from 'react-native';
import { useRoute, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import { fetchDevice } from '../../api/client';
import { useCommands } from '../../hooks/useCommands';
import { MetricCard } from '../../components/MetricCard';
import { StatusBadge } from '../../components/StatusBadge';
import { CommandButton } from '../../components/CommandButton';
import { promptCriticalAction } from '../../services/biometrics';
import type { Capability, Device as DeviceType } from '../../types';
import type { FleetStackParamList } from '../../types/navigation';
import { theme } from '../../theme';

type Props = NativeStackScreenProps<FleetStackParamList, 'DeviceDetail'>;

export const DeviceDetailScreen = () => {
  const route = useRoute<Props['route']>();
  const navigation = useNavigation<NativeStackNavigationProp<FleetStackParamList>>();
  const { deviceId } = route.params;
  const [device, setDevice] = useState<DeviceType | null>(null);
  const [loading, setLoading] = useState(true);
  const {
    sendCommand,
    loading: commandLoading,
    phase: commandPhase,
    operationId,
    reconciling,
    error: commandError,
    auditRecorded,
  } = useCommands(deviceId);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchDevice(deviceId);
      setDevice(data.device);
    } catch (err) {
      Alert.alert('Error', (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCommand = async (capability: Capability) => {
    if (!device) return;

    let humanConfirmation: string | undefined;
    if (capability.requires_confirmation) {
      const biometric = await promptCriticalAction(capability.name);
      if (!biometric.success) {
        Alert.alert('Cancelled', biometric.error || 'Biometric check failed');
        return;
      }
      humanConfirmation = `CONFIRM ${capability.name.toUpperCase()}`;
    }

    const result = await sendCommand(capability.name, {}, humanConfirmation);
    if (result.success) {
      if (result.data?.dry_run) {
        Alert.alert('Dry-run complete', `${capability.name} was validated without execution`);
      } else {
        Alert.alert('Command acknowledged', 'ACK received. CYPHER65 is verifying physical state.');
      }
    } else {
      Alert.alert('Error', result.error || 'Command failed');
    }
  };

  if (loading || !device) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={theme.brand.DEFAULT} />
      </View>
    );
  }

  const t = device.current_telemetry;

  return (
    <ScrollView style={styles.container}>
      <TouchableOpacity onPress={() => navigation.goBack()}>
        <Text style={styles.back}>← Back</Text>
      </TouchableOpacity>

      <Text style={styles.heading}>{device.name}</Text>
      <View style={styles.statusRow}>
        <StatusBadge status={device.status} />
        <Text style={styles.ip}>{device.ip_address}</Text>
        <Text style={styles.model}>{device.model}</Text>
      </View>

      <Text style={styles.section}>Telemetry</Text>
      <View style={styles.grid}>
        <MetricCard title="Hashrate" value={t ? `${(t.hashrate / 1e12).toFixed(2)} TH/s` : '—'} />
        <MetricCard title="Temp" value={t ? `${t.temperature}°C` : '—'} />
        <MetricCard title="Power" value={t?.power ? `${t.power}W` : '—'} />
        <MetricCard title="Fan" value={t?.fan_speed ? `${t.fan_speed} rpm` : '—'} />
        <MetricCard title="Voltage" value={t?.voltage ? `${t.voltage}V` : '—'} />
        <MetricCard title="Freq" value={t?.frequency ? `${t.frequency} MHz` : '—'} />
        <MetricCard title="Accepted" value={t?.accepted_shares ?? '—'} />
        <MetricCard title="Rejected" value={t?.rejected_shares ?? '—'} />
        <MetricCard title="Best Diff" value={t?.best_difficulty || '—'} />
        <MetricCard title="Uptime" value={t?.uptime ? `${Math.floor(t.uptime / 3600)}h` : '—'} />
      </View>

      <Text style={styles.section}>Capabilities</Text>
      {commandLoading && <ActivityIndicator color={theme.brand.DEFAULT} style={styles.loader} />}
      <View style={styles.commands}>
        {device.capabilities?.map((cap) => (
          <CommandButton
            key={cap.name}
            capability={cap}
            onPress={handleCommand}
            disabled={commandLoading || reconciling}
          />
        ))}
      </View>

      {commandPhase !== 'idle' && (
        <View style={styles.lifecycle} accessible accessibilityLabel={`Command verification: ${commandPhase}`}>
          <View style={styles.lifecycleHeading}>
            <Text style={styles.lifecycleTitle}>Command verification</Text>
            {reconciling && <ActivityIndicator size="small" color={theme.brand.DEFAULT} />}
          </View>
          <Text style={styles.lifecycleState}>{commandPhase.toUpperCase()}</Text>
          <Text style={styles.lifecycleDetail}>
            {commandPhase === 'acknowledged' && 'Device ACK received; success is not yet verified.'}
            {commandPhase === 'offline' && 'Expected reboot outage observed.'}
            {commandPhase === 'reconnecting' && 'Device is online; checking fresh telemetry and uptime reset.'}
            {commandPhase === 'verified' && 'Offline transition, reconnection and uptime reset verified.'}
            {commandPhase === 'unknown' && (commandError || 'Final physical state is unknown.')}
            {commandPhase === 'failed' && (commandError || 'Observed state contradicts the command.')}
          </Text>
          {operationId && <Text style={styles.operationId}>Audit operation: {operationId}</Text>}
          {commandPhase === 'verified' && (
            <Text style={styles.operationId}>
              Audit Log: {auditRecorded ? 'RECORDED' : 'NOT CONFIRMED'}
            </Text>
          )}
        </View>
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.bg.deep,
    padding: 16,
  },
  center: {
    flex: 1,
    backgroundColor: theme.bg.deep,
    justifyContent: 'center',
    alignItems: 'center',
  },
  back: {
    color: theme.brand.DEFAULT,
    fontSize: 14,
    marginTop: 16,
    marginBottom: 8,
  },
  heading: {
    color: theme.text.primary,
    fontSize: 24,
    fontWeight: '700',
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 8,
    marginBottom: 16,
  },
  ip: {
    color: theme.text.tertiary,
    fontSize: 13,
  },
  model: {
    color: theme.text.secondary,
    fontSize: 13,
  },
  section: {
    color: theme.text.primary,
    fontSize: 18,
    fontWeight: '600',
    marginTop: 24,
    marginBottom: 12,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  commands: {
    marginBottom: 32,
  },
  loader: {
    marginVertical: 12,
  },
  lifecycle: {
    backgroundColor: theme.bg.surface,
    borderColor: theme.brand.DEFAULT,
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 32,
  },
  lifecycleHeading: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  lifecycleTitle: {
    color: theme.text.primary,
    fontSize: 16,
    fontWeight: '600',
  },
  lifecycleState: {
    color: theme.brand.DEFAULT,
    fontSize: 13,
    fontWeight: '700',
    marginTop: 8,
  },
  lifecycleDetail: {
    color: theme.text.tertiary,
    fontSize: 13,
    marginTop: 4,
  },
  operationId: {
    color: theme.text.secondary,
    fontSize: 11,
    marginTop: 8,
  },
});
