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
    const app = readJson('app.json').expo;
    const splashPlugin = app.plugins.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === 'expo-splash-screen',
    );

    expect(app.splash).toBeUndefined();
    expect(splashPlugin).toBeDefined();

    const assetPaths = [app.icon, app.web.favicon, splashPlugin[1].image];
    for (const assetPath of assetPaths) {
      expect(fs.existsSync(path.resolve(root, assetPath))).toBe(true);
    }
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
