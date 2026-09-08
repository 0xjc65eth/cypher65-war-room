import { act, renderHook, waitFor } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';
import { useAuth } from '../src/hooks/useAuth';
import * as client from '../src/api/client';
import { useAppStore } from '../src/store';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

jest.mock('../src/api/client', () => ({
  login: jest.fn(),
  logoutRemote: jest.fn(),
}));

describe('useAuth', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState({ auth: { token: null, isAuthenticated: false } });
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(null);
  });

  it('hydrates a stored token on mount', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue('stored-token');
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.token).toBe('stored-token');
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('treats a SecureStore read failure as logged out', async () => {
    (SecureStore.getItemAsync as jest.Mock).mockRejectedValue(new Error('keystore'));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.token).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('persists a successful login and returns the API error message on failure', async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    (client.login as jest.Mock).mockResolvedValue({ token: 'new-token' });
    let ok: { success: boolean; error?: string } | undefined;
    await act(async () => {
      ok = await result.current.login('op', 'secret');
    });
    expect(ok).toEqual({ success: true });
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith('cypher65_token', 'new-token');
    expect(result.current.token).toBe('new-token');

    (client.login as jest.Mock).mockRejectedValue(new Error('invalid credentials'));
    let fail: { success: boolean; error?: string } | undefined;
    await act(async () => {
      fail = await result.current.login('op', 'wrong');
    });
    expect(fail).toEqual({ success: false, error: 'invalid credentials' });
  });

  it('clears the token even when remote logout fails', async () => {
    useAppStore.getState().setToken('live');
    (client.logoutRemote as jest.Mock).mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.logout();
    });
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('cypher65_token');
    expect(result.current.token).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });
});
