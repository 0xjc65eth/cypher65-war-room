import { renderHook, act, waitFor } from '@testing-library/react-native';
import { useCommands } from '../src/hooks/useCommands';
import * as client from '../src/api/client';

jest.mock('../src/api/client', () => ({
  sendDeviceCommand: jest.fn(),
  requestDeviceCommandConfirmation: jest.fn(),
  fetchCommandHistory: jest.fn(),
  fetchDeviceCommandStatus: jest.fn(),
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
      false,
      expect.any(String)
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
      true,
      expect.any(String)
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
      false,
      expect.any(String)
    );
  });

  it('keeps ACK separate and advances to verified only after reconciliation', async () => {
    (client.requestDeviceCommandConfirmation as jest.Mock).mockResolvedValue({
      confirmation_token: 'one-time-token',
    });
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({
      success: true,
      operation_id: 'op-1',
      ack: { state: 'acknowledged' },
      reconciliation: { state: 'pending' },
    });
    (client.fetchDeviceCommandStatus as jest.Mock).mockResolvedValue({
      success: true,
      phase: 'verified',
      reconciliation: { state: 'confirmed' },
      audit: { state: 'recorded' },
    });
    const { result } = renderHook(() => useCommands('d1'));

    await act(async () => {
      await result.current.sendCommand('restart', {}, 'CONFIRM RESTART');
    });

    expect(result.current.operationId).toBe('op-1');
    await waitFor(() => expect(result.current.phase).toBe('verified'));
    await waitFor(() => expect(result.current.auditRecorded).toBe(true));
    expect(client.fetchDeviceCommandStatus).toHaveBeenCalledWith('d1', 'op-1');
  });

  it('rejects a duplicate tap while the first command is in flight', async () => {
    let releaseRequest!: (value: unknown) => void;
    (client.sendDeviceCommand as jest.Mock).mockReturnValue(
      new Promise((resolve) => {
        releaseRequest = resolve;
      })
    );
    const { result } = renderHook(() => useCommands('d1'));

    let first!: Promise<unknown>;
    act(() => {
      first = result.current.sendCommand('restart');
    });
    let duplicate: any;
    await act(async () => {
      duplicate = await result.current.sendCommand('restart');
    });

    expect(duplicate.success).toBe(false);
    expect(duplicate.error).toMatch(/already being verified/);
    expect(client.sendDeviceCommand).toHaveBeenCalledTimes(1);

    await act(async () => {
      releaseRequest({ success: true, dry_run: true });
      await first;
    });
  });

  it('reuses the idempotency key after a lost command response', async () => {
    (client.sendDeviceCommand as jest.Mock)
      .mockRejectedValueOnce(new Error('Network timeout'))
      .mockResolvedValueOnce({ success: true, dry_run: true });
    const { result } = renderHook(() => useCommands('d1'));

    await act(async () => {
      await result.current.sendCommand('restart');
      await result.current.sendCommand('restart');
    });

    const firstKey = (client.sendDeviceCommand as jest.Mock).mock.calls[0][5];
    const retryKey = (client.sendDeviceCommand as jest.Mock).mock.calls[1][5];
    expect(retryKey).toBe(firstKey);
  });

  it('restores VERIFIED and audit evidence from an idempotent replay', async () => {
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({
      success: true,
      duplicate: true,
      operation_id: 'op-complete',
      phase: 'verified',
      reconciliation: { state: 'confirmed' },
      audit: { state: 'recorded' },
    });
    const { result } = renderHook(() => useCommands('d1'));

    await act(async () => {
      await result.current.sendCommand('restart');
    });

    expect(result.current.operationId).toBe('op-complete');
    expect(result.current.phase).toBe('verified');
    expect(result.current.auditRecorded).toBe(true);
    expect(client.fetchDeviceCommandStatus).not.toHaveBeenCalled();
  });

  it('does not update hook state after the command view unmounts', async () => {
    let releaseRequest!: (value: unknown) => void;
    (client.sendDeviceCommand as jest.Mock).mockReturnValue(
      new Promise((resolve) => {
        releaseRequest = resolve;
      })
    );
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result, unmount } = renderHook(() => useCommands('d1'));

    let request!: Promise<unknown>;
    act(() => {
      request = result.current.sendCommand('restart');
    });
    unmount();
    await act(async () => {
      releaseRequest({ success: true, dry_run: true });
      await request;
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('does not update hook state when history fails after unmount', async () => {
    let rejectHistory!: (reason: Error) => void;
    (client.fetchCommandHistory as jest.Mock).mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectHistory = reject;
      })
    );
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result, unmount } = renderHook(() => useCommands('d1'));

    let request!: Promise<unknown>;
    act(() => {
      request = result.current.getHistory();
    });
    unmount();
    await act(async () => {
      rejectHistory(new Error('history unavailable'));
      await request;
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('recovers from a transient reconciliation network failure', async () => {
    jest.useFakeTimers();
    (client.sendDeviceCommand as jest.Mock).mockResolvedValue({
      success: true,
      operation_id: 'op-retry',
      reconciliation: { state: 'pending' },
    });
    (client.fetchDeviceCommandStatus as jest.Mock)
      .mockRejectedValueOnce(new Error('temporary offline'))
      .mockResolvedValueOnce({
        phase: 'verified',
        reconciliation: { state: 'confirmed' },
        audit: { state: 'recorded' },
      });
    const { result } = renderHook(() => useCommands('d1'));

    await act(async () => {
      await result.current.sendCommand('restart');
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.phase).toBe('verified');
    expect(result.current.auditRecorded).toBe(true);
    expect(client.fetchDeviceCommandStatus).toHaveBeenCalledTimes(2);
    jest.useRealTimers();
  });
});
