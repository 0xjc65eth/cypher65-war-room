import { api } from '../src/api/client';

jest.mock('expo-secure-store', () => ( ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

describe('API client', () => {
  it('exports an axios instance with a baseURL', () => {
    expect(api.defaults.baseURL).toBeDefined();
  });
});
