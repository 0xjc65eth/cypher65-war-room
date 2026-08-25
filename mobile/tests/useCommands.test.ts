import { renderHook, act } from '@testing-library/react-native';
import { useCommands } from '../src/hooks/useCommands';
import * as client from '../src/api/client';

jest.mock('../src/api/client', () => ({
  sendDeviceCommand: jest.fn(),
  fetchCommandHistory: jest.fn(),
}));

describe('useCommands', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('sends a command successfully', async () => {
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({ success: true });
    const { result } = renderHook(() => useCommands('d1'));

    let response: any;
    await act(async () => {
      response = await result.current.sendCommand('restart');
    });

    expect(client.sendDeviceCommand).toHaveBeenCalledWith('d1', 'restart', {});
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

  it('consumes the server confirmation before reporting success', async () => {
    (client.sendDeviceCommand as jest.Mock)
      .mockResolvedValueOnce({
        success: false,
        confirmation_required: true,
        confirmation_token: 'one-time-token',
      })
      .mockResolvedValueOnce({ success: true });
    const { result } = renderHook(() => useCommands('d1'));

    let response: any;
    await act(async () => {
      response = await result.current.sendCommand('restart');
    });

    expect(client.sendDeviceCommand).toHaveBeenNthCalledWith(1, 'd1', 'restart', {});
    expect(client.sendDeviceCommand).toHaveBeenNthCalledWith(
      2,
      'd1',
      'restart',
      {},
      'one-time-token'
    );
    expect(response.success).toBe(true);
  });
});
