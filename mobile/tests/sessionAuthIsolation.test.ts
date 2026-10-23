import { act, renderHook, waitFor } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';
import { useAuth } from '../src/hooks/useAuth';
import * as client from '../src/api/client';
import { useAppStore } from '../src/store';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(), setItemAsync: jest.fn(), deleteItemAsync: jest.fn(),
}));
jest.mock('../src/api/client', () => ({ login: jest.fn(), logoutRemote: jest.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('authentication intent isolation', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
    jest.mocked(SecureStore.setItemAsync).mockResolvedValue(undefined);
    jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue(undefined);
    jest.mocked(client.logoutRemote).mockResolvedValue({});
  });

  it('does not resurrect A when an old bootstrap finishes after B is selected', async () => {
    const read = deferred<string | null>();
    jest.mocked(SecureStore.getItemAsync).mockReturnValueOnce(read.promise);
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(SecureStore.getItemAsync).toHaveBeenCalled());
    await act(() => useAppStore.getState().setToken('fixture-B'));
    await act(async () => { read.resolve('fixture-A'); });
    expect(result.current.token).toBe('fixture-B');
  });

  it('rejects a login response arriving after logout', async () => {
    const reply = deferred<{ token: string }>();
    jest.mocked(client.login).mockReturnValueOnce(reply.promise);
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    let pending!: ReturnType<typeof result.current.login>;
    await act(() => { pending = result.current.login('fixture', 'synthetic-password'); });
    await act(async () => { await result.current.logout(); });
    await act(async () => { reply.resolve({ token: 'fixture-A' }); await pending; });
    expect(useAppStore.getState().auth.token).toBeNull();
    expect(SecureStore.setItemAsync).not.toHaveBeenCalledWith('cypher65_token', 'fixture-A');
  });

  it('invalidates local data before remote logout completes, preserving the old revocation token', async () => {
    const revocation = deferred<Record<string, never>>();
    jest.mocked(client.logoutRemote).mockReturnValueOnce(revocation.promise);
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => useAppStore.getState().setToken('fixture-A'));
    let pending!: ReturnType<typeof result.current.logout>;
    await act(() => { pending = result.current.logout(); });
    const tokenDuringRemoteWait = useAppStore.getState().auth.token;
    const revocationArguments = jest.mocked(client.logoutRemote).mock.calls[0];
    await act(() => useAppStore.getState().setToken('fixture-B'));
    await act(async () => { revocation.resolve({}); await pending; });
    expect(tokenDuringRemoteWait).toBeNull();
    expect(revocationArguments).toEqual(['fixture-A']);
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });

  it('exits the local session even if native credential deletion fails', async () => {
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => useAppStore.getState().setToken('fixture-A'));
    jest.mocked(SecureStore.deleteItemAsync).mockRejectedValueOnce(new Error('synthetic keystore fault'));
    await act(async () => { await result.current.logout().catch(() => undefined); });
    expect(useAppStore.getState().auth.token).toBeNull();
    expect(useAppStore.getState().authNotice).toMatch(/credencial salva/);
  });

  it('keeps login feedback across the keyed auth subtree remount', async () => {
    const response = deferred<{ token: string }>();
    jest.mocked(client.login).mockReturnValueOnce(response.promise);
    const first = await renderHook(() => useAuth());
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    let pending!: ReturnType<typeof first.result.current.login>;
    await act(() => { pending = first.result.current.login('fixture', 'synthetic'); });
    await first.unmount();
    const next = await renderHook(() => useAuth());
    expect(next.result.current.loading).toBe(true);
    await act(async () => { response.resolve({ token: 'fixture-A' }); await pending; });
    expect(next.result.current.loading).toBe(false);
    expect(next.result.current.isAuthenticated).toBe(true);
  });

  it('does not clear the newer login progress when the older login fails', async () => {
    let rejectA!: (error: Error) => void;
    const a = new Promise<{ token: string }>((_resolve, reject) => { rejectA = reject; });
    const b = deferred<{ token: string }>();
    jest.mocked(client.login).mockReturnValueOnce(a).mockReturnValueOnce(b.promise);
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    let first!: ReturnType<typeof result.current.login>;
    await act(() => { first = result.current.login('fixture-A', 'synthetic'); });
    let second!: ReturnType<typeof result.current.login>;
    await act(() => { second = result.current.login('fixture-B', 'synthetic'); });
    await act(async () => { rejectA(new Error('fixture late failure')); await first; });
    expect(result.current.loading).toBe(true);
    expect(result.current.authNotice).toBeNull();
    await act(async () => { b.resolve({ token: 'fixture-B' }); await second; });
    expect(result.current.loading).toBe(false);
    expect(result.current.token).toBe('fixture-B');
  });

  it('rejects an old biometric callback before native storage is read', async () => {
    const { result } = await renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const oldUnlock = result.current.unlock;
    jest.mocked(SecureStore.getItemAsync).mockClear();
    let unlocked!: Awaited<ReturnType<typeof oldUnlock>>;
    await act(async () => {
      useAppStore.getState().setToken('fixture-B');
      unlocked = await oldUnlock();
    });
    expect(unlocked.success).toBe(false);
    expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });
});
