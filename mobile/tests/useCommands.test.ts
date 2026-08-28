import { renderHook, act } from '@testing-library/react-native';
import { useCommands } from '../src/hooks/useCommands';
import * as client from '../src/api/client';

jest.mock('../src/api/client', () => ({
  sendDeviceCommand: jest.fn(),
  requestDeviceCommandConfirmation: jest.fn(),
  fetchCommandHistory: jest.fn(),
}));

describe('useCommands', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('defaults an unconfirmed command to dry-run', async () => {
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({
      success: true,
      dry_run: true,
    });
    const { result } = renderHook(() => useCommands('d1'));

    let response: any;
    await act(async () => {
      response = await result.current.sendCommand('restart');
    });

    expect(client.sendDeviceCommand).toHaveBeenCalledWith(
      'd1',
      'restart',
      {},
      undefined,
      false
    );
    expect(response.success).toBe(true);
  });

  it('handles command errors', async () => {
    (client.sendDeviceCommand as jest.Mock).mockRejectedValue(new Error('Device offline'));
    const { result } = renderHook(() => useCommands('d1'));

    let response: any;
    await act(async () => {
      response = await result.current.sendCommand('restart');
    });

    expect(response.success).toBe(false);
    expect(response.error).toBe('Device offline');
  });

  it('executes only after an explicit human confirmation obtains a token', async () => {
    (client.requestDeviceCommandConfirmation as jest.Mock).mockResolvedValue({
      success: true,
      confirmation_token: 'one-time-token',
    });
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({ success: true });
    const { result } = renderHook(() => useCommands('d1'));

    let response: any;
    await act(async () => {
      response = await result.current.sendCommand('restart', {}, 'CONFIRM RESTART');
    });

    expect(client.requestDeviceCommandConfirmation).toHaveBeenCalledWith(
      'd1',
      'restart',
      {},
      'CONFIRM RESTART'
    );
    expect(client.sendDeviceCommand).toHaveBeenCalledWith(
      'd1',
      'restart',
      {},
      'one-time-token',
      true
    );
    expect(response.success).toBe(true);
  });

  it('never requests a confirmation token without explicit human confirmation', async () => {
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({
      success: false,
      error: 'human confirmation required',
    });
    const { result } = renderHook(() => useCommands('d1'));

    await act(async () => {
      await result.current.sendCommand('restart');
    });

    expect(client.requestDeviceCommandConfirmation).not.toHaveBeenCalled();
    expect(client.sendDeviceCommand).toHaveBeenCalledWith(
      'd1',
      'restart',
      {},
      undefined,
      false
    );
  });
});
