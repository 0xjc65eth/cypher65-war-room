import * as SecureStore from 'expo-secure-store';
import { useAppStore } from '../store';
import { clearSessionCache } from './offline';
import { assertSession, captureSession, isCurrentSession, SessionChangedError, type SessionLease } from './sessionLease';
import type { BiometricResult } from './biometrics';

const TOKEN_KEY = 'cypher65_token';
let credentialTail: Promise<unknown> = Promise.resolve();
let hydration: Promise<void> | null = null;

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const result = credentialTail.then(operation);
  credentialTail = result.catch(() => undefined);
  return result;
}

/**
 * Restore once per app bootstrap, never once per mounted auth consumer.
 * @example await hydrateSession();
 */
export function hydrateSession(): Promise<void> {
  if (useAppStore.getState().authReady) return Promise.resolve();
  if (hydration) return hydration;
  const lease = captureSession();
  hydration = serialize(async () => {
    if (!isCurrentSession(lease)) return;
    try {
      const token = await SecureStore.getItemAsync(TOKEN_KEY);
      if (isCurrentSession(lease)) useAppStore.getState().setToken(token ?? null);
    } catch {
      if (isCurrentSession(lease)) useAppStore.getState().setToken(null);
    }
  }).finally(() => { hydration = null; });
  return hydration;
}

/**
 * Invalidate memory immediately; serialize native deletion ahead of new writes.
 * False means native deletion failed, not that the old UI remains authorized.
 * @example const removed = await endSession(captureSession());
 */
export function endSession(lease: SessionLease): Promise<boolean> {
  if (!isCurrentSession(lease)) return Promise.resolve(false);
  useAppStore.getState().logout();
  const exited = captureSession();
  void clearSessionCache(lease);
  return serialize(async () => {
    try {
      await SecureStore.deleteItemAsync(TOKEN_KEY);
      return true;
    } catch {
      // In-process restoration stays disabled. Native persistence after a
      // storage fault/restart requires separate device evidence, not a claim.
      if (isCurrentSession(exited)) useAppStore.setState({
        authNotice: 'Saída local concluída; não foi possível remover a credencial salva. Não compartilhe este aparelho até verificar o armazenamento seguro.',
      });
      return false;
    }
  });
}

/**
 * A newer login intent supersedes pending bootstrap, login and biometric work.
 * @example const intent = beginAuthentication(); await completeLogin(token, intent);
 */
export function beginAuthentication(): SessionLease {
  void endSession(captureSession());
  useAppStore.setState({ authPending: true, authNotice: null });
  return captureSession();
}

/**
 * Persist and publish only the still-current authentication intent.
 * @example await completeLogin(response.token, intent);
 */
export function completeLogin(token: string, intent: SessionLease): Promise<void> {
  return serialize(async () => {
    assertSession(intent);
    if (typeof token !== 'string' || !token.trim()) throw new Error('Resposta de autenticação inválida.');
    await SecureStore.setItemAsync(TOKEN_KEY, token);
    if (!isCurrentSession(intent)) {
      // No newer writer can run until this compensation leaves the queue.
      await SecureStore.deleteItemAsync(TOKEN_KEY);
      throw new SessionChangedError();
    }
    useAppStore.getState().setToken(token);
  });
}

/**
 * Bind the native prompt and credential read to the same identity generation.
 * This is race isolation, not certification of biometric-protected Keychain.
 * @example await unlockSavedSession(() => authenticateWithBiometrics());
 */
export async function unlockSavedSession(
  authenticate: () => Promise<BiometricResult>
): Promise<BiometricResult> {
  const lease = captureSession();
  try {
    if (!useAppStore.getState().credentialRestoreAllowed) throw new SessionChangedError();
    const result = await authenticate();
    assertSession(lease);
    if (!result.success) return result;
    return await serialize(async () => {
      assertSession(lease);
      if (!useAppStore.getState().credentialRestoreAllowed) throw new SessionChangedError();
      const token = await SecureStore.getItemAsync(TOKEN_KEY);
      assertSession(lease);
      if (!token) return { success: false, error: 'Nenhuma sessão salva. Entre com suas credenciais.' };
      useAppStore.getState().setToken(token);
      return { success: true };
    });
  } catch {
    return { success: false, error: 'Não foi possível restaurar a sessão. Entre novamente.' };
  }
}
