import { useEffect, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import { useAppStore } from '../store';
import { login as apiLogin, logoutRemote } from '../api/client';

const TOKEN_KEY = 'cypher65_token';

export const useAuth = () => {
  const { auth, setToken, logout: logoutStore } = useAppStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadToken = async () => {
      try {
        const token = await SecureStore.getItemAsync(TOKEN_KEY);
        setToken(token ?? null);
      } catch {
        setToken(null);
      } finally {
        setLoading(false);
      }
    };
    loadToken();
  }, [setToken]);

  const login = async (username: string, password: string) => {
    try {
      const response = await apiLogin({ username, password });
      await SecureStore.setItemAsync(TOKEN_KEY, response.token);
      setToken(response.token);
      return { success: true };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  };

  const logout = async () => {
    try {
      await logoutRemote();
    } catch {
      // ignore
    }
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    logoutStore();
  };

  return { ...auth, loading, login, logout, setToken };
};
