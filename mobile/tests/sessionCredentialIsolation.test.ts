import * as SecureStore from 'expo-secure-store';
import { useAppStore } from '../src/store';
import { beginAuthentication, completeLogin, endSession, hydrateSession, unlockSavedSession } from '../src/services/authSession';
import { captureSession, SessionChangedError } from '../src/services/sessionLease';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(), setItemAsync: jest.fn(), deleteItemAsync: jest.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('serialized native credentials', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
    jest.mocked(SecureStore.setItemAsync).mockResolvedValue(undefined);
    jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue(undefined);
  });

  it('coalesces simultaneous bootstrap consumers and never rehydrates a ready session', async () => {
    const read = deferred<string | null>();
    jest.mocked(SecureStore.getItemAsync).mockReturnValueOnce(read.promise);
    const first = hydrateSession();
    const second = hydrateSession();
    expect(second).toBe(first);
    await Promise.resolve();
    read.resolve('fixture-A');
    await Promise.all([first, second]);
    await hydrateSession();
    expect(SecureStore.getItemAsync).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().auth.token).toBe('fixture-A');
  });

  it('completes an old native delete before persisting a newer login', async () => {
    const deletion = deferred<void>();
    let persisted: string | null = 'fixture-A';
    jest.mocked(SecureStore.deleteItemAsync).mockImplementationOnce(async () => {
      await deletion.promise;
      persisted = null;
    });
    jest.mocked(SecureStore.setItemAsync).mockImplementation(async (_key, value) => { persisted = value; });
    useAppStore.getState().setToken('fixture-A');
    const logout = endSession(captureSession());
    const login = completeLogin('fixture-B', captureSession());
    await Promise.resolve();
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
    deletion.resolve();
    await Promise.all([logout, login]);
    expect(persisted).toBe('fixture-B');
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });

  it('compensates a stale native write before allowing the newer writer', async () => {
    const write = deferred<void>();
    const started = deferred<void>();
    let persisted: string | null = null;
    jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async () => { persisted = null; });
    jest.mocked(SecureStore.setItemAsync).mockImplementation(async (_key, value) => {
      if (value === 'fixture-A') { started.resolve(); await write.promise; }
      persisted = value;
    });
    const a = completeLogin('fixture-A', beginAuthentication());
    const rejectedA = expect(a).rejects.toBeInstanceOf(SessionChangedError);
    await started.promise;
    const b = completeLogin('fixture-B', beginAuthentication());
    write.resolve();
    await rejectedA;
    await b;
    expect(persisted).toBe('fixture-B');
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });

  it('does not restore after a biometric prompt crosses a session boundary', async () => {
    const prompt = deferred<{ success: boolean }>();
    const unlock = unlockSavedSession(() => prompt.promise);
    useAppStore.getState().setToken('fixture-B');
    prompt.resolve({ success: true });
    expect((await unlock).success).toBe(false);
    expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });

  it('does not publish a native biometric read that finishes after logout', async () => {
    const read = deferred<string | null>();
    const started = deferred<void>();
    jest.mocked(SecureStore.getItemAsync).mockImplementationOnce(() => {
      started.resolve();
      return read.promise;
    });
    const unlock = unlockSavedSession(async () => ({ success: true }));
    await started.promise;
    const deletion = endSession(captureSession());
    read.resolve('fixture-A');
    expect((await unlock).success).toBe(false);
    await deletion;
    expect(useAppStore.getState().auth.token).toBeNull();
  });

  it('blocks biometric resurrection after failed native deletion', async () => {
    useAppStore.getState().setToken('fixture-A');
    jest.mocked(SecureStore.deleteItemAsync).mockRejectedValueOnce(new Error('fixture failure'));
    expect(await endSession(captureSession())).toBe(false);
    const prompt = jest.fn(async () => ({ success: true }));
    expect((await unlockSavedSession(prompt)).success).toBe(false);
    expect(prompt).not.toHaveBeenCalled();
    expect(useAppStore.getState().auth.token).toBeNull();
  });

  it('preserves cancellation and supported same-owner biometric restoration', async () => {
    expect(await unlockSavedSession(async () => ({ success: false, error: 'cancelled' })))
      .toEqual({ success: false, error: 'cancelled' });
    jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce('fixture-A');
    expect(await unlockSavedSession(async () => ({ success: true }))).toEqual({ success: true });
    expect(useAppStore.getState().auth.token).toBe('fixture-A');
  });

  it('does not persist a blank credential or an obsolete login intent', async () => {
    const intent = beginAuthentication();
    await expect(completeLogin('', intent)).rejects.toThrow('inválida');
    const stale = completeLogin('fixture-A', intent);
    useAppStore.getState().logout();
    await expect(stale).rejects.toBeInstanceOf(SessionChangedError);
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  });
});
