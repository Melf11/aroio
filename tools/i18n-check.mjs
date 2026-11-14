// Lists German UI texts (t('…') keys) that have no English entry yet.
//   node tools/i18n-check.mjs [--write]   --write appends empty stubs to en.js
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'src');
const files = [];
(function walk(d) { for (const f of readdirSync(d)) { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : /\.(svelte|js)$/.test(f) && files.push(p); } })(root);
const keys = new Set();
const re = /\bt\(\s*(['"])((?:\\.|(?!\1).)*)\1/g;
for (const f of files) for (const m of readFileSync(f, 'utf8').matchAll(re)) keys.add(m[2].replace(/\\'/g, "'"));
const en = (await import(join(root, 'lib', 'en.js'))).default;
const missing = [...keys].filter((k) => !(k in en)).sort();
console.log(`i18n: ${keys.size} Texte, ${keys.size - missing.length} übersetzt, ${missing.length} ohne Englisch.`);
if (process.argv.includes('--list')) for (const k of missing) console.log('  ' + k);
