#!/usr/bin/env node
/**
 * dep_tree_js.js — Dependency tree analyzer for JS/TS packages.
 *
 * Usage:
 *   node dep_tree_js.js <project_path> <package_name> [--pkg-manager npm|yarn|pnpm|bun]
 *
 * Strategy (lockfile-first — IMPROVEMENTS #5):
 *   1. If a lockfile exists, parse it directly. This works even when
 *      node_modules/ is absent (Yarn 3 PnP / fresh checkout / CI-only install).
 *   2. Fall back to `<pm> ls --json` only when no lockfile is found.
 *
 * Output schema mirrors dep_tree.py so Phase 2 LLM logic stays shared:
 *   {
 *     "package_name": "lodash",
 *     "language": "javascript",
 *     "pkg_manager": "yarn",
 *     "current_version": "4.17.20",
 *     "dependency_type": "direct" | "transitive" | "both" | "peer" | "unknown",
 *     "is_direct": bool,
 *     "is_transitive": bool,
 *     "is_peer": bool,
 *     "parent_packages": ["express", ...],
 *     "version_constraints": { "express": "^4.17.0", "__declared__": "..." },
 *     "declared_in": ["dependencies", "devDependencies", ...],
 *     "source": "yarn3-lock" | "yarn1-lock" | "pnpm-lock" | "npm-lock" | "npm-ls" | "yarn-list",
 *     "full_tree": <raw>,
 *     "errors": []
 *   }
 *
 * No external npm deps required for lockfile parsing — uses custom parsers
 * for the YAML-ish formats (yarn 3 lockfile is YAML with key quirks; pnpm
 * lockfile is regular YAML but the small subset we need is parseable with
 * a hand-rolled reader).
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

function detectLockfile(projectPath) {
    const candidates = [
        ['yarn.lock',          'yarn'],
        ['pnpm-lock.yaml',     'pnpm'],
        ['package-lock.json',  'npm'],
        ['npm-shrinkwrap.json','npm'],
        ['bun.lock',           'bun'],
        ['bun.lockb',          'bun'],
    ];
    for (const [name, pm] of candidates) {
        const full = path.join(projectPath, name);
        if (fs.existsSync(full)) return { path: full, pm, name };
    }
    return null;
}

function detectPkgManager(projectPath) {
    const lf = detectLockfile(projectPath);
    return lf ? lf.pm : 'npm';
}

function readManifest(projectPath) {
    const manifestPath = path.join(projectPath, 'package.json');
    if (!fs.existsSync(manifestPath)) {
        throw new Error(`package.json not found in ${projectPath}`);
    }
    return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
}

const DEP_FIELDS = [
    'dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies',
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

/**
 * Look for the target in package.json's transitive-pinning fields:
 *   - npm:   `overrides`
 *   - yarn:  `resolutions`
 *   - pnpm:  `pnpm.overrides`
 *
 * These let the user pin a transitive dep's version without bumping the
 * parent. Per user feedback we MUST surface these to the LLM so it picks
 * "bump the pin" over "hand-edit the lockfile".
 *
 * The match logic is conservative: top-level key equals target name, OR
 * any nested key path ends in target. (overrides supports nested form like
 * `{"foo": {"bar": "1.0"}}` which means bar gets pinned under foo.)
 */
function findOverridesPin(manifest, packageName) {
    const result = { overrides: null, resolutions: null, pnpm_overrides: null };

    function searchObj(obj, kind) {
        if (!obj || typeof obj !== 'object') return null;
        // Top-level direct match
        if (Object.prototype.hasOwnProperty.call(obj, packageName)) {
            const val = obj[packageName];
            return { kind, key: packageName, value: typeof val === 'string' ? val : JSON.stringify(val) };
        }
        // Nested: any key whose value is an object that contains packageName
        for (const [k, v] of Object.entries(obj)) {
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                if (Object.prototype.hasOwnProperty.call(v, packageName)) {
                    const inner = v[packageName];
                    return {
                        kind,
                        key: `${k}.${packageName}`,
                        value: typeof inner === 'string' ? inner : JSON.stringify(inner),
                    };
                }
            }
        }
        return null;
    }

    result.overrides      = searchObj(manifest.overrides, 'npm-overrides');
    result.resolutions    = searchObj(manifest.resolutions, 'yarn-resolutions');
    result.pnpm_overrides = searchObj(manifest.pnpm && manifest.pnpm.overrides, 'pnpm-overrides');
    return result;
}

/* ============================================================
 * Lockfile parsers
 *
 * Each parser returns:
 *   { entries: [{ name, version, dependencies: {name: range}, peers: {name: range} }],
 *     locator_to_resolved: Map<string, string> }
 * ============================================================ */

/** Detect whether a yarn.lock is yarn 1 (legacy) or yarn 2/3 (Berry).
 * Berry lockfiles start with `# This file is generated by running "yarn install"`
 * and contain `__metadata:` keys. */
function isYarnBerry(text) {
    return /^__metadata:/m.test(text) || /\n__metadata:\n/.test(text);
}

/**
 * Parse a yarn 2/3 (Berry) lockfile.
 * Format example (YAML-ish):
 *   "@scope/pkg@npm:^1.0.0":
 *     version: 1.2.3
 *     resolution: "@scope/pkg@npm:1.2.3"
 *     dependencies:
 *       lodash: ^4.17.0
 *     peerDependencies:
 *       react: ^18
 *     checksum: ...
 */
function parseYarnBerry(text) {
    const entries = [];
    // Split into entry blocks. Each entry starts at column-0 with a key line ending in ':'
    const lines = text.split('\n');
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        // Skip blank / comment / __metadata
        if (!line || line.startsWith('#') || /^\s/.test(line) || line.startsWith('__metadata:')) {
            i++; continue;
        }
        // Entry header: e.g. `"lodash@npm:^4.17.0":` or `"@scope/pkg@npm:^1.0.0, @scope/pkg@npm:^1.1.0":`
        const headerMatch = /^("?)(.+?)\1:\s*$/.exec(line);
        if (!headerMatch) { i++; continue; }
        const locators = headerMatch[2].split(',').map(s => s.trim().replace(/^"|"$/g, ''));

        const entry = {
            locators,
            version: '',
            resolution: '',
            dependencies: {},
            peerDependencies: {},
        };

        i++;
        // Read indented body
        while (i < lines.length && /^\s/.test(lines[i])) {
            const bodyLine = lines[i];
            const trimmed = bodyLine.trim();
            if (!trimmed) { i++; continue; }

            if (/^version:\s*/.test(trimmed)) {
                entry.version = trimmed.replace(/^version:\s*/, '').replace(/^"|"$/g, '').trim();
            } else if (/^resolution:\s*/.test(trimmed)) {
                entry.resolution = trimmed.replace(/^resolution:\s*/, '').replace(/^"|"$/g, '').trim();
            } else if (/^(dependencies|peerDependencies|optionalDependencies):\s*$/.test(trimmed)) {
                const section = trimmed.split(':')[0];
                i++;
                while (i < lines.length && /^\s{4,}/.test(lines[i])) {
                    const depLine = lines[i].trim();
                    if (!depLine) { i++; continue; }
                    const dm = /^("?)(.+?)\1:\s*("?)(.+?)\3\s*$/.exec(depLine);
                    if (dm) {
                        const depName = dm[2];
                        const range = dm[4];
                        if (section === 'peerDependencies') {
                            entry.peerDependencies[depName] = range;
                        } else {
                            entry.dependencies[depName] = range;
                        }
                    }
                    i++;
                }
                continue;
            }
            i++;
        }
        // Derive name from the first locator (`name@protocol:range`)
        const firstLoc = entry.locators[0] || '';
        const nm = /^((?:@[^/]+\/)?[^@]+)@/.exec(firstLoc);
        entry.name = nm ? nm[1] : firstLoc;
        entries.push(entry);
    }
    return { entries, format: 'yarn3-lock' };
}

/**
 * Parse a yarn 1 (legacy) lockfile.
 * Format example:
 *   lodash@^4.17.0:
 *     version "4.17.21"
 *     resolved "https://..."
 *     integrity sha512-...
 *     dependencies:
 *       "is-arrayish" "^0.3.0"
 */
function parseYarn1(text) {
    const entries = [];
    const lines = text.split('\n');
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (!line || line.startsWith('#') || /^\s/.test(line)) { i++; continue; }
        // Header: "lodash@^4.17.0:" or `"@scope/pkg@^1.0.0":` or "a@x, a@y:"
        const headerMatch = /^(.+):\s*$/.exec(line);
        if (!headerMatch) { i++; continue; }
        const locators = headerMatch[1].split(',').map(s => s.trim().replace(/^"|"$/g, ''));
        const entry = { locators, version: '', resolved: '', dependencies: {}, peerDependencies: {} };
        i++;
        while (i < lines.length && /^\s/.test(lines[i])) {
            const trimmed = lines[i].trim();
            if (!trimmed) { i++; continue; }
            const vm = /^version\s+"([^"]+)"/.exec(trimmed);
            if (vm) { entry.version = vm[1]; i++; continue; }
            if (/^dependencies:\s*$/.test(trimmed) || /^peerDependencies:\s*$/.test(trimmed)
                || /^optionalDependencies:\s*$/.test(trimmed)) {
                const section = trimmed.split(':')[0];
                i++;
                while (i < lines.length && /^\s{4,}/.test(lines[i])) {
                    const depLine = lines[i].trim();
                    const dm = /^"?([^"\s]+)"?\s+"?([^"]+)"?$/.exec(depLine);
                    if (dm) {
                        if (section === 'peerDependencies') entry.peerDependencies[dm[1]] = dm[2];
                        else entry.dependencies[dm[1]] = dm[2];
                    }
                    i++;
                }
                continue;
            }
            i++;
        }
        const firstLoc = entry.locators[0] || '';
        const nm = /^((?:@[^/]+\/)?[^@]+)@/.exec(firstLoc);
        entry.name = nm ? nm[1] : firstLoc;
        entries.push(entry);
    }
    return { entries, format: 'yarn1-lock' };
}

/**
 * Parse a pnpm-lock.yaml.
 * Format excerpt (we only need the `packages:` map):
 *   packages:
 *     /lodash@4.17.21:
 *       resolution: {integrity: sha512-...}
 *       dependencies:
 *         is-arrayish: 0.3.2
 *       peerDependencies:
 *         react: '>=16'
 */
function parsePnpm(text) {
    const entries = [];
    // Find the `packages:` block
    const pkgIdx = text.indexOf('\npackages:');
    if (pkgIdx < 0) return { entries, format: 'pnpm-lock' };
    const tail = text.slice(pkgIdx);
    const lines = tail.split('\n');
    let i = 1; // skip "packages:" header line itself
    while (i < lines.length) {
        const line = lines[i];
        // Top-level key is 2-space indented under `packages:` (lockfile v6/v7 quote-wrapped)
        const keyMatch = /^  ['"]?(\/?[^'"]+?)['"]?:\s*$/.exec(line);
        if (!keyMatch) { i++; continue; }
        const fullKey = keyMatch[1]; // e.g. "/lodash@4.17.21" or "/@scope/pkg@1.0.0(react@18)"
        const stripped = fullKey.replace(/^\//, '');
        // Strip peer-id suffix like `(react@18)`
        const noPeer = stripped.replace(/\(.+?\)$/, '');
        const m = /^((?:@[^/]+\/)?[^@]+)@(.+)$/.exec(noPeer);
        if (!m) { i++; continue; }
        const entry = { locators: [fullKey], name: m[1], version: m[2],
                        dependencies: {}, peerDependencies: {} };
        i++;
        while (i < lines.length && /^    /.test(lines[i])) {
            const trimmed = lines[i].trim();
            if (!trimmed) { i++; continue; }
            if (/^dependencies:\s*$/.test(trimmed) || /^peerDependencies:\s*$/.test(trimmed)
                || /^optionalDependencies:\s*$/.test(trimmed)) {
                const section = trimmed.split(':')[0];
                i++;
                while (i < lines.length && /^      /.test(lines[i])) {
                    const dl = lines[i].trim();
                    const dm = /^([^:]+):\s*(.+?)\s*$/.exec(dl);
                    if (dm) {
                        const depName = dm[1].replace(/^['"]|['"]$/g, '');
                        const range = dm[2].replace(/^['"]|['"]$/g, '');
                        if (section === 'peerDependencies') entry.peerDependencies[depName] = range;
                        else entry.dependencies[depName] = range;
                    }
                    i++;
                }
                continue;
            }
            i++;
        }
        entries.push(entry);
    }
    return { entries, format: 'pnpm-lock' };
}

/**
 * Parse a package-lock.json (npm v7+).
 * Format: { "packages": { "node_modules/lodash": { "version": ..., "dependencies": {...} } } }
 */
function parseNpmLock(jsonStr) {
    const data = JSON.parse(jsonStr);
    const entries = [];
    const pkgs = data.packages || {};
    for (const [key, val] of Object.entries(pkgs)) {
        if (key === '') continue; // root entry
        // key looks like "node_modules/lodash" or "node_modules/@scope/pkg" or "node_modules/parent/node_modules/lodash"
        const m = /node_modules\/((?:@[^/]+\/)?[^/]+)$/.exec(key);
        if (!m) continue;
        const name = m[1];
        entries.push({
            locators: [key],
            name,
            version: val.version || '',
            dependencies: val.dependencies || {},
            peerDependencies: val.peerDependencies || {},
            dev: !!val.dev,
        });
    }
    return { entries, format: 'npm-lock' };
}

/* ============================================================
 * Workspace / monorepo detection.
 *
 * Walks the root `workspaces` field (npm/yarn) or `pnpm-workspace.yaml`
 * (pnpm). For each workspace, parses its package.json and reports
 * whether `target` appears as a direct dep + which field.
 *
 * Output shape — one element per workspace where target appears:
 *   { workspace: "packages/foo", name: "foo",
 *     declared_in: ["dependencies", ...],
 *     constraint: "^1.2.3" }
 *
 * Why this matters: in a monorepo Phase 2 must know "this pkg appears
 * in workspaces A, B but NOT C" so the user is asked which to upgrade,
 * and Phase 5 runs the package-manager command in the correct cwd.
 * ============================================================ */

function expandWorkspaceGlob(projectPath, pattern) {
    // Supports: literal "packages/foo", single-star "packages/*",
    // and recursive "packages/**". No regex / minimatch dep.
    const norm = pattern.replace(/\\/g, '/').replace(/\/$/, '');
    const recursive = /\/\*\*$/.test(norm);
    const singleStar = !recursive && /\/\*$/.test(norm);
    const baseRel = norm.replace(/\/\*\*?$/, '');
    const baseAbs = path.join(projectPath, baseRel);

    if (!recursive && !singleStar) {
        return fs.existsSync(path.join(baseAbs, 'package.json')) ? [baseRel] : [];
    }

    const out = [];
    function walk(dirAbs, dirRel, depth) {
        let entries;
        try {
            entries = fs.readdirSync(dirAbs, { withFileTypes: true });
        } catch (_) { return; }
        for (const ent of entries) {
            if (!ent.isDirectory()) continue;
            if (ent.name === 'node_modules' || ent.name.startsWith('.')) continue;
            const childAbs = path.join(dirAbs, ent.name);
            const childRel = dirRel ? `${dirRel}/${ent.name}` : ent.name;
            if (fs.existsSync(path.join(childAbs, 'package.json'))) {
                out.push(childRel);
            }
            if (recursive && depth < 6) walk(childAbs, childRel, depth + 1);
        }
    }
    if (fs.existsSync(baseAbs)) walk(baseAbs, baseRel, 0);
    return out;
}

function readPnpmWorkspaceGlobs(projectPath) {
    const fp = path.join(projectPath, 'pnpm-workspace.yaml');
    if (!fs.existsSync(fp)) return [];
    const text = fs.readFileSync(fp, 'utf8');
    const out = [];
    const lines = text.split('\n');
    let inPackages = false;
    for (const line of lines) {
        if (/^packages:\s*$/.test(line.trim())) { inPackages = true; continue; }
        if (inPackages) {
            const m = /^\s*-\s*['"]?([^'"#]+?)['"]?\s*(?:#.*)?$/.exec(line);
            if (m) out.push(m[1].trim());
            else if (/^\S/.test(line)) break; // next top-level key
        }
    }
    return out;
}

function detectWorkspaceLocations(projectPath, rootManifest, target) {
    let globs = [];
    if (Array.isArray(rootManifest.workspaces)) {
        globs = rootManifest.workspaces;
    } else if (rootManifest.workspaces && Array.isArray(rootManifest.workspaces.packages)) {
        // yarn berry shape: { workspaces: { packages: [...] } }
        globs = rootManifest.workspaces.packages;
    } else {
        globs = readPnpmWorkspaceGlobs(projectPath);
    }
    if (!globs.length) return { is_workspace_root: false, workspaces: [], locations: [] };

    const wsPaths = new Set();
    for (const g of globs) {
        for (const rel of expandWorkspaceGlob(projectPath, g)) wsPaths.add(rel);
    }

    const locations = [];
    const allWs = [];
    for (const wsRel of wsPaths) {
        const wsAbs = path.join(projectPath, wsRel);
        const manifestPath = path.join(wsAbs, 'package.json');
        let wsManifest;
        try {
            wsManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
        } catch (_) { continue; }
        allWs.push({ workspace: wsRel, name: wsManifest.name || wsRel });
        const { declaredIn, declaredConstraint } = classifyDeclared(wsManifest, target);
        if (declaredIn.length > 0) {
            locations.push({
                workspace: wsRel,
                name: wsManifest.name || wsRel,
                declared_in: declaredIn,
                constraint: declaredConstraint,
            });
        }
    }
    return { is_workspace_root: true, workspaces: allWs, locations };
}

/* ============================================================
 * @types/<pkg> sibling detection.
 *
 * In TS projects, runtime packages frequently ship without bundled
 * types and rely on a DefinitelyTyped sibling at @types/<derived>.
 * Bumping the runtime alone often drifts the types out of sync.
 *
 * Naming convention (DefinitelyTyped):
 *   lodash       -> @types/lodash
 *   @babel/core  -> @types/babel__core   (scope__name)
 *   @types/...   -> no sibling
 * ============================================================ */

function deriveTypesSiblingName(target) {
    if (target.startsWith('@types/')) return null;
    if (target.startsWith('@')) {
        const m = /^@([^/]+)\/(.+)$/.exec(target);
        if (!m) return null;
        return `@types/${m[1]}__${m[2]}`;
    }
    return `@types/${target}`;
}

function detectTypesSibling(rootManifest, target, parsedLockfile) {
    const siblingName = deriveTypesSiblingName(target);
    if (!siblingName) return { applicable: false };

    // Check root manifest
    const rootDecl = classifyDeclared(rootManifest, siblingName);

    // Check lockfile for the sibling's installed version
    let installedVersion = null;
    if (parsedLockfile && parsedLockfile.entries) {
        for (const entry of parsedLockfile.entries) {
            if (entry.name === siblingName && entry.version) {
                installedVersion = entry.version;
                break;
            }
        }
    }

    const present = rootDecl.declaredIn.length > 0 || installedVersion !== null;
    return {
        applicable: true,
        sibling_name: siblingName,
        present,
        declared_in_root: rootDecl.declaredIn,
        root_constraint: rootDecl.declaredConstraint,
        installed_version: installedVersion,
        recommendation: present
            ? `Bump ${siblingName} alongside ${target} — @types are commonly version-locked to the runtime package.`
            : null,
    };
}

/* ============================================================
 * Common collector: given the parsed lockfile, find every package
 * that lists `target` in its `dependencies`/`peerDependencies`.
 * ============================================================ */

function collectParentsFromLock(parsed, target, rootName) {
    const parents = new Set();
    const constraints = {};
    for (const entry of parsed.entries) {
        // Skip workspace root resolutions (`<name>@workspace:...`) — those
        // aren't "parent packages" in the dep-graph sense; they are the
        // manifest the user already controls.
        const isWorkspace = (entry.locators || []).some(l => /@workspace:/.test(l));
        if (isWorkspace) continue;
        if (entry.dependencies && entry.dependencies[target] !== undefined) {
            parents.add(entry.name);
            // Prefer the first (closest) constraint encountered
            if (!constraints[entry.name]) constraints[entry.name] = entry.dependencies[target];
        }
        if (entry.peerDependencies && entry.peerDependencies[target] !== undefined) {
            parents.add(entry.name);
            if (!constraints[entry.name]) constraints[entry.name] = entry.peerDependencies[target] + ' (peer)';
        }
    }
    // Remove self-references and root manifest name
    parents.delete(target);
    if (rootName) parents.delete(rootName);
    return { parents: Array.from(parents), constraints };
}

function getInstalledVersionFromLock(parsed, target) {
    // Return the first version we see for target (lockfiles may have multiple)
    for (const entry of parsed.entries) {
        if (entry.name === target && entry.version) return entry.version;
    }
    return 'unknown';
}

/**
 * Build a reverse-dependency index: { childName -> Set<parentName> }.
 * This lets us walk UP the lockfile dep graph from any package to find
 * its eventual "direct parents" (= packages declared in package.json).
 */
function buildReverseIndex(parsed) {
    const reverse = new Map(); // child -> Set<parent>
    for (const entry of parsed.entries) {
        const isWorkspace = (entry.locators || []).some(l => /@workspace:/.test(l));
        if (isWorkspace) continue;
        for (const childName of Object.keys(entry.dependencies || {})) {
            if (!reverse.has(childName)) reverse.set(childName, new Set());
            reverse.get(childName).add(entry.name);
        }
        for (const childName of Object.keys(entry.peerDependencies || {})) {
            if (!reverse.has(childName)) reverse.set(childName, new Set());
            reverse.get(childName).add(entry.name);
        }
    }
    return reverse;
}

/**
 * Walk UP the lockfile graph from `target` until we hit packages that are
 * declared in package.json (= "direct parents"). Returns ALL distinct
 * chains found and a flat list of direct parent names.
 *
 * Each chain is an ordered array from target to direct-parent, e.g.
 * ["ip-address", "some-mid-pkg", "axios"] means
 *   axios → some-mid-pkg → ip-address
 * and `axios` is in package.json.
 *
 * Capped at maxDepth to avoid runaway in pathological graphs.
 */
function walkUpToDirectParents(target, reverseIndex, directDepNames, maxDepth = 10) {
    const chains = [];
    const directParents = new Set();
    const transitiveParents = new Set();

    // BFS: each frontier element is { chain: [<target>, ...] }
    const queue = [{ chain: [target] }];
    const visited = new Set([target]);

    while (queue.length > 0) {
        const { chain } = queue.shift();
        const node = chain[chain.length - 1];
        if (chain.length > maxDepth) continue;

        const parents = reverseIndex.get(node);
        if (!parents || parents.size === 0) continue;

        for (const parent of parents) {
            if (visited.has(parent)) continue;
            const newChain = [...chain, parent];

            if (directDepNames.has(parent)) {
                // Reached a direct parent — chain complete
                directParents.add(parent);
                chains.push(newChain);
            } else {
                transitiveParents.add(parent);
                visited.add(parent);
                queue.push({ chain: newChain });
            }
        }
    }

    return {
        chains,
        direct_parents: Array.from(directParents),
        transitive_parents: Array.from(transitiveParents),
    };
}

/**
 * Decide the recommended upgrade strategy ranked by user preference:
 *   1. direct_bump  — target is declared directly in package.json
 *   2. bump_override — target is in package.json overrides/resolutions
 *   3. bump_parent  — bump a direct parent so it pulls a new target
 *   4. add_override — no parent path works; add overrides/resolutions
 *   5. lock_only    — last resort; truly orphan transitive with no parent
 *                     in package.json and no override field exists
 */
function recommendStrategies({ declaredIn, declaredConstraint, overridesPin,
                                directParents, transitiveParents, chains,
                                pkgManager }) {
    const strategies = [];

    if (declaredIn.length > 0) {
        strategies.push({
            type: 'direct_bump',
            rationale: `Target is declared directly in package.json (${declaredIn.join(', ')}); bump it there and the lockfile follows.`,
            current_constraint: declaredConstraint,
            apply_hint: pkgManager === 'yarn'
                ? `$PKG_MANAGER_BIN up <target>@<new-range>`
                : pkgManager === 'pnpm'
                    ? `pnpm up <target>@<new-range>`
                    : `npm install <target>@<new-range>`,
        });
        return strategies; // direct supersedes everything else
    }

    const overrideHit = overridesPin.overrides || overridesPin.resolutions || overridesPin.pnpm_overrides;
    if (overrideHit) {
        strategies.push({
            type: 'bump_override',
            rationale: `Target is pinned via ${overrideHit.kind} (key: ${overrideHit.key}, current: ${overrideHit.value}). Update that entry in package.json — preferable to hand-editing the lockfile.`,
            field: overrideHit.kind,
            current_value: overrideHit.value,
        });
    }

    if (directParents.length > 0) {
        for (const parent of directParents) {
            // Find the chain(s) that end in this parent
            const chainsForParent = chains.filter(c => c[c.length - 1] === parent);
            strategies.push({
                type: 'bump_parent',
                target: parent,
                rationale: `${parent} is a direct dependency that (transitively) pulls in the target. Bumping ${parent} lets ITS new release pick a compatible target version — safer than overriding the lockfile entry.`,
                parent_chain: chainsForParent[0] || [parent],
                apply_hint: pkgManager === 'yarn'
                    ? `$PKG_MANAGER_BIN up ${parent}`
                    : pkgManager === 'pnpm'
                        ? `pnpm up ${parent}`
                        : `npm install ${parent}@<new-range>`,
            });
        }
    }

    // add_override is always offered when target is transitive and no direct
    // package.json constraint exists — covers the case where bump_parent's
    // new version doesn't actually pull a new target.
    if (declaredIn.length === 0 && !overrideHit) {
        strategies.push({
            type: 'add_override',
            rationale: 'Add an overrides (npm) / resolutions (yarn) / pnpm.overrides entry to package.json to pin the target to the new version. Expresses intent in package.json instead of hand-editing the lockfile.',
            patch_hint: pkgManager === 'yarn'
                ? '{"resolutions": {"<target>": "<new-version>"}}'
                : pkgManager === 'pnpm'
                    ? '{"pnpm": {"overrides": {"<target>": "<new-version>"}}}'
                    : '{"overrides": {"<target>": "<new-version>"}}',
        });
    }

    // lock_only is the LAST resort and only listed when there's no
    // package.json constraint whatsoever AND no direct parent path exists.
    if (declaredIn.length === 0 && !overrideHit && directParents.length === 0) {
        strategies.push({
            type: 'lock_only',
            rationale: '⚠️ Last resort: no package.json constraint exists for target, and no direct parent could be walked to. This means hand-editing the lockfile or running pkg-manager-specific lock-update commands. Make sure validate_lockfile.sh passes before committing.',
            warning: 'Hand-editing the lockfile loses the audit trail; prefer add_override above unless explicitly told otherwise.',
        });
    }

    return strategies;
}

/* ============================================================
 * Fallback: package-manager `ls`-based tree (existing behavior).
 * Kept for the rare case where no lockfile exists.
 * ============================================================ */

function getTreeNpmFallback(projectPath) {
    try {
        const out = execSync('npm ls --all --json', {
            cwd: projectPath, stdio: ['ignore', 'pipe', 'pipe'],
            maxBuffer: 1024 * 1024 * 128,
        }).toString();
        return { format: 'npm-ls', data: JSON.parse(out) };
    } catch (err) {
        if (err.stdout && err.stdout.length > 0) {
            try { return { format: 'npm-ls', data: JSON.parse(err.stdout.toString()) }; } catch (_) { /* */ }
        }
        return { format: 'npm-ls', data: null, error: err.message };
    }
}

function walkNpmTreeJSON(node, target, parents, constraints, parentName) {
    if (!node || typeof node !== 'object') return;
    const deps = node.dependencies || {};
    for (const [depName, depNode] of Object.entries(deps)) {
        if (depName === target && parentName && !parents.has(parentName)) {
            parents.add(parentName);
            const peer = (depNode && depNode.peer) ? ' (peer)' : '';
            const required = (depNode && depNode.required) ||
                             (depNode && depNode.from) ||
                             (depNode && depNode.version ? `==${depNode.version}` : '');
            constraints[parentName] = `${required}${peer}` || 'unknown';
        }
        walkNpmTreeJSON(depNode, target, parents, constraints, depName);
    }
}

/* ============================================================
 * Main
 * ============================================================ */

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
    const overridesPin = findOverridesPin(manifest, args.packageName);

    // Build the set of direct dependency names (anything declared in
    // package.json's dep fields) for parent-chain walking.
    const directDepNames = new Set();
    for (const field of DEP_FIELDS) {
        if (manifest[field]) for (const name of Object.keys(manifest[field])) directDepNames.add(name);
    }

    // ---- Lockfile-first ----
    const lockfile = detectLockfile(args.projectPath);
    let parents = [];
    let constraints = {};
    let installedVersion = 'unknown';
    let source = 'unknown';
    let fullTree = null;
    let chainInfo = { chains: [], direct_parents: [], transitive_parents: [] };
    let parsedLockfile = null;

    if (lockfile) {
        const text = fs.readFileSync(lockfile.path, 'utf8');
        try {
            if (lockfile.pm === 'yarn') {
                parsedLockfile = isYarnBerry(text) ? parseYarnBerry(text) : parseYarn1(text);
            } else if (lockfile.pm === 'pnpm') {
                parsedLockfile = parsePnpm(text);
            } else if (lockfile.pm === 'npm') {
                parsedLockfile = parseNpmLock(text);
            } else if (lockfile.pm === 'bun') {
                // bun.lock(b): no robust parser without bun runtime; record as unsupported
                errors.push('bun lockfile parsing not implemented yet; falling back to package.json declaration only');
                parsedLockfile = { entries: [], format: 'bun-unsupported' };
            }
            source = parsedLockfile.format;
            const collected = collectParentsFromLock(parsedLockfile, args.packageName, manifest.name);
            parents = collected.parents;
            constraints = collected.constraints;
            installedVersion = getInstalledVersionFromLock(parsedLockfile, args.packageName);
            fullTree = { format: parsedLockfile.format, entry_count: parsedLockfile.entries.length };

            // Walk up the lockfile dep graph to find direct parents
            const reverseIndex = buildReverseIndex(parsedLockfile);
            chainInfo = walkUpToDirectParents(args.packageName, reverseIndex, directDepNames);
        } catch (err) {
            errors.push(`lockfile parse failed: ${err.message}`);
        }
    }

    // ---- Fallback to `npm ls` if no lockfile or parse failed AND node_modules exists ----
    const hasNodeModules = fs.existsSync(path.join(args.projectPath, 'node_modules'));
    if ((!lockfile || installedVersion === 'unknown') && pkgManager === 'npm' && hasNodeModules) {
        const tree = getTreeNpmFallback(args.projectPath);
        if (tree.data) {
            source = source === 'unknown' ? 'npm-ls' : `${source}+npm-ls`;
            const ps = new Set();
            walkNpmTreeJSON(tree.data, args.packageName, ps, constraints, null);
            for (const p of ps) if (!parents.includes(p)) parents.push(p);
            fullTree = fullTree || tree.data;
        }
        if (tree.error) errors.push(`npm ls fallback: ${tree.error}`);
    }

    const isDirect = declaredIn.length > 0 && !declaredIn.every(f => f === 'peerDependencies');
    const isPeer = declaredIn.includes('peerDependencies');
    const isTransitive = parents.length > 0;

    let depType = 'unknown';
    if (isDirect && isTransitive) depType = 'both';
    else if (isDirect)            depType = 'direct';
    else if (isTransitive)        depType = 'transitive';
    else if (isPeer)              depType = 'peer';

    if (declaredConstraint !== null) constraints.__declared__ = declaredConstraint;

    // Workspace / monorepo detection — where does target appear across
    // workspaces? Lets Phase 2 prompt the user with concrete locations
    // and lets Phase 5 cd into the correct workspace before bumping.
    const workspaceInfo = detectWorkspaceLocations(args.projectPath, manifest, args.packageName);

    // @types/<pkg> sibling detection — TS projects commonly need to bump
    // the DefinitelyTyped sibling alongside the runtime package.
    const typesSibling = detectTypesSibling(manifest, args.packageName, parsedLockfile);

    // Recommend upgrade strategies in priority order (per user feedback:
    // prefer bumping the source-of-truth in package.json over hand-editing
    // the lockfile).
    const upgradeStrategies = recommendStrategies({
        declaredIn,
        declaredConstraint,
        overridesPin,
        directParents: chainInfo.direct_parents,
        transitiveParents: chainInfo.transitive_parents,
        chains: chainInfo.chains,
        pkgManager,
    });

    const result = {
        package_name: args.packageName,
        language: 'javascript',
        pkg_manager: pkgManager,
        current_version: installedVersion,
        dependency_type: depType,
        is_direct: isDirect,
        is_transitive: isTransitive,
        is_peer: isPeer,
        // Backward-compat fields
        parent_packages: parents,
        version_constraints: constraints,
        declared_in: declaredIn,
        // NEW fields — package.json transitive-pinning detection
        package_json_pin: {
            overrides:      overridesPin.overrides,
            resolutions:    overridesPin.resolutions,
            pnpm_overrides: overridesPin.pnpm_overrides,
        },
        // NEW fields — parent-chain walking
        direct_parents:     chainInfo.direct_parents,
        transitive_parents: chainInfo.transitive_parents,
        parent_chains:      chainInfo.chains,
        // NEW field — ranked upgrade strategies
        upgrade_strategies: upgradeStrategies,
        recommended_strategy: upgradeStrategies[0] ? upgradeStrategies[0].type : null,
        // NEW field — workspace / monorepo location map
        workspace_info: workspaceInfo,
        // NEW field — @types/<pkg> DefinitelyTyped sibling
        types_sibling: typesSibling,
        source,
        full_tree: fullTree,
        errors,
    };

    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main();
