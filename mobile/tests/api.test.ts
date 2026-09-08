import {
  api,
  mobileEnvironment,
  fetchRentals,
  fetchDeviceDiagnostics,
  fetchDeviceTimeline,
  createMaintenanceRecord,
  fetchBestDiffHistory,
  fetchMarketHistory,
} from '../src/api/client';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

describe('API client', () => {
  it('exports an axios instance with a baseURL', () => {
    expect(api.defaults.baseURL).toBeDefined();
  });

  it('fetchRentals hits /rentals and returns the payload', async () => {
    const mock = jest.fn().mockResolvedValue({
      data: { success: true, mrr: { active: [] }, braiins: { contracts: [] } },
    });
    (api.get as jest.Mock) = mock;
    const result = await fetchRentals();
    expect(mock).toHaveBeenCalledWith('/rentals');
    expect(result.mrr.active).toEqual([]);
    expect(result.braiins.contracts).toEqual([]);
  });

  it('exposes the resolved mobile environment used as axios baseURL', () => {
    expect(mobileEnvironment.apiBaseUrl).toBe(api.defaults.baseURL);
    expect(mobileEnvironment.environment).toMatch(/development|testing|staging|production/);
  });

  it('hits device diagnostics, timeline and maintenance endpoints', async () => {
    const get = jest.fn().mockResolvedValue({ data: { ok: true } });
    const post = jest.fn().mockResolvedValue({ data: { id: 'm1' } });
    (api.get as jest.Mock) = get;
    (api.post as jest.Mock) = post;

    await expect(fetchDeviceDiagnostics('d1')).resolves.toEqual({ ok: true });
    expect(get).toHaveBeenCalledWith('/devices/d1/diagnostics');

    await expect(fetchDeviceTimeline('d1')).resolves.toEqual({ ok: true });
    expect(get).toHaveBeenCalledWith('/devices/d1/timeline');

    await expect(
      createMaintenanceRecord('d1', { type: 'clean', notes: 'fan', performed_by: 'op' })
    ).resolves.toEqual({ id: 'm1' });
    expect(post).toHaveBeenCalledWith('/devices/d1/maintenance', {
      type: 'clean',
      notes: 'fan',
      performed_by: 'op',
    });
  });

  it('hits best-diff and market history endpoints', async () => {
    const get = jest.fn().mockResolvedValue({ data: { points: [] } });
    (api.get as jest.Mock) = get;

    await expect(fetchBestDiffHistory()).resolves.toEqual({ points: [] });
    expect(get).toHaveBeenCalledWith('/best-diff-history');

    await expect(fetchMarketHistory(50)).resolves.toEqual({ points: [] });
    expect(get).toHaveBeenCalledWith('/hashrate-market/history', { params: { limit: 50 } });
  });
});
