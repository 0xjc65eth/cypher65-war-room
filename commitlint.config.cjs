// commitlint — mensagens Conventional Commits (Issue #29 · quality)
// Rodado no CI (check) e recomendado no pre-commit. Alinhado ao padrão
// já usado no repo (feat/fix/docs/chore/refactor/test + escopo opcional).
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', [
      'feat', 'fix', 'docs', 'chore', 'refactor', 'test', 'perf', 'build', 'ci', 'style',
    ]],
    'header-max-length': [2, 'always', 100],
  },
};
