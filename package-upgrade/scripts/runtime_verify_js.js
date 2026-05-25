#!/usr/bin/env node
/**
 * runtime_verify_js.js — Runtime smoke-test for JS web apps (Phase 0.5 baseline / Phase 6.6 verify).
 *
 * Usage:
 *   node runtime_verify_js.js <project_path> \
 *       --mode baseline|verify \
 *       --start-cmd "<cmd>" \
 *       [--port <port>] \
 *       [--url <url>] \
 *       [--timeout <seconds>] \
 *       [--playwright] \
 *       [--cache-dir <dir>]
 *
 * Tiers:
 *   T1 (default): spawn dev server, scan stdout/stderr for "ready" or "fatal" pattern,
 *                 HTTP GET the URL once ready. No browser dependency.
 *   T2 (--playwright): T1 + launch headless chromium, capture console errors + screenshot.
 *                      Requires `playwright` to be installed (caller's responsibility).
 *
 * Output: JSON on stdout. Errors / diagnostics to stderr.
 * Schema (kept stable so the Phase 6.6 LLM diff logic doesn't need updating per change):
 *   {
 *     "mode": "baseline" | "verify",
 *     "tier": "t1" | "t2",
 *     "start_cmd": "...",
 *     "url": "http://localhost:3000",
 *     "boot_status": "ready" | "timeout" | "crashed" | "port_conflict" | "spawn_error",
 *     "ready_time_ms": 12345,
 *     "ready_pattern_matched": "Local:.*http",
 *     "stderr_errors": [{"line": 42, "text": "...", "type": "module_not_found"}],
 *     "stderr_warning_count": 3,
 *     "http_status": 200,
 *     "http_body_size": 12345,
 *     "http_error": "",
 *     "console_errors": [{"type":"error","text":"..."}],  // T2 only
 *     "failed_requests": [{"url":"...","reason":"..."}],   // T2 only
 *     "dom_node_count": 1234,                              // T2 only
 *     "screenshot_path": ".package-upgrade-cache/screenshot-baseline.png",  // T2 only
 *     "t2_status": "ok" | "playwright_not_installed" | "skipped",
 *     "log_path": ".package-upgrade-cache/runtime-baseline.log"
 *   }
 *
 * Process management notes:
 *   - We spawn the start-cmd via `cross-spawn`-style invocation (shell on Windows for npm/yarn batch).
 *   - On Unix we create a detached process group and SIGTERM the whole group on cleanup.
 *   - On Windows we use `taskkill /T /F` to recursively kill the spawned tree.
 *   - All output is tee'd to <cache-dir>/runtime-<mode>.log for human inspection.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const { URL } = require('url');

// ---------- ready / fatal patterns ----------

// Order matters: more specific first. Each entry is a JS RegExp tested against stripped lines.
const READY_PATTERNS = [
    /Local:\s+https?:\/\//i,             // vite, vite-derived
    /ready\s+(?:-\s+)?started server on/i, // next.js (both pre-13 "ready - started" and 13+ "ready started")
    /ready\s+in\s+\d+/i,                  // vite "ready in 432 ms"
    /Compiled successfully/i,             // CRA, webpack-dev-server
    /webpack\s+\S+\s+compiled/i,          // generic webpack ("webpack 5.x compiled successfully")
    /App running at:/i,                   // vue-cli
    /Listening on https?:\/\//i,
    /Server (?:running|listening) (?:at|on)/i,
    /server started on/i,
    /now serving/i,                       // sveltekit / svelte-kit
    /\bdev server running at\b/i,
    /listening at https?:\/\//i,
    /started server on /i,
    /✔.*ready/i,                          // generic checkmark + ready
];

const FATAL_PATTERNS = [
    { re: /EADDRINUSE/i,                  type: 'port_conflict' },
    { re: /Error:\s+listen\s+EADDR/i,     type: 'port_conflict' },
    { re: /Cannot find module ['"]([^'"]+)['"]/i, type: 'module_not_found' },
    { re: /MODULE_NOT_FOUND/i,            type: 'module_not_found' },
    { re: /ERR_REQUIRE_ESM/i,             type: 'esm_only' },
    { re: /\[vite\]\s+(?:Internal server )?error/i, type: 'vite_error' },
    { re: /Failed to compile/i,           type: 'compile_error' },
    { re: /SyntaxError:/i,                type: 'syntax_error' },
    { re: /\berror TS\d+:/i,              type: 'ts_error' },
    { re: /UnhandledPromiseRejection/i,   type: 'unhandled_rejection' },
];

const STDERR_ERROR_PATTERNS = [
    ...FATAL_PATTERNS,
    { re: /\bERROR\b/i,                   type: 'generic_error' },
    { re: /\bError:/i,                    type: 'generic_error' },
];

// ANSI escape stripper — terminal color codes interfere with regex matching.
function stripAnsi(s) {
    return s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
}

// ---------- args ----------

function parseArgs(argv) {
    const args = {
        projectPath: argv[2],
        mode: null,
        startCmd: null,
        port: null,
        url: null,
        timeout: 60,
        playwright: false,
        cacheDir: null,
    };
    for (let i = 3; i < argv.length; i++) {
        switch (argv[i]) {
            case '--mode':       args.mode = argv[++i]; break;
            case '--start-cmd':  args.startCmd = argv[++i]; break;
            case '--port':       args.port = parseInt(argv[++i], 10); break;
            case '--url':        args.url = argv[++i]; break;
            case '--timeout':    args.timeout = parseInt(argv[++i], 10); break;
            case '--playwright': args.playwright = true; break;
            case '--cache-dir':  args.cacheDir = argv[++i]; break;
            default:
                process.stderr.write(`Unknown arg: ${argv[i]}\n`);
                process.exit(2);
        }
    }
    if (!args.projectPath) { process.stderr.write('Missing <project_path>\n'); process.exit(2); }
    if (!args.mode || !['baseline', 'verify'].includes(args.mode)) {
        process.stderr.write('--mode must be baseline|verify\n'); process.exit(2);
    }
    if (!args.startCmd) { process.stderr.write('--start-cmd required\n'); process.exit(2); }
    if (!args.url && !args.port) { process.stderr.write('--url or --port required\n'); process.exit(2); }
    if (!args.url) args.url = `http://localhost:${args.port}`;
    if (!args.cacheDir) args.cacheDir = path.join(args.projectPath, '.package-upgrade-cache');
    return args;
}

// ---------- cache dir + gitignore ----------

function ensureCacheDir(projectPath, cacheDir) {
    fs.mkdirSync(cacheDir, { recursive: true });
    const gitignorePath = path.join(projectPath, '.gitignore');
    const entry = '.package-upgrade-cache/';
    let current = '';
    try { current = fs.readFileSync(gitignorePath, 'utf8'); } catch { /* missing is fine */ }
    if (!current.split(/\r?\n/).some(l => l.trim() === entry || l.trim() === '.package-upgrade-cache')) {
        const sep = current.length && !current.endsWith('\n') ? '\n' : '';
        fs.appendFileSync(gitignorePath, `${sep}${entry}\n`);
    }
}

// ---------- process spawn ----------

function spawnServer(startCmd, projectPath, logStream) {
    // Shell mode handles `npm run dev`, `yarn start`, etc. portably.
    // On Windows, .cmd shims (npm.cmd, yarn.cmd) require shell:true.
    const isWindows = process.platform === 'win32';
    const child = spawn(startCmd, {
        cwd: projectPath,
        shell: true,
        // detached on POSIX gives us a process group we can SIGTERM atomically.
        // On Windows, detached spawns a new console which we don't want — leave false.
        detached: !isWindows,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1' },
    });

    let collected = '';
    const append = chunk => {
        const s = chunk.toString('utf8');
        collected += s;
        logStream.write(s);
    };
    child.stdout.on('data', append);
    child.stderr.on('data', append);
    return { child, getBuffer: () => collected };
}

function killTree(child) {
    if (!child || child.killed) return;
    const isWindows = process.platform === 'win32';
    try {
        if (isWindows) {
            // Recursive force-kill of the whole tree by root PID.
            spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
        } else {
            // Negative PID targets the process group created by detached:true.
            process.kill(-child.pid, 'SIGTERM');
            setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch { /* gone */ } }, 3000);
        }
    } catch { /* already dead */ }
}

// ---------- ready / fatal detection ----------

async function waitForReadyOrFatal(getBuffer, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        const buf = stripAnsi(getBuffer());
        for (const pat of FATAL_PATTERNS) {
            const m = buf.match(pat.re);
            if (m) {
                return { status: pat.type === 'port_conflict' ? 'port_conflict' : 'crashed',
                         pattern: pat.re.source, elapsed: Date.now() - start };
            }
        }
        for (const pat of READY_PATTERNS) {
            const m = buf.match(pat);
            if (m) {
                return { status: 'ready', pattern: pat.source, elapsed: Date.now() - start };
            }
        }
        await new Promise(r => setTimeout(r, 250));
    }
    return { status: 'timeout', pattern: null, elapsed: timeoutMs };
}

function collectStderrErrors(buffer) {
    const lines = stripAnsi(buffer).split(/\r?\n/);
    const errors = [];
    let warnings = 0;
    lines.forEach((text, idx) => {
        if (/\b(warning|warn|deprecated)\b/i.test(text) && !/\berror\b/i.test(text)) {
            warnings++;
            return;
        }
        for (const pat of STDERR_ERROR_PATTERNS) {
            if (pat.re.test(text)) {
                errors.push({ line: idx + 1, text: text.trim().slice(0, 500), type: pat.type });
                break; // first match wins; don't double-count generic_error on top of specific type
            }
        }
    });
    return { errors, warnings };
}

// ---------- HTTP probe ----------

function httpProbe(url, timeoutMs = 15000) {
    return new Promise(resolve => {
        const parsed = new URL(url);
        const lib = parsed.protocol === 'https:' ? https : http;
        const req = lib.get(url, { timeout: timeoutMs, rejectUnauthorized: false }, res => {
            let size = 0;
            res.on('data', chunk => { size += chunk.length; });
            res.on('end', () => resolve({ status: res.statusCode, size, error: '' }));
        });
        req.on('error', err => resolve({ status: 0, size: 0, error: err.code || err.message }));
        req.on('timeout', () => { req.destroy(); resolve({ status: 0, size: 0, error: 'timeout' }); });
    });
}

// ---------- T2 (playwright) ----------

async function playwrightProbe(url, screenshotPath) {
    let chromium;
    try {
        ({ chromium } = await import('playwright'));
    } catch {
        return { status: 'playwright_not_installed', console_errors: [], failed_requests: [],
                 dom_node_count: 0, screenshot_path: '' };
    }
    const browser = await chromium.launch();
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    const failedRequests = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push({ type: 'error', text: msg.text() });
    });
    page.on('pageerror', err => consoleErrors.push({ type: 'pageerror', text: err.message }));
    page.on('requestfailed', req => failedRequests.push({
        url: req.url(), reason: req.failure() ? req.failure().errorText : 'unknown',
    }));
    let domNodeCount = 0;
    try {
        await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
        domNodeCount = await page.evaluate(() => document.querySelectorAll('*').length);
        await page.screenshot({ path: screenshotPath, fullPage: false });
    } catch (err) {
        consoleErrors.push({ type: 'navigation', text: err.message });
    } finally {
        await browser.close();
    }
    return { status: 'ok', console_errors: consoleErrors, failed_requests: failedRequests,
             dom_node_count: domNodeCount, screenshot_path: screenshotPath };
}

// ---------- main ----------

async function main() {
    const args = parseArgs(process.argv);
    ensureCacheDir(args.projectPath, args.cacheDir);

    const logPath = path.join(args.cacheDir, `runtime-${args.mode}.log`);
    const logStream = fs.createWriteStream(logPath, { flags: 'w' });

    process.stderr.write(`[runtime_verify_js] mode=${args.mode} cmd="${args.startCmd}" url=${args.url} timeout=${args.timeout}s\n`);

    const { child, getBuffer } = spawnServer(args.startCmd, args.projectPath, logStream);

    let spawnError = '';
    child.on('error', err => { spawnError = err.message; });

    const readyResult = await waitForReadyOrFatal(getBuffer, args.timeout * 1000);

    const result = {
        mode: args.mode,
        tier: args.playwright ? 't2' : 't1',
        start_cmd: args.startCmd,
        url: args.url,
        boot_status: spawnError ? 'spawn_error' : readyResult.status,
        ready_time_ms: readyResult.elapsed,
        ready_pattern_matched: readyResult.pattern || '',
        stderr_errors: [],
        stderr_warning_count: 0,
        http_status: 0,
        http_body_size: 0,
        http_error: spawnError || '',
        console_errors: [],
        failed_requests: [],
        dom_node_count: 0,
        screenshot_path: '',
        t2_status: 'skipped',
        log_path: path.relative(args.projectPath, logPath).replace(/\\/g, '/'),
    };

    if (result.boot_status === 'ready') {
        // Give the framework a brief moment to finish wiring routes after the "ready" log.
        await new Promise(r => setTimeout(r, 1500));

        const probe = await httpProbe(args.url);
        result.http_status = probe.status;
        result.http_body_size = probe.size;
        if (probe.error) result.http_error = probe.error;

        if (args.playwright) {
            const screenshotPath = path.join(args.cacheDir, `screenshot-${args.mode}.png`);
            const t2 = await playwrightProbe(args.url, screenshotPath);
            result.t2_status = t2.status;
            result.console_errors = t2.console_errors;
            result.failed_requests = t2.failed_requests;
            result.dom_node_count = t2.dom_node_count;
            result.screenshot_path = t2.screenshot_path
                ? path.relative(args.projectPath, t2.screenshot_path).replace(/\\/g, '/')
                : '';
        }
    }

    // stderr error extraction runs regardless of boot status — even on timeout we want the noise.
    const { errors, warnings } = collectStderrErrors(getBuffer());
    result.stderr_errors = errors;
    result.stderr_warning_count = warnings;

    killTree(child);
    // Give the kill a beat so the log stream flushes cleanly.
    await new Promise(r => setTimeout(r, 500));
    logStream.end();

    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    process.exit(result.boot_status === 'ready' ? 0 : 1);
}

main().catch(err => {
    process.stderr.write(`Fatal: ${err.stack || err.message}\n`);
    process.exit(1);
});
