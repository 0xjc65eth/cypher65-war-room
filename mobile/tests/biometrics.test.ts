import * as LocalAuthentication from 'expo-local-authentication';
import {
  isBiometricAvailable,
  authenticateWithBiometrics,
  promptCriticalAction,
  type BiometricResult,
} from '../src/services/biometrics';

jest.mock('expo-local-authentication', () => ({
  hasHardwareAsync: jest.fn(),
  isEnrolledAsync: jest.fn(),
  authenticateAsync: jest.fn(),
}));

describe('biometrics', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('is available only when hardware exists and a biometric is enrolled', async () => {
    (LocalAuthentication.hasHardwareAsync as jest.Mock).mockResolvedValue(true);
    (LocalAuthentication.isEnrolledAsync as jest.Mock).mockResolvedValue(false);
    expect(await isBiometricAvailable()).toBe(false);

    (LocalAuthentication.isEnrolledAsync as jest.Mock).mockResolvedValue(true);
    expect(await isBiometricAvailable()).toBe(true);
  });

  it('fails closed when biometrics are unavailable', async () => {
    (LocalAuthentication.hasHardwareAsync as jest.Mock).mockResolvedValue(false);
    (LocalAuthentication.isEnrolledAsync as jest.Mock).mockResolvedValue(false);
    const result: BiometricResult = await authenticateWithBiometrics();
    expect(result).toEqual({
      success: false,
      error: 'Biometric authentication not available',
    });
    expect(LocalAuthentication.authenticateAsync).not.toHaveBeenCalled();
  });

  it('returns success or the firmware error from authenticateAsync', async () => {
    (LocalAuthentication.hasHardwareAsync as jest.Mock).mockResolvedValue(true);
    (LocalAuthentication.isEnrolledAsync as jest.Mock).mockResolvedValue(true);
    (LocalAuthentication.authenticateAsync as jest.Mock).mockResolvedValue({ success: true });
    await expect(authenticateWithBiometrics('Unlock')).resolves.toEqual({ success: true });

    (LocalAuthentication.authenticateAsync as jest.Mock).mockResolvedValue({
      success: false,
      error: 'user_cancel',
    });
    await expect(authenticateWithBiometrics()).resolves.toEqual({
      success: false,
      error: 'user_cancel',
    });
  });

  it('prompts a critical action with the action name in the message', async () => {
    (LocalAuthentication.hasHardwareAsync as jest.Mock).mockResolvedValue(true);
    (LocalAuthentication.isEnrolledAsync as jest.Mock).mockResolvedValue(true);
    (LocalAuthentication.authenticateAsync as jest.Mock).mockResolvedValue({ success: true });
    await expect(promptCriticalAction('restart miner')).resolves.toEqual({ success: true });
    expect(LocalAuthentication.authenticateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ promptMessage: 'Confirm to restart miner' })
    );
  });
});
