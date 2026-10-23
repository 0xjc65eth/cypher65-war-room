import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import * as SecureStore from 'expo-secure-store';
import { api, logoutRemote } from '../src/api/client';
import { useAppStore } from '../src/store';
import { SessionChangedError } from '../src/services/sessionLease';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(), setItemAsync: jest.fn(), deleteItemAsync: jest.fn(),
}));

describe('real axios session boundary with a synthetic adapter', () => {
  let finish: (status: number) => void;
  let sent: InternalAxiosRequestConfig;

  beforeEach(() => {
    jest.resetAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    useAppStore.getState().setToken('fixture-A');
    jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue(undefined);
    api.defaults.adapter = (config) => {
      sent = config;
      return new Promise((resolve, reject) => {
        finish = (status) => {
          const response: AxiosResponse = { config, data: { owner: 'A' }, status, statusText: 'fixture', headers: {} };
          if (status >= 400) reject(new AxiosError('fixture rejection', 'ERR_BAD_REQUEST', config, undefined, response));
          else resolve(response);
        };
      });
    };
  });

  afterEach(() => { jest.restoreAllMocks(); });

  it('binds the bearer synchronously without a deferred native credential lookup', async () => {
    const request = api.get('/fixture');
    expect(sent.headers.get('Authorization')).toBe('Bearer fixture-A');
    expect(SecureStore.getItemAsync).not.toHaveBeenCalled();
    useAppStore.getState().setToken('fixture-B');
    finish(200);
    await expect(request).rejects.toBeInstanceOf(SessionChangedError);
  });

  it.each([200, 401, 403, 500])('rejects stale %s responses without touching B credentials', async (status) => {
    const request = api.get('/fixture');
    useAppStore.getState().setToken('fixture-B');
    finish(status);
    await expect(request).rejects.toBeInstanceOf(SessionChangedError);
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
    expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
  });

  it('invalidates the current session on protected 401, but not login rejection', async () => {
    const login = api.post('/auth/login', {});
    finish(401);
    await expect(login).rejects.toBeInstanceOf(AxiosError);
    expect(useAppStore.getState().auth.token).toBe('fixture-A');
    const protectedRequest = api.get('/fixture');
    finish(401);
    await expect(protectedRequest).rejects.toBeInstanceOf(AxiosError);
    expect(useAppStore.getState().auth.token).toBeNull();
    await Promise.resolve();
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('cypher65_token');
  });

  it('does not authorize anonymous requests from an explicitly supplied bearer', async () => {
    useAppStore.getState().logout();
    const request = api.get('/fixture', { headers: { Authorization: 'Bearer fixture-A' } });
    expect(sent.headers.has('Authorization')).toBe(false);
    finish(200);
    await expect(request).resolves.toMatchObject({ status: 200 });
  });

  it('revokes only the captured old token through a separate bounded transport', async () => {
    useAppStore.getState().setToken('fixture-B');
    const post = jest.spyOn(axios, 'post').mockResolvedValue({ data: { success: true } });
    await logoutRemote('fixture-A');
    expect(post).toHaveBeenCalledWith(expect.stringMatching(/\/api\/auth\/logout$/), {}, {
      timeout: 15000,
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer fixture-A' },
    });
    expect(useAppStore.getState().auth.token).toBe('fixture-B');
  });
});
