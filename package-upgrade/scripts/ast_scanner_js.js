#!/usr/bin/env node
/**
 * ast_scanner_js.js — Scan JS/TS project for usage of a target package.
 *
 * Usage:
 *   node ast_scanner_js.js <project_path> <package_name>
 *
 * Output: JSON with the same top-level shape as ast_scanner.py so the LLM's
 * Phase 4 logic can be reused:
 *   {
 *     "scan_results": [
 *       {
 *         "file": "src/api/client.ts",
 *         "imports": [
 *           { "type": "esm_default", "module": "axios", "alias": "axios",
 *             "line": 3, "context": "..." }, ...
 *         ],
 *         "usages": [
 *           { "symbol": "axios.get", "line": 12, "context": "..." }, ...
 *         ]
 *       }, ...
 *     ],
 *     "total_files": N,
 *     "package_name": "axios",
 *     "language": "javascript"
 *   }
 *
 * Import patterns covered:
 *   ESM:  import X from 'pkg'                  -> esm_default
 *         import { Y as Z } from 'pkg'         -> esm_named (records original Y)
 *         import * as ns from 'pkg'            -> esm_namespace
 *         import 'pkg'                         -> esm_side_effect
 *         import type { T } from 'pkg'         -> esm_type_only (flagged)
 *   CJS:  const X = require('pkg')             -> cjs_default
 *         const { Y } = require('pkg')         -> cjs_destructure
 *   Dyn:  await import('pkg')                  -> dynamic
 *
 * Submodule imports ('pkg/foo/bar') are also matched and recorded with the
 * full submodule path so Phase 3 can distinguish "deep import" usage.
 */

'use strict';

const fs = require('fs');
const path = require('path');

let parser, traverse;
try {
    parser = require('@babel/parser');
    traverse = require('@babel/traverse').default;
} catch (err) {
    process.stderr.write(
        'ERROR: @babel/parser / @babel/traverse not installed.\n' +
        'Run: cd <skill-dir>/scripts && npm install\n' +
        `(${err.message})\n`
    );
    process.exit(2);
}

const SKIP_DIRS = new Set([
    'node_modules', '.git', 'dist', 'build', 'out', '.next', '.nuxt',
    '.cache', 'coverage', '.turbo', '.parcel-cache',
]);
const SOURCE_EXTS = new Set(['.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx']);

function isTargetModule(modulePath, packageName) {
    if (!modulePath || typeof modulePath !== 'string') return false;
    if (modulePath === packageName) return true;
    if (modulePath.startsWith(`${packageName}/`)) return true;
    return false;
}

function getContext(sourceLines, lineno, radius = 5) {
    const start = Math.max(0, lineno - radius - 1);
    const end = Math.min(sourceLines.length, lineno + radius);
    const lines = sourceLines.slice(start, end);
    return lines.map((line, i) =>
        `${String(start + i + 1).padStart(4, ' ')} | ${line}`
    ).join('\n');
}

function parseFile(filepath, source) {
    const ext = path.extname(filepath);
    const isTS = ext === '.ts' || ext === '.tsx';
    const isJSX = ext === '.jsx' || ext === '.tsx';
    const plugins = [];
    if (isTS) plugins.push('typescript');
    if (isJSX) plugins.push('jsx');
    // Permissive plugin set that covers most real-world code.
    plugins.push('decorators-legacy', 'classProperties', 'topLevelAwait', 'importAttributes');
    try {
        return parser.parse(source, {
            sourceType: 'unambiguous',
            allowReturnOutsideFunction: true,
            allowImportExportEverywhere: true,
            allowAwaitOutsideFunction: true,
            errorRecovery: true,
            plugins,
        });
    } catch (err) {
        // Fallback: try without TS/JSX plugins if a syntax we don't understand trips parsing
        try {
            return parser.parse(source, {
                sourceType: 'unambiguous',
                errorRecovery: true,
                plugins: ['jsx'],
            });
        } catch (_) {
            return null;
        }
    }
}

function scanFile(filepath, packageName) {
    let source;
    try {
        source = fs.readFileSync(filepath, 'utf8');
    } catch (_) {
        return null;
    }
    const ast = parseFile(filepath, source);
    if (!ast) return null;
    const sourceLines = source.split('\n');

    const imports = [];
    const usages = [];
    // localName -> { sourceModule, originalSymbol, importType }
    const importedNames = new Map();
    let hasMatch = false;

    function recordImport(entry, localName, info) {
        imports.push(entry);
        if (localName && info) {
            importedNames.set(localName, info);
        }
        hasMatch = true;
    }

    traverse(ast, {
        // import X from 'pkg' | import { Y } from 'pkg' | import * as ns from 'pkg' | import 'pkg'
        ImportDeclaration(p) {
            const node = p.node;
            const source = node.source.value;
            if (!isTargetModule(source, packageName)) return;
            const lineno = node.loc ? node.loc.start.line : 0;
            const ctx = getContext(sourceLines, lineno);

            if (node.specifiers.length === 0) {
                recordImport({
                    type: 'esm_side_effect',
                    module: source,
                    line: lineno,
                    context: ctx,
                }, null, null);
                return;
            }

            for (const spec of node.specifiers) {
                const isTypeOnly = node.importKind === 'type' || spec.importKind === 'type';
                if (spec.type === 'ImportDefaultSpecifier') {
                    recordImport({
                        type: isTypeOnly ? 'esm_type_only' : 'esm_default',
                        module: source,
                        local: spec.local.name,
                        line: lineno,
                        context: ctx,
                    }, spec.local.name, { sourceModule: source, originalSymbol: 'default', importType: 'esm_default' });
                } else if (spec.type === 'ImportNamespaceSpecifier') {
                    recordImport({
                        type: isTypeOnly ? 'esm_type_only' : 'esm_namespace',
                        module: source,
                        local: spec.local.name,
                        line: lineno,
                        context: ctx,
                    }, spec.local.name, { sourceModule: source, originalSymbol: '*', importType: 'esm_namespace' });
                } else if (spec.type === 'ImportSpecifier') {
                    const original = spec.imported.type === 'Identifier'
                        ? spec.imported.name
                        : spec.imported.value;
                    recordImport({
                        type: isTypeOnly ? 'esm_type_only' : 'esm_named',
                        module: source,
                        imported: original,
                        local: spec.local.name,
                        line: lineno,
                        context: ctx,
                    }, spec.local.name, { sourceModule: source, originalSymbol: original, importType: 'esm_named' });
                }
            }
        },

        // const X = require('pkg') | const { Y } = require('pkg')
        VariableDeclarator(p) {
            const node = p.node;
            if (!node.init) return;
            // Match require('pkg') and require('pkg/sub')
            if (node.init.type !== 'CallExpression') return;
            const callee = node.init.callee;
            if (!callee || callee.name !== 'require') return;
            const arg = node.init.arguments[0];
            if (!arg || arg.type !== 'StringLiteral') return;
            if (!isTargetModule(arg.value, packageName)) return;
            const lineno = node.loc ? node.loc.start.line : 0;
            const ctx = getContext(sourceLines, lineno);

            if (node.id.type === 'Identifier') {
                recordImport({
                    type: 'cjs_default',
                    module: arg.value,
                    local: node.id.name,
                    line: lineno,
                    context: ctx,
                }, node.id.name, { sourceModule: arg.value, originalSymbol: 'module.exports', importType: 'cjs_default' });
            } else if (node.id.type === 'ObjectPattern') {
                for (const prop of node.id.properties) {
                    if (prop.type !== 'ObjectProperty') continue;
                    const keyName = prop.key.type === 'Identifier' ? prop.key.name : prop.key.value;
                    const localName = prop.value.type === 'Identifier' ? prop.value.name : keyName;
                    recordImport({
                        type: 'cjs_destructure',
                        module: arg.value,
                        imported: keyName,
                        local: localName,
                        line: lineno,
                        context: ctx,
                    }, localName, { sourceModule: arg.value, originalSymbol: keyName, importType: 'cjs_destructure' });
                }
            }
        },

        // import('pkg') dynamic
        CallExpression(p) {
            const node = p.node;
            if (node.callee.type === 'Import') {
                const arg = node.arguments[0];
                if (arg && arg.type === 'StringLiteral' && isTargetModule(arg.value, packageName)) {
                    const lineno = node.loc ? node.loc.start.line : 0;
                    imports.push({
                        type: 'dynamic',
                        module: arg.value,
                        line: lineno,
                        context: getContext(sourceLines, lineno),
                    });
                    hasMatch = true;
                }
            }
            // require.resolve('pkg')
            if (node.callee.type === 'MemberExpression' &&
                node.callee.object.name === 'require' &&
                node.callee.property.name === 'resolve') {
                const arg = node.arguments[0];
                if (arg && arg.type === 'StringLiteral' && isTargetModule(arg.value, packageName)) {
                    const lineno = node.loc ? node.loc.start.line : 0;
                    imports.push({
                        type: 'cjs_resolve',
                        module: arg.value,
                        line: lineno,
                        context: getContext(sourceLines, lineno),
                    });
                    hasMatch = true;
                }
            }
        },
    });

    // Second pass: track usage sites for every localName we recorded.
    if (importedNames.size > 0) {
        traverse(ast, {
            MemberExpression(p) {
                const node = p.node;
                // Build chain: a.b.c.d -> "a.b.c.d"
                const chain = [];
                let cur = node;
                while (cur && cur.type === 'MemberExpression') {
                    if (cur.property.type === 'Identifier') chain.unshift(cur.property.name);
                    else if (cur.property.type === 'StringLiteral') chain.unshift(cur.property.value);
                    cur = cur.object;
                }
                if (!cur || cur.type !== 'Identifier') return;
                const root = cur.name;
                const info = importedNames.get(root);
                if (!info) return;
                const lineno = node.loc ? node.loc.start.line : 0;
                // Symbol: <pkg>.<originalSymbol>.<chain...> when default/namespace;
                // for named imports the chain hangs directly off the original symbol.
                let symbol;
                if (info.importType === 'esm_namespace') {
                    symbol = `${info.sourceModule}.${chain.join('.')}`;
                } else if (info.originalSymbol === 'default' || info.originalSymbol === 'module.exports') {
                    symbol = `${info.sourceModule}.default${chain.length ? '.' + chain.join('.') : ''}`;
                } else {
                    symbol = `${info.sourceModule}.${info.originalSymbol}${chain.length ? '.' + chain.join('.') : ''}`;
                }
                usages.push({
                    symbol,
                    line: lineno,
                    context: getContext(sourceLines, lineno),
                });
            },
            Identifier(p) {
                // Only count "referenced" identifiers: usages, not binding
                // sites. @babel/traverse provides isReferencedIdentifier()
                // which already filters out import specifiers, declaration
                // patterns, object keys, etc.
                if (!p.isReferencedIdentifier()) return;
                // MemberExpression roots are handled by the MemberExpression
                // visitor above — skip to avoid duplicates.
                if (p.parent && p.parent.type === 'MemberExpression' && p.parent.object === p.node) return;
                const node = p.node;
                const info = importedNames.get(node.name);
                if (!info) return;
                const lineno = node.loc ? node.loc.start.line : 0;
                let symbol;
                if (info.originalSymbol === 'default' || info.originalSymbol === 'module.exports') {
                    symbol = `${info.sourceModule}.default`;
                } else if (info.originalSymbol === '*') {
                    symbol = `${info.sourceModule}.*`;
                } else {
                    symbol = `${info.sourceModule}.${info.originalSymbol}`;
                }
                usages.push({
                    symbol,
                    line: lineno,
                    context: getContext(sourceLines, lineno),
                });
            },
        });
    }

    if (!hasMatch) return null;
    return { file: filepath, imports, usages };
}

function walkProject(projectPath, packageName, results) {
    let entries;
    try {
        entries = fs.readdirSync(projectPath, { withFileTypes: true });
    } catch (_) {
        return;
    }
    for (const entry of entries) {
        if (entry.name.startsWith('.')) continue;
        const full = path.join(projectPath, entry.name);
        if (entry.isDirectory()) {
            if (SKIP_DIRS.has(entry.name)) continue;
            walkProject(full, packageName, results);
        } else if (entry.isFile()) {
            const ext = path.extname(entry.name);
            // Skip .d.ts in the project — those are type re-exports, not usage
            if (entry.name.endsWith('.d.ts')) continue;
            if (!SOURCE_EXTS.has(ext)) continue;
            const res = scanFile(full, packageName);
            if (res) results.push(res);
        }
    }
}

function main() {
    const [, , projectPath, packageName] = process.argv;
    if (!projectPath || !packageName) {
        process.stderr.write('Usage: node ast_scanner_js.js <project_path> <package_name>\n');
        process.exit(1);
    }
    const results = [];
    walkProject(projectPath, packageName, results);
    process.stdout.write(JSON.stringify({
        scan_results: results,
        total_files: results.length,
        package_name: packageName,
        language: 'javascript',
    }, null, 2) + '\n');
}

main();
