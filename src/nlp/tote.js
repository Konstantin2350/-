// TOTE: Test → Operate → Test → Exit — операционный цикл коллектива.
// Логика под ключ: фазы, блокеры, stall, подсказки коррекции.

const PHASES = ['test', 'operate', 'exit'];
const DEFAULT_MAX_ITERATIONS = 8;

function suggestOperate(note, focus) {
  const text = `${note || ''} ${focus || ''}`.toLowerCase();
  const tips = [];

  if (/0\s*показ|нет показ|не было показ/.test(text)) {
    tips.push('Назначить 2 показа сегодня и подтвердить слоты в календаре');
  }
  if (/лид|заявк|касани|звонк|whatsapp|вотсап|wa\b/.test(text)) {
    tips.push('Сделать 10 целевых касаний по тёплой базе + зафиксировать ответы');
  }
  if (/договор|предоплат|сделк/.test(text)) {
    tips.push('Дожать 1 ближайшую сделку: следующий шаг подписанта и дедлайн ответа');
  }
  if (/цена|дорог|скидк|бюджет/.test(text)) {
    tips.push('Подготовить 2 альтернативы по цене/площади и отправить сравнение');
  }
  if (/блокер|ждет|ждёт|согласован|документ/.test(text)) {
    tips.push('Снять блокер: кто решает, какой артефакт нужен, срок до конца дня');
  }
  if (tips.length === 0) {
    tips.push('Сменить канал/скрипт/ресурс и назначить один проверяемый тест до вечера');
  }
  return tips[0];
}

function buildAssessment({ phase, status, lastTest, wfo, stalled, maxIterations, iteration }) {
  if (status === 'archived') {
    return 'Цикл в архиве (не активен).';
  }
  if (status === 'review') {
    return `Нужен разбор: итераций ${iteration}/${maxIterations}. Уточнить критерий или ресурсы.`;
  }
  if (status === 'done' || phase === 'exit') {
    return `Exit: критерий «${wfo?.successMetric || 'успех'}» считается достигнутым или цикл закрыт.`;
  }
  if (stalled) {
    return 'Stall: давно не было движения. Нужен свежий тест или коррекция сегодня.';
  }
  if (phase === 'operate') {
    return `Test не пройден${lastTest?.note ? `: ${lastTest.note}` : ''}. Нужна коррекция (Operate).`;
  }
  return `Test: сверить факт с критерием «${wfo?.successMetric || 'успех'}».`;
}

function withRuntimeFlags(cycle, { stallHours = 24 } = {}) {
  const maxIterations = Number(cycle.maxIterations || DEFAULT_MAX_ITERATIONS);
  const updatedMs = Date.parse(cycle.updatedAt || cycle.createdAt || '') || Date.now();
  const ageHours = (Date.now() - updatedMs) / 36e5;
  const stalled =
    cycle.status === 'active' && ageHours >= stallHours && cycle.phase !== 'exit';
  const overdue =
    Boolean(cycle.deadline) &&
    cycle.status === 'active' &&
    Date.parse(cycle.deadline) < Date.now();

  return {
    ...cycle,
    maxIterations,
    stalled,
    overdue,
    assessment: buildAssessment({
      phase: cycle.phase,
      status: cycle.status,
      lastTest: cycle.lastTest,
      wfo: cycle.wfo,
      stalled,
      maxIterations,
      iteration: cycle.iteration,
    }),
  };
}

function advanceLocal(cycle, { eventType, note, passed, action } = {}) {
  const history = Array.isArray(cycle.history) ? [...cycle.history] : [];
  const now = new Date().toISOString();
  const maxIterations = Number(cycle.maxIterations || DEFAULT_MAX_ITERATIONS);
  let phase = cycle.phase || 'test';
  let iteration = Number(cycle.iteration || 1);
  let status = cycle.status || 'active';
  let lastTest = cycle.lastTest || null;
  let lastOperate = cycle.lastOperate || null;
  let blocker = cycle.blocker || null;
  let nextAction = cycle.nextAction || cycle.wfo?.firstTest || null;

  if (status === 'archived') {
    const err = new Error('cycle archived');
    err.status = 409;
    throw err;
  }

  const inferredType =
    eventType ||
    (phase === 'operate' ? 'operate' : phase === 'exit' ? 'exit' : 'test');

  if (inferredType === 'test') {
    if (phase === 'operate' && eventType === 'test') {
      // явный тест из operate допускается (команда уже сделала коррекцию «в уме»)
    } else if (phase === 'exit') {
      const err = new Error('cycle already in exit');
      err.status = 409;
      throw err;
    }

    if (typeof passed !== 'boolean') {
      const err = new Error('passed (boolean) is required for test');
      err.status = 400;
      throw err;
    }

    const ok = passed;
    lastTest = { at: now, note: note || null, passed: ok };
    history.push({ type: 'test', at: now, passed: ok, note: note || null });

    if (ok) {
      phase = 'exit';
      status = 'done';
      nextAction = null;
      blocker = null;
    } else {
      phase = 'operate';
      blocker = note || blocker;
      const suggested = suggestOperate(note, cycle.wfo?.outcome);
      nextAction = action || suggested;
    }
  } else if (inferredType === 'operate') {
    if (!action && !note) {
      const err = new Error('action or note is required for operate');
      err.status = 400;
      throw err;
    }
    const operateAction =
      action || note || suggestOperate(blocker, cycle.wfo?.outcome);
    lastOperate = { at: now, action: operateAction, note: note || null };
    history.push({
      type: 'operate',
      at: now,
      action: operateAction,
      note: note || null,
    });
    phase = 'test';
    iteration += 1;
    nextAction = `Проверить результат после: ${operateAction}`;
    if (iteration > maxIterations) {
      status = 'review';
      nextAction = 'Разбор с владельцем: сузить цель или добавить ресурс';
    }
  } else if (inferredType === 'exit') {
    phase = 'exit';
    status = 'done';
    nextAction = null;
    history.push({ type: 'exit', at: now, note: note || 'Ручной выход' });
  } else if (inferredType === 'reopen') {
    if (status !== 'done' && status !== 'archived' && status !== 'review') {
      const err = new Error('reopen only for done/archived/review');
      err.status = 409;
      throw err;
    }
    phase = 'test';
    status = 'active';
    iteration = 1;
    nextAction = cycle.wfo?.firstTest || 'Повторить тест по критерию успеха';
    history.push({ type: 'reopen', at: now, note: note || 'Reopen' });
  } else {
    const err = new Error(`unsupported eventType: ${inferredType}`);
    err.status = 400;
    throw err;
  }

  const next = {
    ...cycle,
    phase,
    iteration,
    status,
    lastTest,
    lastOperate,
    blocker,
    nextAction,
    history,
    maxIterations,
  };
  return withRuntimeFlags(next);
}

function appendNote(cycle, note) {
  const text = String(note || '').trim();
  if (!text) {
    const err = new Error('note is required');
    err.status = 400;
    throw err;
  }
  const now = new Date().toISOString();
  const notes = Array.isArray(cycle.notesTail) ? [...cycle.notesTail] : [];
  notes.push({ at: now, note: text });
  // хвост заметок — последние 30
  const notesTail = notes.slice(-30);
  return withRuntimeFlags({
    ...cycle,
    notesTail,
    history: [...(cycle.history || []), { type: 'note', at: now, note: text }],
  });
}

function staffCycleLocal({ staff, focus, notes, owner, deadline, successMetric, firstTest }) {
  const role = String(staff || '').trim();
  if (!role) {
    const err = new Error('staff is required');
    err.status = 400;
    throw err;
  }
  const focusText = focus ? String(focus).trim() : 'закрыть ключевой результат периода';
  const outcome = `${role}: ${focusText}`;
  const metric =
    successMetric || `Есть проверяемый факт по фокусу: ${focusText}`;
  const concreteTest =
    firstTest ||
    (/сдат|аренд|лот|помещ/.test(focusText.toLowerCase())
      ? '1 показ или 5 целевых касаний + запись факта в конце дня'
      : 'Сделать один проверяемый шаг по фокусу и зафиксировать результат');

  return {
    mode: 'operational',
    staff: role,
    owner: owner || role,
    deadline: deadline || null,
    notes: notes || null,
    wfo: {
      outcome,
      successMetric: metric,
      evidence: [
        'Артефакт/факт в рабочем контуре (задача, договор, отчёт, сообщение)',
      ],
      firstTest: concreteTest,
    },
    todayTest: concreteTest,
    operateIfFail: suggestOperate(notes, focusText),
    exitWhen: 'Критерий успеха подтверждён фактом',
    standupLine: `${role} | цель: ${focusText} | тест: ${concreteTest} | блокер: ${notes || '—'}`,
  };
}

function buildBoard(cycles, { stallHours = 24 } = {}) {
  const enriched = cycles.map((c) => withRuntimeFlags(c, { stallHours }));
  const active = enriched.filter((c) => c.status === 'active');
  const review = enriched.filter((c) => c.status === 'review');
  const done = enriched.filter((c) => c.status === 'done');
  const lines = active.map((c) => {
    const who = c.staff || c.owner || '—';
    const blocker = c.blocker ? ` | блокер: ${c.blocker}` : '';
    const flags = [
      c.stalled ? 'STALL' : null,
      c.overdue ? 'OVERDUE' : null,
      `i${c.iteration}`,
    ]
      .filter(Boolean)
      .join(',');
    return `${who} [${c.phase}/${flags}] → ${c.nextAction || c.wfo?.outcome || ''}${blocker}`;
  });

  return {
    generatedAt: new Date().toISOString(),
    counts: {
      active: active.length,
      review: review.length,
      done: done.length,
      stalled: active.filter((c) => c.stalled).length,
      overdue: active.filter((c) => c.overdue).length,
    },
    standupLines: lines,
    focusNow: active.slice(0, 10).map((c) => ({
      id: c.id,
      staff: c.staff,
      owner: c.owner,
      phase: c.phase,
      nextAction: c.nextAction,
      blocker: c.blocker,
      stalled: c.stalled,
      overdue: c.overdue,
      outcome: c.wfo?.outcome,
    })),
    reviewIds: review.map((c) => c.id),
  };
}

module.exports = {
  PHASES,
  DEFAULT_MAX_ITERATIONS,
  advanceLocal,
  appendNote,
  staffCycleLocal,
  buildAssessment,
  buildBoard,
  suggestOperate,
  withRuntimeFlags,
};
