#!/usr/bin/env node
/**
 * api_surface_diff_js.js — Diff the public API surface of an npm package
 * between two versions.
 *
 * Usage:
 *   node api_surface_diff_js.js <package_name> <old_version> <new_version>
 *
 * Strategy:
 *   1. `npm pack <pkg>@<ver>` into a tempdir for both versions.
 *   2. Locate the public type entry (package.json#types / typings / exports.types).
 *   3. If TS declarations exist: use ts-morph to enumerate exported declarations
 *      and signatures, then diff. This is the strongest signal.
 *   4. If no .d.ts: fall back to @babel/parser-based enumeration of
 *      `export` / `module.exports` from the JS entry (package.json#main / module).
 *
 * Output: JSON, structured so the LLM's Phase 3 logic can rank changes:
 *   {
 *     "package_name": "axios",
 *     "old_version": "0.27.2",
 *     "new_version": "1.6.0",
 *     "strategy": "dts" | "js" | "mixed",
 *     "old_source_label": "node_modules-like tarball, types entry: ./index.d.ts",
 *     "new_source_label": "...",
 *     "removed": [ { "name": "...", "kind": "function", "signature": "..." } ],
 *     "added":   [ ... ],
 *     "changed": [
 *       {
 *         "name": "create",
 *         "kind": "function",
 *         "old_signature": "(config?: AxiosRequestConfig) => AxiosInstance",
 *         "new_signature": "(config?: CreateAxiosDefaults) => AxiosInstance",
 *         "category": "signature_change" | "type_change" | "default_change"
 *       }
 *     ],
 *     "deprecated_new": [ { "name": "...", "reason": "JSDoc @deprecated" } ],
 *     "warnings": [ "..." ],
 *     "errors": []
 *   }
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

let tsMorph;
try {
    tsMorph = require('ts-morph');
} catch (err) {
    process.stderr.write(`WARNING: ts-morph not installed — falling back to JS-only enumeration (${err.message})\n`);
}

let parser;
try {
    parser = require('@babel/parser');
} catch (_) { /* JS fallback also degraded */ }

function npmPack(pkg, version, outDir) {
    const cwd = outDir;
    // `npm pack` downloads but doesn't install; outputs the tarball name on stdout.
    const tarball = execSync(`npm pack ${pkg}@${version} --silent`, {
        cwd, stdio: ['ignore', 'pipe', 'pipe'],
    }).toString().trim().split('\n').pop();
    const tarballPath = path.join(cwd, tarball);
    const extractDir = path.join(cwd, 'extracted');
    fs.mkdirSync(extractDir, { recursive: true });
    execSync(`tar -xzf "${tarballPath}" -C "${extractDir}"`, { stdio: 'ignore' });
    // npm tarballs always extract to a top-level `package/` directory.
    return path.join(extractDir, 'package');
}

function readPkgJson(rootDir) {
    return JSON.parse(fs.readFileSync(path.join(rootDir, 'package.json'), 'utf8'));
}

/**
 * Best-effort: resolve the package's TS types entry. Returns absolute path
 * to a .d.ts file, or null.
 */
function resolveTypesEntry(rootDir, manifest) {
    const candidates = [];
    if (manifest.types) candidates.push(manifest.types);
    if (manifest.typings) candidates.push(manifest.typings);
    // exports.types
    if (manifest.exports && typeof manifest.exports === 'object') {
        const exp = manifest.exports['.'] || manifest.exports;
        if (exp && typeof exp === 'object') {
            if (exp.types) candidates.push(exp.types);
            if (exp.import && typeof exp.import === 'object' && exp.import.types) candidates.push(exp.import.types);
            if (exp.default && typeof exp.default === 'object' && exp.default.types) candidates.push(exp.default.types);
        }
    }
    // Conventional fallback: index.d.ts next to main
    if (manifest.main) {
        const dts = manifest.main.replace(/\.(c?js|mjs)$/, '.d.ts');
        candidates.push(dts);
    }
    candidates.push('index.d.ts', 'dist/index.d.ts', 'types/index.d.ts');

    for (const candidate of candidates) {
        if (!candidate) continue;
        const full = path.join(rootDir, candidate);
        if (fs.existsSync(full) && full.endsWith('.d.ts')) return full;
    }
    return null;
}

function resolveJsEntry(rootDir, manifest) {
    const candidates = [
        manifest.module,
        manifest.main,
        'index.js', 'index.mjs', 'index.cjs', 'dist/index.js',
    ];
    for (const candidate of candidates) {
        if (!candidate) continue;
        const full = path.join(rootDir, candidate);
        if (fs.existsSync(full)) return full;
    }
    return null;
}

/* ---------- TS / .d.ts surface enumeration via ts-morph ---------- */

function enumerateTsExports(dtsPath) {
    if (!tsMorph) return null;
    const project = new tsMorph.Project({
        compilerOptions: {
            allowJs: false,
            declaration: true,
            noEmit: true,
            skipLibCheck: true,
            target: tsMorph.ScriptTarget?.ES2020 ?? 99,
            moduleResolution: 2, // NodeJs
        },
        useInMemoryFileSystem: false,
    });
    let sourceFile;
    try {
        sourceFile = project.addSourceFileAtPath(dtsPath);
    } catch (err) {
        return { error: `ts-morph addSourceFile failed: ${err.message}` };
    }

    const exported = {};
    const exportSymbols = sourceFile.getExportSymbols();
    for (const sym of exportSymbols) {
        const name = sym.getName();
        const decls = sym.getDeclarations();
        if (!decls || decls.length === 0) {
            exported[name] = { kind: 'unknown', signature: '' };
            continue;
        }
        const decl = decls[0];
        let kind = decl.getKindName().replace(/Declaration$/, '').toLowerCase();
        let signature = '';
        let deprecated = false;
        try {
            const jsdoc = decl.getJsDocs ? decl.getJsDocs() : [];
            if (jsdoc && jsdoc.length > 0) {
                for (const doc of jsdoc) {
                    if (doc.getTags && doc.getTags().some(t => t.getTagName() === 'deprecated')) {
                        deprecated = true;
                    }
                }
            }
        } catch (_) { /* ignore */ }

        try {
            // Try to get a compact textual signature.
            if (decl.getType) {
                signature = decl.getType().getText(decl, tsMorph.TypeFormatFlags?.NoTruncation ?? 0);
            }
            if (!signature || signature.length > 600) {
                // Fallback to the first 200 chars of the declaration text
                signature = decl.getText().slice(0, 600);
            }
        } catch (_) {
            try { signature = decl.getText().slice(0, 600); } catch (_) { /* */ }
        }

        exported[name] = { kind, signature, deprecated };
    }
    return { exports: exported };
}

/* ---------- JS surface enumeration via @babel/parser fallback ---------- */

function enumerateJsExports(jsPath) {
    if (!parser) return null;
    let source;
    try { source = fs.readFileSync(jsPath, 'utf8'); } catch (_) { return null; }
    let ast;
    try {
        ast = parser.parse(source, {
            sourceType: 'unambiguous',
            errorRecovery: true,
            plugins: ['jsx', 'typescript', 'decorators-legacy', 'classProperties'],
        });
    } catch (err) {
        return { error: `babel parse failed: ${err.message}` };
    }
    const exported = {};
    function add(name, info) {
        if (!name) return;
        exported[name] = info;
    }
    for (const node of ast.program.body) {
        switch (node.type) {
            case 'ExportNamedDeclaration': {
                if (node.declaration) {
                    if (node.declaration.type === 'VariableDeclaration') {
                        for (const d of node.declaration.declarations) {
                            if (d.id.type === 'Identifier') {
                                add(d.id.name, { kind: 'const', signature: '' });
                            }
                        }
                    } else if (node.declaration.id && node.declaration.id.name) {
                        const kind = node.declaration.type
                            .replace(/Declaration$/, '').toLowerCase();
                        add(node.declaration.id.name, { kind, signature: '' });
                    }
                }
                for (const spec of node.specifiers || []) {
                    const name = spec.exported && spec.exported.name;
                    add(name, { kind: 're-export', signature: '' });
                }
                break;
            }
            case 'ExportDefaultDeclaration': {
                add('default', { kind: 'default', signature: '' });
                break;
            }
            case 'ExpressionStatement': {
                const expr = node.expression;
                if (expr.type === 'AssignmentExpression' && expr.operator === '=') {
                    const left = expr.left;
                    // module.exports = ...
                    if (left.type === 'MemberExpression' &&
                        left.object.name === 'module' &&
                        left.property.name === 'exports') {
                        add('default', { kind: 'cjs_module_exports', signature: '' });
                    }
                    // exports.X = ... | module.exports.X = ...
                    if (left.type === 'MemberExpression' &&
                        (left.object.name === 'exports' ||
                         (left.object.type === 'MemberExpression' &&
                          left.object.object.name === 'module' &&
                          left.object.property.name === 'exports'))) {
                        const name = left.property.name || left.property.value;
                        add(name, { kind: 'cjs_named', signature: '' });
                    }
                }
                break;
            }
        }
    }
    return { exports: exported };
}

/* ---------- Diff ---------- */

function diffExports(oldExports, newExports) {
    const removed = [];
    const added = [];
    const changed = [];
    const deprecated_new = [];

    for (const name of Object.keys(oldExports)) {
        if (!(name in newExports)) {
            removed.push({ name, kind: oldExports[name].kind, signature: oldExports[name].signature });
        } else {
            const o = oldExports[name];
            const n = newExports[name];
            if ((o.signature || '') !== (n.signature || '')) {
                let category = 'type_change';
                if (o.kind !== n.kind) category = 'kind_change';
                else if (/\([^)]*\) =>/.test(o.signature || '')) category = 'signature_change';
                changed.push({
                    name,
                    kind: n.kind,
                    old_signature: o.signature,
                    new_signature: n.signature,
                    category,
                });
            }
            if (!o.deprecated && n.deprecated) {
                deprecated_new.push({ name, reason: 'JSDoc @deprecated added' });
            }
        }
    }
    for (const name of Object.keys(newExports)) {
        if (!(name in oldExports)) {
            added.push({ name, kind: newExports[name].kind, signature: newExports[name].signature });
        }
    }
    return { removed, added, changed, deprecated_new };
}

/* ---------- Orchestration ---------- */

function buildSurface(rootDir) {
    const manifest = readPkgJson(rootDir);
    const dtsPath = resolveTypesEntry(rootDir, manifest);
    if (dtsPath) {
        const result = enumerateTsExports(dtsPath);
        if (result && result.exports) {
            return { strategy: 'dts', source: dtsPath, exports: result.exports };
        }
        if (result && result.error) {
            // fall through to JS
        }
    }
    const jsPath = resolveJsEntry(rootDir, manifest);
    if (jsPath) {
        const result = enumerateJsExports(jsPath);
        if (result && result.exports) {
            return { strategy: 'js', source: jsPath, exports: result.exports };
        }
    }
    return { strategy: 'none', source: null, exports: {} };
}

function main() {
    const [, , packageName, oldVer, newVer] = process.argv;
    if (!packageName || !oldVer || !newVer) {
        process.stderr.write('Usage: node api_surface_diff_js.js <package_name> <old_version> <new_version>\n');
        process.exit(1);
    }

    const warnings = [];
    const errors = [];

    const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'apidiff-'));
    const oldDir = fs.mkdtempSync(path.join(workDir, 'old-'));
    const newDir = fs.mkdtempSync(path.join(workDir, 'new-'));
    let oldRoot, newRoot;
    try {
        oldRoot = npmPack(packageName, oldVer, oldDir);
        newRoot = npmPack(packageName, newVer, newDir);
    } catch (err) {
        process.stdout.write(JSON.stringify({
            package_name: packageName,
            old_version: oldVer,
            new_version: newVer,
            strategy: 'error',
            errors: [`npm pack failed: ${err.message}`],
        }, null, 2) + '\n');
        process.exit(1);
    }

    const oldSurface = buildSurface(oldRoot);
    const newSurface = buildSurface(newRoot);

    if (oldSurface.strategy !== newSurface.strategy) {
        warnings.push(`Strategy mismatch: old=${oldSurface.strategy}, new=${newSurface.strategy}. Diff may be noisy.`);
    }
    if (oldSurface.strategy === 'none' || newSurface.strategy === 'none') {
        errors.push('Could not enumerate exports for one or both versions.');
    }

    const { removed, added, changed, deprecated_new } =
        diffExports(oldSurface.exports || {}, newSurface.exports || {});

    process.stdout.write(JSON.stringify({
        package_name: packageName,
        old_version: oldVer,
        new_version: newVer,
        strategy: oldSurface.strategy === newSurface.strategy ? oldSurface.strategy : 'mixed',
        old_source_label: oldSurface.source,
        new_source_label: newSurface.source,
        removed,
        added,
        changed,
        deprecated_new,
        warnings,
        errors,
    }, null, 2) + '\n');

    // best-effort cleanup
    try { fs.rmSync(workDir, { recursive: true, force: true }); } catch (_) { /* */ }
}

main();
