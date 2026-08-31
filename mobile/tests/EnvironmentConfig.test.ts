import { resolveMobileEnvironment } from '../src/config/environment';

describe('mobile environment isolation', () => {
  it.each([
    'http://127.0.0.1:8765/api',
    'https://cypher65.local/api',
    'http://example.com/api',
    'https://10.0.0.1/api',
    'https://169.254.169.254/api',
    'https://[::1]/api',
    'https://[fd00::1]/api',
    'https://127.0.0.2/api',
    'https://[::ffff:127.0.0.1]/api',
    'https://user:password@example.com/api',
    'https://example.com/api?token=secret',
    'https://example.com/api#secret',
  ])(
    'rejects an unsafe production endpoint: %s',
    (apiBaseUrl) => {
      expect(() =>
        resolveMobileEnvironment({ environment: 'production', apiBaseUrl }, false)
      ).toThrow();
    }
  );

  it('accepts the explicit production HTTPS endpoint', () => {
    expect(
      resolveMobileEnvironment(
        { environment: 'production', apiBaseUrl: 'https://cypher65-war-room.onrender.com/api' },
        false
      )
    ).toEqual({
      environment: 'production',
      apiBaseUrl: 'https://cypher65-war-room.onrender.com/api',
      apiHost: 'cypher65-war-room.onrender.com',
    });
  });

  it('fails closed in a release build without explicit generated config', () => {
    expect(() => resolveMobileEnvironment(undefined, false)).toThrow(/missing or invalid/);
  });

  it('allows localhost only for an explicit development environment', () => {
    expect(
      resolveMobileEnvironment(
        { environment: 'development', apiBaseUrl: 'http://127.0.0.1:8765/api' },
        true
      ).environment
    ).toBe('development');
  });
});
