import { useEffect, useMemo } from 'react';
import { useAppStore } from '../store';
import { isCurrentSession, type SessionLease } from '../services/sessionLease';

/**
 * Bind callbacks to their originating render and mount, not their invocation.
 * Old callbacks cannot acquire a newer account's authority before cleanup runs.
 * @example const scope = useSessionScope(); if (scope.isActive()) publish(data);
 */
export function useSessionScope() {
  const revision = useAppStore((state) => state.authRevision);
  const token = useAppStore((state) => state.auth.token);
  const scope = useMemo(() => {
    const lease: SessionLease = Object.freeze({ revision, token });
    let active = true;
    return {
      lease,
      isActive: () => active && isCurrentSession(lease),
      activate: () => { active = true; },
      deactivate: () => { active = false; },
    };
  }, [revision, token]);
  useEffect(() => {
    scope.activate();
    return scope.deactivate;
  }, [scope]);
  return scope;
}
