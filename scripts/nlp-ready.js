#!/usr/bin/env node
// Под ключ: поднять сервис при необходимости → bootstrap → smoke.
const { spawn } = require('child_process');
const path = require('path');

const base = process.env.BASE_URL || 'http://localhost:8787';
const root = path.resolve(__dirname, '..');

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function isUp() {
  try {
    const res = await fetch(`${base}/health`);
    if (!res.ok) return false;
    const j = await res.json();
    return Boolean(j?.nlp?.enabled);
  } catch {
    return false;
  }
}

function runNode(script, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script], {
      cwd: root,
      env: { ...process.env, ...env },
      stdio: 'inherit',
    });
    child.on('exit', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${script} exited ${code}`));
    });
  });
}

async function main() {
  let server = null;
  let startedByUs = false;

  if (!(await isUp())) {
    console.log('starting server...');
    startedByUs = true;
    server = spawn(process.execPath, ['src/index.js'], {
      cwd: root,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    server.stdout.on('data', (d) => process.stdout.write(`[server] ${d}`));
    server.stderr.on('data', (d) => process.stderr.write(`[server] ${d}`));

    const started = Date.now();
    while (!(await isUp())) {
      if (Date.now() - started > 20000) {
        if (server) server.kill('SIGTERM');
        throw new Error('server failed to become healthy');
      }
      await sleep(400);
    }
  } else {
    console.log('server already up');
  }

  try {
    await runNode(path.join('scripts', 'nlp-bootstrap.js'), { BASE_URL: base });
    await runNode(path.join('scripts', 'nlp-smoke.js'), { BASE_URL: base });
    console.log('\nREADY под ключ: API работает, bootstrap и smoke прошли.');
    console.log(`health: ${base}/health`);
    console.log(`digest: ${base}/nlp/digest`);
    console.log(`skills: ${base}/nlp/skills`);
  } finally {
    // Если сервер подняли мы и это one-shot — оставляем его жить только если KEEP_SERVER=1
    if (startedByUs && server && process.env.KEEP_SERVER !== '1') {
      server.kill('SIGTERM');
    }
  }
}

main().catch((err) => {
  console.error('FAIL', err.message);
  process.exit(1);
});
