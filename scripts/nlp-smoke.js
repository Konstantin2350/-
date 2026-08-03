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

  const models = await req('GET', '/nlp/models');
  if (!models.models?.some((m) => m.id === 'goal-path')) {
    throw new Error('goal-path model missing');
  }

  const pack = await req('POST', '/nlp/models/pack', {
    goal: 'Сдать 3 пустующих лота на Северной 100',
    owner: 'Альбина',
    deadline: '2026-08-17',
    present: '2 лота пустуют дольше месяца',
    symptom: 'Нет стабильного потока показов',
    cause: 'Мало целевых касаний и нет ежедневного теста',
    startCycle: true,
    staff: 'Альбина-модели',
    reuseActive: false,
  });
  if (!pack.models?.wfo || !pack.models?.goalPath || !pack.models?.score) {
    throw new Error('pack incomplete');
  }
  if (!pack.cycle?.id) throw new Error('pack startCycle failed');

  const path = await req('POST', '/nlp/models/goal-path', {
    goal: 'Закрыть 5 тёплых лидов',
    present: 'Есть база, нет ритма касаний',
    owner: 'Олег',
    obstacles: ['Нет скрипта follow-up'],
  });
  if (!path.path?.length) throw new Error('goal-path empty');

  const grow = await req('POST', '/nlp/models/grow', {
    goal: 'Сдать 3 лота',
    reality: 'Мало показов',
    owner: 'Альбина',
    commitment: 9,
  });
  if (grow.grow?.will?.commitment !== 9) throw new Error('grow commitment failed');

  const okrRes = await req('POST', '/nlp/okr', {
    goal: 'Сдать 3 пустующих лота на Северной 100',
    owner: 'Альбина',
    deadline: '2026-08-17',
  });
  const okr = okrRes.okr;
  if (!okr?.keyResults?.length) throw new Error('okr keyResults missing');

  const krId = okr.keyResults[0].id;
  const updated = await req('PATCH', `/nlp/okr/${okr.id}/kr/${krId}`, {
    current: 1,
    confidence: 7,
  });
  if (updated.okr.keyResults[0].current !== 1) throw new Error('kr update failed');

  await req('POST', `/nlp/okr/${okr.id}/checkin`, {
    confidence: 7,
    plans: '2 показа',
    progress: '1 договор в работе',
    problems: 'ждём сравнение цен',
    krUpdates: [{ id: krId, current: 1, confidence: 7 }],
  });

  const checkin = await req('POST', `/nlp/cycle/${pack.cycle.id}/checkin`, {
    confidence: 6,
    plans: 'касания',
    progress: 'есть ответы',
    problems: 'мало слотов',
    nextTest: 'назначить 2 показа',
  });
  if (checkin.cycle.trafficLight !== 'at_risk') {
    throw new Error('expected at_risk traffic light');
  }

  const digest = await req('GET', '/nlp/digest');
  if (!digest.digest?.lines?.length) throw new Error('digest empty');

  const retro = await req('POST', `/nlp/cycle/${albina.id}/retro`, {});
  if (!retro.retro?.learnings?.length) throw new Error('retro empty');

  const skills = await req('GET', '/nlp/skills');
  if (!skills.skills?.some((s) => s.id === 'meta-model')) {
    throw new Error('master skills missing');
  }
  const packSkills = await req('POST', '/nlp/skills/pack', {
    role: 'sales',
    staff: 'Альбина',
    focus: 'сдать лоты',
  });
  if (!packSkills.systemPrompt || !packSkills.skills?.length) {
    throw new Error('skills pack incomplete');
  }
  if (/терапи/i.test(packSkills.systemPrompt) && !/ЗАПРЕЩЕНО: терапия/i.test(packSkills.systemPrompt)) {
    throw new Error('skills pack must forbid therapy');
  }
  const applied = await req('POST', '/nlp/skills/apply', {
    skillId: 'objection-handle',
    situation: 'Дорого',
    staff: 'Альбина',
    role: 'sales',
  });
  if (!applied.nextAction) throw new Error('skill apply missing nextAction');

  const boot = await req('POST', '/nlp/bootstrap', {
    companyGoal: 'Smoke bootstrap goal',
    roster: [
      { staff: 'SmokeBot', role: 'ops', focus: 'закрыть операционный тест' },
    ],
    reuseActive: false,
  });
  if (!boot.ok || !boot.employees?.length) throw new Error('bootstrap failed');
  if (!boot.company?.okrId) throw new Error('bootstrap company okr missing');

  console.log('OK nlp smoke + models + okr/checkin + master skills + bootstrap');
}

main().catch((err) => {
  console.error('FAIL', err.message);
  process.exit(1);
});
