import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Text, View, StyleSheet } from 'react-native';
import { CommandScreen } from './src/screens/Command/CommandScreen';
import { FleetScreen } from './src/screens/Fleet/FleetScreen';
import { DeviceDetailScreen } from './src/screens/Fleet/DeviceDetailScreen';
import { BlockHuntScreen } from './src/screens/Block/BlockHuntScreen';
import { MarketScreen } from './src/screens/Market/MarketScreen';
import { RentalsScreen } from './src/screens/Rentals/RentalsScreen';
import { AiOperatorScreen } from './src/screens/AI/AiOperatorScreen';
import { LoginScreen } from './src/screens/Auth/LoginScreen';
import { SettingsScreen } from './src/screens/Settings/SettingsScreen';
import { ErrorBoundary } from './src/components/ErrorBoundary';
import { theme } from './src/theme';
import { configureNotificationHandler, registerForPushNotifications } from './src/services/push';
import { useAuth } from './src/hooks/useAuth';
import { useAppStore } from './src/store';
import { captureSession } from './src/services/sessionLease';
import { SessionBoundary } from './src/components/SessionBoundary';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function FleetStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="FleetList" component={FleetScreen} />
      <Stack.Screen name="DeviceDetail" component={DeviceDetailScreen} />
    </Stack.Navigator>
  );
}

const TabIcon: Record<string, string> = {
  Command: '⌘',
  Fleet: '⛏',
  Block: '▣',
  Market: '$',
  Rentals: '⟁',
  AI: '✦',
};

const AppContent = () => {
  const { isAuthenticated, loading, authPending } = useAuth();

  useEffect(() => {
    configureNotificationHandler();
    if (isAuthenticated) void registerForPushNotifications(captureSession()).catch(() => {});
  }, [isAuthenticated]);

  if (loading) {
    return (
      <View style={styles.loading} accessibilityRole="progressbar" accessibilityLabel={authPending ? 'Entrando' : 'Restaurando sessão'}>
        <Text style={styles.loadingText}>{authPending ? 'Entrando…' : 'Restaurando sessão…'}</Text>
        <View style={styles.skeleton} />
        <View style={styles.skeleton} />
      </View>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: styles.tabBar,
        tabBarActiveTintColor: theme.brand.DEFAULT,
        tabBarInactiveTintColor: theme.text.secondary,
        tabBarLabelStyle: styles.tabLabel,
        tabBarIcon: () => <Text style={styles.tabIcon}>{TabIcon[route.name] || '•'}</Text>,
      })}
    >
      <Tab.Screen name="Command" component={CommandScreen} />
      <Tab.Screen name="Fleet" component={FleetStack} />
      <Tab.Screen name="Block" component={BlockHuntScreen} />
      <Tab.Screen name="Market" component={MarketScreen} />
      <Tab.Screen name="Rentals" component={RentalsScreen} />
      <Tab.Screen name="AI" component={AiOperatorScreen} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>
  );
};

export default function App() {
  const revision = useAppStore((state) => state.authRevision);
  return (
    <ErrorBoundary>
      <SessionBoundary key={revision}>
        <NavigationContainer>
          <AppContent />
          <StatusBar style="light" />
        </NavigationContainer>
      </SessionBoundary>
    </ErrorBoundary>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
    backgroundColor: theme.bg.deep,
  },
  loadingText: { color: theme.text.primary, textAlign: 'center', marginBottom: 16 },
  // Static skeleton: auth transitions remove private content immediately.
  // No motion or delayed exit, including when reduced motion is requested.
  skeleton: { height: 48, marginBottom: 12, borderRadius: 8, backgroundColor: theme.bg.surface },
  tabBar: {
    backgroundColor: theme.bg.surface,
    borderTopColor: theme.border.subtle,
    borderTopWidth: 1,
    paddingTop: 6,
    paddingBottom: 8,
    height: 60,
  },
  tabLabel: {
    fontSize: 11,
    fontWeight: '600',
  },
  tabIcon: {
    fontSize: 18,
    marginBottom: 2,
  },
});
