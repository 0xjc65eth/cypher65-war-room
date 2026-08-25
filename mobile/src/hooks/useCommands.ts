import { useState, useCallback } from 'react';
import { sendDeviceCommand, fetchCommandHistory } from '../api/client';

export const useCommands = (deviceId: string) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendCommand = useCallback(
    async (command: string, parameters: Record<string, unknown> = {}) => {
      setLoading(true);
      setError(null);
      try {
        let result = await sendDeviceCommand(deviceId, command, parameters);
        if (result?.confirmation_required && result.confirmation_token) {
          result = await sendDeviceCommand(
            deviceId,
            command,
            parameters,
            result.confirmation_token
          );
        }
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
