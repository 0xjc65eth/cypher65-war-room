#!/usr/bin/env node
/**
 * build_app_js.cjs — gera `static/app.js` a partir de `static/src/*.js`
 * =====================================================================
 * Issue #489 · Opção A do RFC #478 (docs/rfc/478-god-files-decomposition.md)
 *
 * Zero bundler, zero dependências, zero transformação: o build é uma
 * CONCATENAÇÃO na ordem do MANIFEST. O resultado continua sendo UM arquivo
 * servido por UMA tag (`<script src="/static/app.js?vNN" defer>`), então
 * cache-bust, `node --check` e todos os guards que escaneiam `static/app.js`
 * (DOM/XSS, tokens-hex, a11y) seguem valendo sem alteração.
 *
 * A ordem do MANIFEST reproduz exatamente a ordem lexical dos blocos no
 * arquivo original — por isso hoisting e TDZ não mudam: o IIFE único abre no
 * primeiro fragmento e fecha no último.
 *
 * Invariantes — falham o build, nunca silenciam:
 *   1. ÓRFÃO   — todo `.js` em `static/src/` precisa estar no MANIFEST. Um
 *                fragmento fora do manifest nunca chegaria ao navegador e
 *                escaparia de TODOS os guards, que leem só `static/app.js`.
 *   2. AUSENTE — todo arquivo do MANIFEST precisa existir em disco.
 *   3. DRIFT   — em `--check`, o `static/app.js` commitado precisa ser
 *                byte-idêntico ao build. Editar o artefato à mão quebra o CI.
 *
 * Uso:
 *   node scripts/build_app_js.cjs           # escreve static/app.js
 *   node scripts/build_app_js.cjs --check   # exit 1 se houver drift (CI)
 *   node scripts/build_app_js.cjs --stdout  # imprime o build (debug)
 *
 * Exit: 0 ok · 1 violação/drift · 2 erro de execução
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(ROOT, 'static', 'src');
const OUT_FILE = path.join(ROOT, 'static', 'app.js');

/**
 * Ordem canônica dos fragmentos. Ela É a ordem de execução do IIFE — mexer
 * aqui é mexer no runtime do dashboard. Cada entrada corresponde a um domínio
 * extraído (ou, provisoriamente, ao trecho que ainda será extraído).
 */
const MANIFEST = [
  '00-preamble.js',
  '10-core-fmt.js',
  '20-dom-primitives.js',
  '30-core-escape.js',
  '40-app-logic.js',
  '45-market.js',
  '46-rentals.js',
  '47-admin.js',
  '50-close.js',
];

function build() {
  if (!fs.existsSync(SRC_DIR)) {
    throw new Error(`diretório de fontes ausente: ${path.relative(ROOT, SRC_DIR)}`);
  }

  const present = fs
    .readdirSync(SRC_DIR)
    .filter((name) => name.endsWith('.js'))
    .sort();

  const orphans = present.filter((name) => !MANIFEST.includes(name));
  if (orphans.length > 0) {
    throw new Error(
      'fragmento órfão em static/src/ (não está no MANIFEST, nunca chegaria ao navegador):\n' +
        orphans.map((name) => `  - ${name}`).join('\n') +
        '\nAdicione ao MANIFEST de scripts/build_app_js.cjs na posição correta de execução.'
    );
  }

  const missing = MANIFEST.filter((name) => !present.includes(name));
  if (missing.length > 0) {
    throw new Error(
      'arquivo do MANIFEST ausente em static/src/:\n' +
        missing.map((name) => `  - ${name}`).join('\n')
    );
  }

  return MANIFEST.map((name) => {
    const file = path.join(SRC_DIR, name);
    const body = fs.readFileSync(file, 'utf8');
    if (body.length === 0) {
      throw new Error(`fragmento vazio: static/src/${name}`);
    }
    return body;
  }).join('');
}

function main() {
  const args = new Set(process.argv.slice(2));

  let output;
  try {
    output = build();
  } catch (err) {
    console.error(`❌ [build_app_js] ${err.message}`);
    process.exit(1);
  }

  if (args.has('--stdout')) {
    process.stdout.write(output);
    return;
  }

  const current = fs.existsSync(OUT_FILE) ? fs.readFileSync(OUT_FILE, 'utf8') : null;

  if (args.has('--check')) {
    if (current === output) {
      console.log(
        `✅ [build_app_js] static/app.js está em sincronia com static/src/ (${MANIFEST.length} fragmentos)`
      );
      return;
    }
    const lines = output.split('\n').length;
    console.error(
      '❌ [build_app_js] DRIFT: static/app.js não corresponde ao build de static/src/.\n' +
        '   static/app.js é um ARTEFATO GERADO — não edite à mão.\n' +
        '   Edite o fragmento em static/src/ e rode: node scripts/build_app_js.cjs\n' +
        `   (build atual = ${lines} linhas)`
    );
    process.exit(1);
  }

  if (current === output) {
    console.log('✅ [build_app_js] static/app.js já está atualizado (nada a escrever)');
    return;
  }

  fs.writeFileSync(OUT_FILE, output);
  console.log(
    `✅ [build_app_js] static/app.js gerado — ${MANIFEST.length} fragmentos, ${output.split('\n').length} linhas`
  );
}

main();
