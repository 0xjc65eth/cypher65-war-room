import { api, fetchRentals } from '../src/api/client';

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
});
