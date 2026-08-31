import { validateApiBaseUrl } from '../../config/api-url';

export type MobileEnvironment = 'development' | 'testing' | 'staging' | 'production';

export interface ExpoEnvironmentExtra {
  environment?: string;
  apiBaseUrl?: string;
}

export function resolveMobileEnvironment(extra: ExpoEnvironmentExtra | undefined, isDev: boolean) {
  const environment = String(extra?.environment || (isDev ? 'development' : '')) as MobileEnvironment;
  if (!['development', 'testing', 'staging', 'production'].includes(environment)) {
    throw new Error('CYPHER65 mobile environment is missing or invalid');
  }
  const developmentDefault = isDev && environment === 'development' ? 'http://127.0.0.1:8765/api' : '';
  const apiBaseUrl = validateApiBaseUrl(
    environment,
    String(extra?.apiBaseUrl || developmentDefault)
  );
  const parsed = new URL(apiBaseUrl);
  return { environment, apiBaseUrl, apiHost: parsed.host };
}
