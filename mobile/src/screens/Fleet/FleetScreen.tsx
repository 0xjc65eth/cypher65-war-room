import { useMemo, useState } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, RefreshControl, TextInput } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { DeviceListItem } from '../../components/DeviceListItem';
import { useFleet } from '../../hooks/useFleet';
import type { Device, DeviceStatus } from '../../types';
import type { FleetStackParamList } from '../../types/navigation';
import { theme } from '../../theme';

type Filter = 'ALL' | DeviceStatus;

export const FleetScreen = () => {
  const { devices, loading, error, load } = useFleet();
  const navigation = useNavigation<NativeStackNavigationProp<FleetStackParamList>>();
  const [filter, setFilter] = useState<Filter>('ALL');
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    return devices.filter((device) => {
      const matchesFilter = filter === 'ALL' || device.status === filter;
      const matchesSearch =
        search.trim().length === 0 ||
        device.name.toLowerCase().includes(search.toLowerCase()) ||
        device.id.toLowerCase().includes(search.toLowerCase()) ||
        device.ip_address.includes(search);
      return matchesFilter && matchesSearch;
    });
  }, [devices, filter, search]);

  const filters: Filter[] = ['ALL', 'ONLINE', 'OFFLINE', 'WARNING', 'CRITICAL'];

  const handlePress = (device: Device) => {
    navigation.navigate('DeviceDetail', { deviceId: device.id });
  };

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Fleet</Text>

      <TextInput
        style={styles.search}
        placeholder="Search by name, id or ip"
        placeholderTextColor={theme.text.secondary}
        value={search}
        onChangeText={setSearch}
      />

      <View style={styles.filters}>
        {filters.map((f) => (
          <TouchableOpacity
            key={f}
            style={[styles.filterChip, filter === f && styles.filterChipActive]}
            onPress={() => setFilter(f)}
          >
            <Text style={[styles.filterText, filter === f && styles.filterTextActive]}>{f}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {error && <Text style={styles.error}>{error}</Text>}

      <FlatList
        data={filtered}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <DeviceListItem device={item} onPress={handlePress} />}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.brand.DEFAULT} />}
        ListEmptyComponent={<Text style={styles.empty}>No devices found</Text>}
      />
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
    marginBottom: 12,
  },
  search: {
    backgroundColor: theme.bg.surface,
    color: theme.text.primary,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 12,
  },
  filters: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 12,
  },
  filterChip: {
    backgroundColor: theme.bg.elevated,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  filterChipActive: {
    backgroundColor: theme.bg.brand,
  },
  filterText: {
    color: theme.text.tertiary,
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  filterTextActive: {
    color: theme.text.onBrand,
  },
  error: {
    color: theme.red.DEFAULT,
    marginBottom: 8,
  },
  empty: {
    color: theme.text.secondary,
    textAlign: 'center',
    marginTop: 24,
    fontStyle: 'italic',
  },
});
