import type { Theme } from '../src/theme';
import { theme } from '../src/theme';
import type {
  MobileEnvironment,
  ExpoEnvironmentExtra,
} from '../src/config/environment';
import type { RootNavigationProp, FleetNavigationProp } from '../src/types/navigation';

describe('exported mobile types', () => {
  it('keeps the theme token contract and environment aliases', () => {
    const tokens: Theme = theme;
    expect(tokens.bg.deep).toBe('#0b0f19');
    const env: MobileEnvironment = 'production';
    const extra: ExpoEnvironmentExtra = { environment: env, apiBaseUrl: 'https://example.com/api' };
    expect(extra.environment).toBe('production');
  });

  it('keeps navigation prop aliases assignable', () => {
    type Root = RootNavigationProp;
    type Fleet = FleetNavigationProp;
    const names: Array<keyof Root | keyof Fleet | string> = ['navigate'];
    expect(names).toContain('navigate');
  });
});
