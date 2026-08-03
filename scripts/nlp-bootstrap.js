#!/usr/bin/env node
// Под ключ: дождаться API и развернуть рабочий контур команды.
const base = process.env.BASE_URL || 'http://localhost:8787';
const maxWaitMs = Number(process.env.WAIT_MS || 20000);

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitHealth() {
  const started = Date.now();
  while (Date.now() - started < maxWaitMs) {
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) {
        const json = await res.json();
        if (json?.nlp?.enabled) return json;
      }
    } catch {
      // still starting
    }
    await sleep(500);
  }
  throw new Error(`API not ready at ${base}/health within ${maxWaitMs}ms`);
}

async function main() {
  console.log('bootstrap →', base);
  await waitHealth();

  const res = await fetch(`${base}/nlp/bootstrap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      companyGoal: process.env.COMPANY_GOAL || 'Собрать предсказуемый ритм сделок и сдачи помещений',
      reuseActive: true,
    }),
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(`bootstrap bad JSON: ${text}`);
  }
  if (!res.ok) throw new Error(`bootstrap failed: ${res.status} ${text}`);

  console.log('OK bootstrap');
  console.log('company:', json.company.goal);
  console.log('companyOkr:', json.company.okrId);
  console.log('employees:');
  for (const e of json.employees) {
    console.log(
      `- ${e.staff} [${e.role}] cycle=${e.cycleId} okr=${e.okrId} test="${e.todayTest}"`
    );
  }
  console.log('digest lines:');
  for (const line of json.digest.lines || []) console.log(' ', line);
  console.log('next:');
  for (const step of json.howToOperate) console.log(' ', step);
}

main().catch((err) => {
  console.error('FAIL', err.message);
  process.exit(1);
});
