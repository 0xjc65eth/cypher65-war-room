import * as LocalAuthentication from 'expo-local-authentication';

export interface BiometricResult {
  success: boolean;
  error?: string;
}

export const isBiometricAvailable = async (): Promise<boolean> => {
  const compatible = await LocalAuthentication.hasHardwareAsync();
  const enrolled = await LocalAuthentication.isEnrolledAsync();
  return compatible && enrolled;
};

export const authenticateWithBiometrics = async (
  promptMessage = 'Confirm your identity',
  cancelLabel = 'Cancel'
): Promise<BiometricResult> => {
  try {
    const available = await isBiometricAvailable();
    if (!available) {
      return { success: false, error: 'Biometric authentication not available' };
    }

    const result = await LocalAuthentication.authenticateAsync({
      promptMessage,
      cancelLabel,
      disableDeviceFallback: false,
      fallbackLabel: 'Use passcode',
    });

    if (result.success) {
      return { success: true };
    }
    return { success: false, error: result.error || 'Biometric authentication failed' };
  } catch (error) {
    return { success: false, error: (error as Error).message };
  }
};

export const promptCriticalAction = async (actionName: string): Promise<BiometricResult> => {
  return authenticateWithBiometrics(
    `Confirm to ${actionName}`,
    'Cancel'
  );
};
