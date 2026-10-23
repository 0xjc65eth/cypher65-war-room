import { useAppStore } from '../store';

/** In-memory authority only. Never serialize or log this descriptor. */
export interface SessionLease {
  readonly revision: number;
  readonly token: string | null;
}

/** Controlled cancellation without credentials or response bodies in its text. */
export class SessionChangedError extends Error {
  constructor() {
    super('A sessão mudou. Entre novamente.');
    this.name = 'SessionChangedError';
  }
}

/**
 * Capture the session synchronously before starting asynchronous work.
 * @example const lease = captureSession(); await read(); assertSession(lease);
 */
export function captureSession(): SessionLease {
  const { authRevision, auth } = useAppStore.getState();
  return { revision: authRevision, token: auth.token };
}

/**
 * Check both identity and generation, including A → logout → A transitions.
 * @example if (isCurrentSession(lease)) publish(data);
 */
export function isCurrentSession(lease: SessionLease): boolean {
  const state = useAppStore.getState();
  return state.authRevision === lease.revision && state.auth.token === lease.token;
}

/**
 * Reject work belonging to an obsolete session before dispatch or publication.
 * @example assertSession(lease); await fetchObservation();
 */
export function assertSession(lease: SessionLease): void {
  if (!isCurrentSession(lease)) throw new SessionChangedError();
}
