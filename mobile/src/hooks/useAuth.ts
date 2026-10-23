import { useEffect } from 'react';
import { useAppStore } from '../store';
import { login as apiLogin, logoutRemote } from '../api/client';
import { beginAuthentication, completeLogin, endSession, hydrateSession, unlockSavedSession } from '../services/authSession';
import { assertSession, captureSession, isCurrentSession, type SessionLease } from '../services/sessionLease';
import { authenticateWithBiometrics } from '../services/biometrics';

/**
 * Coordinate session-bound bootstrap/login/logout without stale native writes.
 * @example const { login, logout, loading } = useAuth();
 */
export const useAuth = () => {
  const { auth, authReady, authPending, authNotice } = useAppStore();
  const viewSession = captureSession();

  useEffect(() => {
    void hydrateSession();
  }, []);

  const login = async (username: string, password: string) => {
    let intent: SessionLease | undefined;
    try {
      assertSession(viewSession);
      intent = beginAuthentication();
      const response = await apiLogin({ username, password });
      await completeLogin(response.token, intent);
      return { success: true };
    } catch (error) {
      if (intent && isCurrentSession(intent)) useAppStore.setState({
        authNotice: 'Não foi possível entrar. Verifique suas credenciais e a conexão.',
      });
      return { success: false, error: (error as Error).message };
    } finally {
      if (intent && isCurrentSession(intent)) useAppStore.setState({ authPending: false });
    }
  };

  const logout = async () => {
    assertSession(viewSession);
    const old = captureSession();
    const deletion = endSession(old);
    try {
      if (old.token) await logoutRemote(old.token);
    } catch {
      // Remote revocation failure does not authorize keeping the local session.
    }
    const removed = await deletion;
    return { success: removed, ...(!removed && { error: 'Saída local concluída; não foi possível remover a credencial salva.' }) };
  };

  const unlock = async () => {
    try {
      assertSession(viewSession);
      return await unlockSavedSession(() => authenticateWithBiometrics('Desbloquear CYPHER65'));
    } catch {
      return { success: false, error: 'A sessão mudou. Entre novamente.' };
    }
  };
  return { ...auth, loading: !authReady || authPending, authPending, authNotice, login, logout, unlock };
};
