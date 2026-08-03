#!/usr/bin/env node
// Под ключ: smoke-проверка операционного NLP без GUI и без Perplexity.
const base = process.env.BASE_URL || 'http://localhost:8787';

async function req(method, path, body) {
  const res = await fetch(`${base}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(`${method} ${path} -> ${res.status}: ${text}`);
    err.status = res.status;
    err.json = json;
    throw err;
  }
  return json;
}

async function main() {
  console.log('smoke against', base);
  const health = await req('GET', '/health');
  if (!health.nlp?.enabled) throw new Error('nlp disabled');
  if (health.nlp.therapy !== false) throw new Error('therapy must be false');

  const morning = await req('POST', '/nlp/morning', {
    roster: [
      { staff: 'Альбина', focus: 'сдать пустующие на Северной 100', deadline: '2026-08-17' },
      { staff: 'Олег', focus: 'закрыть 5 тёплых лидов' },
    ],
    reuseActive: true,
  });
  if (!morning.board) throw new Error('morning board missing');

  const albina = morning.cycles.find((c) => c.staff === 'Альбина');
  if (!albina) throw new Error('Альбина cycle missing');

  const fail = await req('POST', `/nlp/cycle/${albina.id}/advance`, {
    eventType: 'test',
    passed: false,
    note: '0 показов за день',
  });
  if (fail.cycle.phase !== 'operate') throw new Error('expected operate after fail');
  if (!fail.cycle.nextAction) throw new Error('expected suggested operate action');

  await req('POST', `/nlp/cycle/${albina.id}/note`, {
    note: 'Клиент ждёт сравнение по цене',
  });

  const op = await req('POST', `/nlp/cycle/${albina.id}/advance`, {
    eventType: 'operate',
    action: '10 целевых касаний + 2 показа',
  });
  if (op.cycle.phase !== 'test') throw new Error('expected test after operate');

  const pass = await req('POST', `/nlp/cycle/${albina.id}/advance`, {
    eventType: 'test',
    passed: true,
    note: '3 договора',
  });
  if (pass.cycle.status !== 'done') throw new Error('expected done');

  const board = await req('GET', '/nlp/board');
  console.log('board counts', board.board.counts);
  console.log('OK nlp smoke');
}

main().catch((err) => {
  console.error('FAIL', err.message);
  process.exit(1);
});
