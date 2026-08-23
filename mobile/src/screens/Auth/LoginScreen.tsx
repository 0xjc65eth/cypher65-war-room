import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { authenticateWithBiometrics, isBiometricAvailable } from '../../services/biometrics';
import { useAuth } from '../../hooks/useAuth';
import { theme } from '../../theme';

export const LoginScreen = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const { login, loading, setToken } = useAuth();

  React.useEffect(() => {
    isBiometricAvailable().then(setBiometricAvailable).catch(() => setBiometricAvailable(false));
  }, []);

  const validate = () => {
    if (!username.trim()) return 'Username is required';
    if (!password.trim()) return 'Password is required';
    if (password.length < 6) return 'Password must be at least 6 characters';
    return null;
  };

  const handleLogin = async () => {
    const error = validate();
    if (error) {
      Alert.alert('Invalid input', error);
      return;
    }

    const result = await login(username, password);
    if (!result.success) {
      Alert.alert('Login failed', result.error || 'Invalid credentials');
    }
  };

  const handleBiometric = async () => {
    const auth = await authenticateWithBiometrics('Unlock CYPHER65 with biometrics');
    if (!auth.success) {
      Alert.alert('Unlock failed', auth.error || 'Biometric check failed');
      return;
    }

    // Attempt to restore a previously saved session. If a token is cached,
    // reuse it; otherwise biometric unlock alone is not enough to authenticate.
    // In a production app, the token should be encrypted with a key protected
    // by the biometric result (e.g., via Keychain/Keystore).
    const token = await SecureStore.getItemAsync('cypher65_token');
    if (token) {
      setToken(token);
    } else {
      Alert.alert('No saved session', 'Please log in with your credentials first.');
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.heading}>CYPHER65</Text>
        <Text style={styles.subheading}>War Room</Text>

        <TextInput
          style={styles.input}
          placeholder="Username"
          placeholderTextColor={theme.text.secondary}
          autoCapitalize="none"
          autoCorrect={false}
          value={username}
          onChangeText={setUsername}
          editable={!loading}
        />

        <View style={styles.passwordContainer}>
          <TextInput
            style={styles.passwordInput}
            placeholder="Password"
            placeholderTextColor={theme.text.secondary}
            secureTextEntry={!showPassword}
            value={password}
            onChangeText={setPassword}
            editable={!loading}
          />
          <TouchableOpacity onPress={() => setShowPassword(!showPassword)}>
            <Text style={styles.toggle}>{showPassword ? 'Hide' : 'Show'}</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={styles.button} onPress={handleLogin} disabled={loading}>
          {loading ? <ActivityIndicator color={theme.text.onBrand} /> : <Text style={styles.buttonText}>Login</Text>}
        </TouchableOpacity>

        {biometricAvailable && (
          <TouchableOpacity style={styles.biometricButton} onPress={handleBiometric} disabled={loading}>
            <Text style={styles.biometricText}>🔐 Unlock with Biometrics</Text>
          </TouchableOpacity>
        )}

        <Text style={styles.hint}>
          Remote logout can be triggered from the Settings tab after login.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  container: {
    flex: 1,
    backgroundColor: theme.bg.deep,
    justifyContent: 'center',
    padding: 24,
  },
  heading: {
    color: theme.text.primary,
    fontSize: 32,
    fontWeight: '700',
    textAlign: 'center',
  },
  subheading: {
    color: theme.brand.DEFAULT,
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
    marginBottom: 32,
  },
  input: {
    backgroundColor: theme.bg.surface,
    color: theme.text.primary,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginBottom: 12,
    fontSize: 15,
  },
  passwordContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    paddingLeft: 16,
    marginBottom: 12,
  },
  passwordInput: {
    flex: 1,
    color: theme.text.primary,
    paddingVertical: 14,
    fontSize: 15,
  },
  toggle: {
    color: theme.brand.DEFAULT,
    paddingHorizontal: 12,
    fontSize: 14,
  },
  button: {
    backgroundColor: theme.bg.brand,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonText: {
    color: theme.text.onBrand,
    fontSize: 16,
    fontWeight: '600',
  },
  biometricButton: {
    marginTop: 16,
    alignItems: 'center',
    padding: 8,
  },
  biometricText: {
    color: theme.text.tertiary,
    fontSize: 14,
  },
  hint: {
    color: theme.text.secondary,
    fontSize: 12,
    textAlign: 'center',
    marginTop: 24,
  },
});
