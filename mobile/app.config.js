const base = {
  name: 'CYPHER65 War Room',
  slug: 'cypher65-war-room',
  version: '1.0.0',
  orientation: 'default',
  icon: './assets/icon.png',
  assetBundlePatterns: ['**/*'],
  ios: {
    supportsTablet: true,
    bundleIdentifier: 'com.cypher65.warroom',
    buildNumber: '1',
    infoPlist: {
      NSAppTransportSecurity: { NSAllowsArbitraryLoads: false },
      NSFaceIDUsageDescription:
        'Use Face ID to unlock CYPHER65 and confirm sensitive operator actions.',
      UIBackgroundModes: ['remote-notification'],
    },
  },
  android: {
    package: 'com.cypher65.warroom',
    permissions: [
      'android.permission.USE_BIOMETRIC',
      'android.permission.USE_FINGERPRINT',
      'android.permission.RECEIVE_BOOT_COMPLETED',
      'android.permission.ACCESS_NETWORK_STATE',
    ],
  },
  web: { favicon: './assets/favicon.png' },
  plugins: [
    ['expo-notifications'],
    ['expo-secure-store'],
    ['expo-local-authentication'],
    'expo-status-bar',
    [
      'expo-splash-screen',
      {
        image: './assets/splash.png',
        resizeMode: 'contain',
        backgroundColor: 'black',
      },
    ],
  ],
};

const { ENVIRONMENTS, validateApiBaseUrl } = require('./config/api-url');
const DEFAULT_URLS = {
  development: 'http://127.0.0.1:8765/api',
  testing: 'http://127.0.0.1:8765/api',
  production: 'https://cypher65-war-room.onrender.com/api',
};

module.exports = () => {
  const environment = process.env.CYPHER65_APP_ENV || 'development';
  if (!ENVIRONMENTS.has(environment)) {
    throw new Error(`Unsupported CYPHER65_APP_ENV: ${environment}`);
  }
  const apiBaseUrl = validateApiBaseUrl(
    environment,
    process.env.CYPHER65_API_BASE_URL || DEFAULT_URLS[environment]
  );
  return {
    ...base,
    extra: { environment, apiBaseUrl },
  };
};
