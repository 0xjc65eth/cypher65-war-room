const ENVIRONMENTS = new Set(['development', 'testing', 'staging', 'production']);
const LOCAL_HOST = /^(localhost|127\.|\[?::1\]?|0\.0\.0\.0|10\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?(fc|fd|fe80|::ffff:))/i;

function validateApiBaseUrl(environment, configuredUrl) {
  if (!ENVIRONMENTS.has(environment)) {
    throw new Error(`Unsupported CYPHER65_APP_ENV: ${environment}`);
  }
  const value = String(configuredUrl || '').trim();
  if (!value) throw new Error(`API base URL is required for ${environment}`);
  const parsed = new URL(value);
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('API base URL cannot contain credentials, query, or fragment');
  }
  if (!parsed.pathname.endsWith('/api')) throw new Error('API base URL must end in /api');
  if (environment === 'production' || environment === 'staging') {
    if (parsed.protocol !== 'https:') throw new Error(`${environment} API must use HTTPS`);
    if (LOCAL_HOST.test(parsed.hostname) || parsed.hostname.toLowerCase().endsWith('.local')) {
      throw new Error(`${environment} API cannot target a local endpoint`);
    }
  }
  return value.replace(/\/$/, '');
}

module.exports = { ENVIRONMENTS, validateApiBaseUrl };
