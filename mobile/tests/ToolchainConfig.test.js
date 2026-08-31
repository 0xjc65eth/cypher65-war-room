const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const repositoryRoot = path.resolve(root, '..');

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), 'utf8'));
}

describe('mobile toolchain contract', () => {
  test('uses the supported Expo 57 dependency matrix and a real lint command', () => {
    const pkg = readJson('package.json');

    expect(pkg.engines.node).toBe('>=22.13.0');
    expect(pkg.dependencies.expo).toMatch(/^~57\./);
    expect(pkg.dependencies['react-native']).toMatch(/^0\.86\./);
    expect(pkg.dependencies.react).toMatch(/^19\.2\./);
    expect(pkg.scripts.lint).toMatch(/^biome lint --error-on-warnings /);
    expect(pkg.scripts.lint).not.toContain('eslint');
  });

  test('all configured app assets exist and splash uses the supported plugin', () => {
    const previousEnvironment = process.env.CYPHER65_APP_ENV;
    process.env.CYPHER65_APP_ENV = 'production';
    const app = require('../app.config.js')();
    if (previousEnvironment === undefined) delete process.env.CYPHER65_APP_ENV;
    else process.env.CYPHER65_APP_ENV = previousEnvironment;
    const splashPlugin = app.plugins.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === 'expo-splash-screen',
    );

    expect(app.splash).toBeUndefined();
    expect(splashPlugin).toBeDefined();
    expect(app.orientation).toBe('default');
    expect(app.ios.bundleIdentifier).toBe('com.cypher65.warroom');
    expect(app.ios.buildNumber).toMatch(/^\d+$/);
    expect(app.ios.infoPlist.NSAppTransportSecurity.NSAllowsArbitraryLoads).toBe(false);
    expect(app.ios.infoPlist.NSFaceIDUsageDescription).toMatch(/Face ID/);
    expect(app.ios.infoPlist.UIBackgroundModes).toEqual(['remote-notification']);
    expect(JSON.stringify(app)).not.toMatch(
      /BTCPAY_API_KEY|JWT_SIGNING_KEY|WALLET_PRIVATE_KEY|MRR_API_SECRET|BRAIINS_API_KEY/
    );

    const assetPaths = [app.icon, app.web.favicon, splashPlugin[1].image];
    for (const assetPath of assetPaths) {
      expect(fs.existsSync(path.resolve(root, assetPath))).toBe(true);
    }
  });

  test.each([
    'http://example.com/api',
    'https://localhost/api',
    'https://192.168.1.5/api',
    'https://169.254.169.254/api',
    'https://[::1]/api',
  ])('dynamic production config rejects unsafe API %s', (apiUrl) => {
    const previousEnvironment = process.env.CYPHER65_APP_ENV;
    const previousUrl = process.env.CYPHER65_API_BASE_URL;
    process.env.CYPHER65_APP_ENV = 'production';
    process.env.CYPHER65_API_BASE_URL = apiUrl;
    expect(() => require('../app.config.js')()).toThrow();
    if (previousEnvironment === undefined) delete process.env.CYPHER65_APP_ENV;
    else process.env.CYPHER65_APP_ENV = previousEnvironment;
    if (previousUrl === undefined) delete process.env.CYPHER65_API_BASE_URL;
    else process.env.CYPHER65_API_BASE_URL = previousUrl;
  });

  test('CI treats mobile lint, audit, doctor and build as blocking gates', () => {
    const workflow = fs.readFileSync(
      path.join(repositoryRoot, '.github/workflows/ci.yml'),
      'utf8',
    );
    const mobileJob = workflow.split('\n  mobile:')[1].split('\n  frontend-audit:')[0];

    expect(mobileJob).toContain('run: npm run doctor');
    expect(mobileJob).toContain('run: npm audit --audit-level=high');
    expect(mobileJob).toContain('run: npm run lint');
    expect(mobileJob).toContain('run: npm run build');
    expect(mobileJob).not.toContain('Biome lint (advisory)');
  });

  test('source token checks ignore only generated mobile output', () => {
    const guard = fs.readFileSync(
      path.join(repositoryRoot, 'scripts/check-tokens-hex.sh'),
      'utf8',
    );

    for (const generatedDir of ['dist', '.expo', 'ios', 'android']) {
      expect(guard).toContain(`--exclude-dir=${generatedDir}`);
    }
  });
});
