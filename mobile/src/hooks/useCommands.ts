import { useState, useCallback } from 'react';
import {
  sendDeviceCommand,
  requestDeviceCommandConfirmation,
  fetchCommandHistory,
} from '../api/client';

export const useCommands = (deviceId: string) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendCommand = useCallback(
    async (
      command: string,
      parameters: Record<string, unknown> = {},
      humanConfirmation?: string
    ) => {
      setLoading(true);
      setError(null);
      try {
        let confirmationToken: string | undefined;
        if (humanConfirmation) {
          const confirmation = await requestDeviceCommandConfirmation(
            deviceId,
            command,
            parameters,
            humanConfirmation
          );
          confirmationToken = confirmation?.confirmation_token;
        }
        const result = await sendDeviceCommand(
          deviceId,
          command,
          parameters,
          confirmationToken,
          Boolean(confirmationToken)
        );
        if (!result?.success) {
          const message = result?.error || 'Command failed';
          setError(message);
          return { success: false, error: message, data: result };
        }
        return { success: true, data: result };
      } catch (err) {
        const message = (err as Error).message;
        setError(message);
        return { success: false, error: message };
      } finally {
        setLoading(false);
      }
    },
    [deviceId]
  );

  const getHistory = useCallback(async () => {
    try {
      return await fetchCommandHistory(deviceId);
    } catch (err) {
      setError((err as Error).message);
      return [];
    }
  }, [deviceId]);

  return { sendCommand, getHistory, loading, error };
};
