#!/usr/bin/env node
/**
 * dep_tree_js.js — Dependency tree analyzer for JS/TS packages.
 *
 * Usage:
 *   node dep_tree_js.js <project_path> <package_name> [--pkg-manager npm|yarn|pnpm|bun]
 *
 * Output: JSON. Schema mirrors dep_tree.py so the LLM can reuse Phase 2 logic.
 *   {
 *     "package_name": "lodash",
 *     "language": "javascript",
 *     "pkg_manager": "npm",
 *     "current_version": "4.17.20",
 *     "dependency_type": "direct" | "transitive" | "both" | "peer" | "unknown",
 *     "is_direct": bool,
 *     "is_transitive": bool,
 *     "is_peer": bool,
 *     "parent_packages": ["express", ...],
 *     "version_constraints": { "express": "^4.17.0", ... },  // parent -> constraint on target
 *     "declared_in": ["dependencies", "devDependencies", ...],
 *     "full_tree": <raw ls output>,
 *     "errors": []
 *   }
 *
 * No external npm deps required — uses child_process to call the project's
 * package manager and `fs` to read package.json directly.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function parseArgs(argv) {
    const args = { projectPath: argv[2], packageName: argv[3], pkgManager: null };
    for (let i = 4; i < argv.length; i++) {
        if (argv[i] === '--pkg-manager' && argv[i + 1]) {
            args.pkgManager = argv[i + 1];
            i++;
        }
    }
    return args;
}

function detectPkgManager(projectPath) {
    if (fs.existsSync(path.join(projectPath, 'bun.lock')) ||
        fs.existsSync(path.join(projectPath, 'bun.lockb'))) return 'bun';
    if (fs.existsSync(path.join(projectPath, 'pnpm-lock.yaml'))) return 'pnpm';
    if (fs.existsSync(path.join(projectPath, 'yarn.lock'))) return 'yarn';
    return 'npm';
}

function readManifest(projectPath) {
    const manifestPath = path.join(projectPath, 'package.json');
    if (!fs.existsSync(manifestPath)) {
        throw new Error(`package.json not found in ${projectPath}`);
    }
    return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
}

const DEP_FIELDS = [
    'dependencies',
    'devDependencies',
    'peerDependencies',
    'optionalDependencies',
];

function classifyDeclared(manifest, packageName) {
    const declaredIn = [];
    let declaredConstraint = null;
    for (const field of DEP_FIELDS) {
        if (manifest[field] && Object.prototype.hasOwnProperty.call(manifest[field], packageName)) {
            declaredIn.push(field);
            if (declaredConstraint === null) declaredConstraint = manifest[field][packageName];
        }
    }
    return { declaredIn, declaredConstraint };
}

function getTreeNpm(projectPath) {
    try {
        const out = execSync('npm ls --all --json', {
            cwd: projectPath,
            stdio: ['ignore', 'pipe', 'pipe'],
            maxBuffer: 1024 * 1024 * 128,
        }).toString();
        return { format: 'npm-json', data: JSON.parse(out) };
    } catch (err) {
        // npm ls returns non-zero when there are peer/optional warnings, but
        // still emits JSON on stdout.
        if (err.stdout && err.stdout.length > 0) {
            try {
                return { format: 'npm-json', data: JSON.parse(err.stdout.toString()) };
            } catch (_) { /* fall through */ }
        }
        return { format: 'npm-json', data: null, error: err.message };
    }
}

function getTreePnpm(projectPath) {
    try {
        const out = execSync('pnpm ls --depth Infinity --json', {
            cwd: projectPath,
            stdio: ['ignore', 'pipe', 'pipe'],
            maxBuffer: 1024 * 1024 * 128,
        }).toString();
        return { format: 'pnpm-json', data: JSON.parse(out) };
    } catch (err) {
        if (err.stdout && err.stdout.length > 0) {
            try {
                return { format: 'pnpm-json', data: JSON.parse(err.stdout.toString()) };
            } catch (_) { /* fall through */ }
        }
        return { format: 'pnpm-json', data: null, error: err.message };
    }
}

function getTreeYarn(projectPath) {
    // yarn v1: `yarn list --json` returns NDJSON
    // yarn berry: `yarn info --recursive --json` is preferred but `npm ls` works
    // because berry maintains node_modules in PnP-loose mode too.
    try {
        const out = execSync('yarn list --json --no-progress', {
            cwd: projectPath,
            stdio: ['ignore', 'pipe', 'pipe'],
            maxBuffer: 1024 * 1024 * 128,
        }).toString();
        // yarn v1 emits multiple JSON lines; the tree is the last "type":"tree" line
        const lines = out.split('\n').filter(Boolean);
        for (let i = lines.length - 1; i >= 0; i--) {
            try {
                const obj = JSON.parse(lines[i]);
                if (obj.type === 'tree') return { format: 'yarn-v1', data: obj.data };
            } catch (_) { /* skip non-json line */ }
        }
        return { format: 'yarn-v1', data: null, error: 'No tree found in yarn list output' };
    } catch (err) {
        return { format: 'yarn-v1', data: null, error: err.message };
    }
}

function getTreeBun(projectPath) {
    try {
        const out = execSync('bun pm ls --all', {
            cwd: projectPath,
            stdio: ['ignore', 'pipe', 'pipe'],
            maxBuffer: 1024 * 1024 * 128,
        }).toString();
        return { format: 'bun-text', raw: out };
    } catch (err) {
        return { format: 'bun-text', raw: '', error: err.message };
    }
}

function getInstalledVersion(projectPath, packageName) {
    // Most reliable: read node_modules/<pkg>/package.json
    const candidates = [
        path.join(projectPath, 'node_modules', packageName, 'package.json'),
    ];
    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            try {
                const pkg = JSON.parse(fs.readFileSync(candidate, 'utf8'));
                return pkg.version || 'unknown';
            } catch (_) { /* ignore */ }
        }
    }
    return 'unknown';
}

/**
 * Walk an npm/pnpm ls JSON tree and collect parents that depend on `target`.
 * Tree node shape: { version, dependencies: { <name>: <node> }, ... }
 */
function walkNpmTree(node, target, parents, constraints, parentName) {
    if (!node || typeof node !== 'object') return;
    const deps = node.dependencies || {};
    for (const [depName, depNode] of Object.entries(deps)) {
        if (depName === target) {
            if (parentName && !parents.includes(parentName)) {
                parents.push(parentName);
                // Try to surface the constraint that parent declared
                const peer = (depNode && depNode.peer) ? ' (peer)' : '';
                const required =
                    (depNode && depNode.required) ||
                    (depNode && depNode.from) ||
                    (depNode && depNode.version ? `==${depNode.version}` : '');
                constraints[parentName] = `${required}${peer}` || 'unknown';
            }
        }
        walkNpmTree(depNode, target, parents, constraints, depName);
    }
}

function walkPnpmTree(nodes, target, parents, constraints) {
    // pnpm ls emits an array of workspace-root entries; each has the same
    // shape as an npm node.
    if (!nodes) return;
    const list = Array.isArray(nodes) ? nodes : [nodes];
    for (const root of list) {
        walkNpmTree(root, target, parents, constraints, null);
    }
}

function walkYarnV1Tree(treeData, target, parents, constraints) {
    if (!treeData || !Array.isArray(treeData.trees)) return;
    function recurse(nodes, parentName) {
        for (const node of nodes) {
            // node.name like "lodash@4.17.20"
            const m = /^(@?[^@]+)@(.+)$/.exec(node.name || '');
            if (!m) continue;
            const [, name, version] = m;
            if (name === target && parentName && !parents.includes(parentName)) {
                parents.push(parentName);
                constraints[parentName] = `==${version}`;
            }
            if (Array.isArray(node.children) && node.children.length > 0) {
                recurse(node.children, name);
            }
        }
    }
    recurse(treeData.trees, null);
}

function parseBunText(raw, target, parents, constraints) {
    // bun pm ls --all output format (text):
    //   <indent>├── package@version
    // Track the most recent shallower-indent line as parent.
    if (!raw) return;
    const lines = raw.split('\n');
    const stack = []; // [{ indent, name }]
    for (const line of lines) {
        const m = /^(\s*)(?:[└├│─\s]+)?(@?[\w\-/.]+)@([^\s]+)/.exec(line);
        if (!m) continue;
        const [, indent, name] = m;
        const lvl = indent.length;
        while (stack.length > 0 && stack[stack.length - 1].indent >= lvl) {
            stack.pop();
        }
        const parent = stack.length > 0 ? stack[stack.length - 1].name : null;
        if (name === target && parent && !parents.includes(parent)) {
            parents.push(parent);
            constraints[parent] = 'unknown';
        }
        stack.push({ indent: lvl, name });
    }
}

function collectParents(tree, packageName) {
    const parents = [];
    const constraints = {};
    if (!tree || !tree.data && !tree.raw) return { parents, constraints };
    switch (tree.format) {
        case 'npm-json':
            walkNpmTree(tree.data, packageName, parents, constraints, null);
            break;
        case 'pnpm-json':
            walkPnpmTree(tree.data, packageName, parents, constraints);
            break;
        case 'yarn-v1':
            walkYarnV1Tree(tree.data, packageName, parents, constraints);
            break;
        case 'bun-text':
            parseBunText(tree.raw, packageName, parents, constraints);
            break;
    }
    return { parents, constraints };
}

function main() {
    const args = parseArgs(process.argv);
    if (!args.projectPath || !args.packageName) {
        process.stderr.write('Usage: node dep_tree_js.js <project_path> <package_name> [--pkg-manager npm|yarn|pnpm|bun]\n');
        process.exit(1);
    }

    const errors = [];
    const pkgManager = args.pkgManager || detectPkgManager(args.projectPath);
    let manifest;
    try {
        manifest = readManifest(args.projectPath);
    } catch (err) {
        process.stdout.write(JSON.stringify({
            package_name: args.packageName,
            language: 'javascript',
            pkg_manager: pkgManager,
            error: err.message,
        }, null, 2) + '\n');
        process.exit(1);
    }

    const { declaredIn, declaredConstraint } = classifyDeclared(manifest, args.packageName);

    let tree;
    switch (pkgManager) {
        case 'npm':  tree = getTreeNpm(args.projectPath); break;
        case 'pnpm': tree = getTreePnpm(args.projectPath); break;
        case 'yarn': tree = getTreeYarn(args.projectPath); break;
        case 'bun':  tree = getTreeBun(args.projectPath); break;
        default:     tree = { format: 'unknown', data: null, error: `Unknown pkg_manager: ${pkgManager}` };
    }
    if (tree.error) errors.push(`dep_tree: ${tree.error}`);

    const { parents, constraints } = collectParents(tree, args.packageName);
    const installedVersion = getInstalledVersion(args.projectPath, args.packageName);

    const isDirect = declaredIn.length > 0 && !declaredIn.every(f => f === 'peerDependencies');
    const isPeer = declaredIn.includes('peerDependencies');
    const isTransitive = parents.length > 0;

    let depType = 'unknown';
    if (isDirect && isTransitive) depType = 'both';
    else if (isDirect)            depType = 'direct';
    else if (isTransitive)        depType = 'transitive';
    else if (isPeer)              depType = 'peer';

    // If declared, surface the declared constraint as a "self" entry —
    // matches how Python's report wants to show "your project asks for X".
    if (declaredConstraint !== null) {
        constraints.__declared__ = declaredConstraint;
    }

    const result = {
        package_name: args.packageName,
        language: 'javascript',
        pkg_manager: pkgManager,
        current_version: installedVersion,
        dependency_type: depType,
        is_direct: isDirect,
        is_transitive: isTransitive,
        is_peer: isPeer,
        parent_packages: parents,
        version_constraints: constraints,
        declared_in: declaredIn,
        full_tree: tree.data || tree.raw || null,
        errors,
    };

    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main();
