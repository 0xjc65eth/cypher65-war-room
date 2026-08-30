import { useState, useCallback, useEffect, useRef } from 'react';
import {
  sendDeviceCommand,
  requestDeviceCommandConfirmation,
  fetchCommandHistory,
  fetchDeviceCommandStatus,
} from '../api/client';

export type CommandPhase =
  | 'idle'
  | 'acknowledged'
  | 'offline'
  | 'reconnecting'
  | 'verified'
  | 'unknown'
  | 'failed';

const RECONCILIATION_ATTEMPTS = 60;
const RECONCILIATION_INTERVAL_MS = 2000;

const wait = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

export const useCommands = (deviceId: string) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<CommandPhase>('idle');
  const [operationId, setOperationId] = useState<string | null>(null);
  const [reconciling, setReconciling] = useState(false);
  const [auditRecorded, setAuditRecorded] = useState(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const activeIdempotencyKey = useRef<string | null>(null);

  useEffect(() => () => {
    mounted.current = false;
    generation.current += 1;
  }, []);

  const reconcile = useCallback(async (id: string, currentGeneration: number) => {
    if (!mounted.current || generation.current !== currentGeneration) return;
    setReconciling(true);
    try {
      for (let attempt = 0; attempt < RECONCILIATION_ATTEMPTS; attempt += 1) {
        if (!mounted.current || generation.current !== currentGeneration) return;
        let status: Awaited<ReturnType<typeof fetchDeviceCommandStatus>>;
        try {
          status = await fetchDeviceCommandStatus(deviceId, id);
        } catch (err) {
          if (!mounted.current || generation.current !== currentGeneration) return;
          if (attempt === RECONCILIATION_ATTEMPTS - 1) throw err;
          await wait(Math.min(RECONCILIATION_INTERVAL_MS * (attempt + 1), 10000));
          continue;
        }
        if (!mounted.current || generation.current !== currentGeneration) return;
        const nextPhase = (status?.phase ||
          (status?.reconciliation?.state === 'confirmed' ? 'verified' : 'reconnecting')) as CommandPhase;
        setPhase(nextPhase);
        if (status?.reconciliation?.state === 'confirmed') {
          setAuditRecorded(status?.audit?.state === 'recorded');
          activeIdempotencyKey.current = null;
          return;
        }
        if (['failed', 'unknown'].includes(status?.reconciliation?.state)) {
          setPhase(status.reconciliation.state);
          setError(status?.reconciliation?.reason || 'Command could not be verified');
          if (status?.reconciliation?.state === 'failed') {
            activeIdempotencyKey.current = null;
          }
          return;
        }
        await wait(RECONCILIATION_INTERVAL_MS);
      }
      if (mounted.current && generation.current === currentGeneration) {
        setPhase('unknown');
        setError('Reconciliation timed out without verified device state');
      }
    } catch (err) {
      if (mounted.current && generation.current === currentGeneration) {
        setPhase('unknown');
        setError((err as Error).message);
      }
    } finally {
      if (mounted.current && generation.current === currentGeneration) {
        setReconciling(false);
        inFlight.current = false;
      }
    }
  }, [deviceId]);

  const sendCommand = useCallback(
    async (
      command: string,
      parameters: Record<string, unknown> = {},
      humanConfirmation?: string
    ) => {
      if (inFlight.current) {
        return { success: false, error: 'A command is already being verified' };
      }
      inFlight.current = true;
      let startedReconciliation = false;
      const idempotencyKey =
        activeIdempotencyKey.current ||
        `mobile-${deviceId}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      activeIdempotencyKey.current = idempotencyKey;
      setLoading(true);
      setError(null);
      setAuditRecorded(false);
      generation.current += 1;
      const currentGeneration = generation.current;
      try {
        let confirmationToken: string | undefined;
        if (humanConfirmation) {
          const confirmation = await requestDeviceCommandConfirmation(
            deviceId,
            command,
            parameters,
            humanConfirmation
          );
          if (!mounted.current || generation.current !== currentGeneration) {
            return { success: false, error: 'Command view is no longer active' };
          }
          confirmationToken = confirmation?.confirmation_token;
        }
        const result = await sendDeviceCommand(
          deviceId,
          command,
          parameters,
          confirmationToken,
          Boolean(confirmationToken),
          idempotencyKey
        );
        if (!mounted.current || generation.current !== currentGeneration) {
          return { success: false, error: 'Command view is no longer active' };
        }
        if (!result?.success) {
          const message = result?.error || 'Command failed';
          setError(message);
          return { success: false, error: message, data: result };
        }
        if (result?.operation_id && result?.reconciliation?.state === 'pending') {
          startedReconciliation = true;
          setOperationId(result.operation_id);
          setPhase('acknowledged');
          void reconcile(result.operation_id, currentGeneration);
        } else if (result?.operation_id && result?.reconciliation?.state === 'confirmed') {
          setOperationId(result.operation_id);
          setPhase('verified');
          setAuditRecorded(result?.audit?.state === 'recorded');
          activeIdempotencyKey.current = null;
        } else if (result?.dry_run) {
          setPhase('idle');
          activeIdempotencyKey.current = null;
        }
        return { success: true, data: result };
      } catch (err) {
        const message = (err as Error).message;
        if (mounted.current && generation.current === currentGeneration) {
          setError(message);
        }
        return { success: false, error: message };
      } finally {
        if (mounted.current && generation.current === currentGeneration) {
          setLoading(false);
          if (!startedReconciliation) inFlight.current = false;
        }
      }
    },
    [deviceId, reconcile]
  );

  const getHistory = useCallback(async () => {
    const currentGeneration = generation.current;
    try {
      return await fetchCommandHistory(deviceId);
    } catch (err) {
      if (mounted.current && generation.current === currentGeneration) {
        setError((err as Error).message);
      }
      return [];
    }
  }, [deviceId]);

  return {
    sendCommand,
    getHistory,
    loading,
    error,
    phase,
    operationId,
    reconciling,
    auditRecorded,
  };
};
