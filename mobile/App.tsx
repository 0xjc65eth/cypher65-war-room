import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Text, StyleSheet } from 'react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CommandScreen } from './src/screens/Command/CommandScreen';
import { FleetScreen } from './src/screens/Fleet/FleetScreen';
import { DeviceDetailScreen } from './src/screens/Fleet/DeviceDetailScreen';
import { BlockHuntScreen } from './src/screens/Block/BlockHuntScreen';
import { MarketScreen } from './src/screens/Market/MarketScreen';
import { AiOperatorScreen } from './src/screens/AI/AiOperatorScreen';
import { LoginScreen } from './src/screens/Auth/LoginScreen';
import { SettingsScreen } from './src/screens/Settings/SettingsScreen';
import { ErrorBoundary } from './src/components/ErrorBoundary';
import { configureNotificationHandler, registerForPushNotifications } from './src/services/push';
import { useAuth } from './src/hooks/useAuth';

const queryClient = new QueryClient();
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
  AI: '✦',
};

const AppContent = () => {
  const { isAuthenticated, loading } = useAuth();

  useEffect(() => {
    configureNotificationHandler();
    registerForPushNotifications().catch(() => {});
  }, []);

  if (loading) {
    return <Text style={styles.loading}>Loading…</Text>;
  }

  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: styles.tabBar,
        tabBarActiveTintColor: '#38bdf8',
        tabBarInactiveTintColor: '#64748b',
        tabBarLabelStyle: styles.tabLabel,
        tabBarIcon: () => <Text style={styles.tabIcon}>{TabIcon[route.name] || '•'}</Text>,
      })}
    >
      <Tab.Screen name="Command" component={CommandScreen} />
      <Tab.Screen name="Fleet" component={FleetStack} />
      <Tab.Screen name="Block" component={BlockHuntScreen} />
      <Tab.Screen name="Market" component={MarketScreen} />
      <Tab.Screen name="AI" component={AiOperatorScreen} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>
  );
};

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <NavigationContainer>
          <AppContent />
          <StatusBar style="light" />
        </NavigationContainer>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    textAlign: 'center',
    textAlignVertical: 'center',
    color: '#f8fafc',
    backgroundColor: '#0b0f19',
  },
  tabBar: {
    backgroundColor: '#111827',
    borderTopColor: '#1f2937',
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
