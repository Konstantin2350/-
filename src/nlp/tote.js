// TOTE: Test → Operate → Test → Exit — операционный цикл коллектива.

const PHASES = ['test', 'operate', 'exit'];

function advanceLocal(cycle, { eventType, note, passed, action } = {}) {
  const history = Array.isArray(cycle.history) ? [...cycle.history] : [];
  const now = new Date().toISOString();
  let phase = cycle.phase || 'test';
  let iteration = Number(cycle.iteration || 1);
  let status = cycle.status || 'active';
  let lastTest = cycle.lastTest || null;
  let lastOperate = cycle.lastOperate || null;
  let nextAction = cycle.nextAction || cycle.wfo?.firstTest || null;

  if (eventType === 'test' || (!eventType && phase === 'test')) {
    const ok = Boolean(passed);
    lastTest = {
      at: now,
      note: note || null,
      passed: ok,
    };
    history.push({ type: 'test', at: now, passed: ok, note: note || null });

    if (ok) {
      phase = 'exit';
      status = 'done';
      nextAction = null;
    } else {
      phase = 'operate';
      nextAction =
        action ||
        'Скорректировать процесс/ресурсы и назначить следующий тест';
    }
  } else if (eventType === 'operate' || (!eventType && phase === 'operate')) {
    lastOperate = {
      at: now,
      action: action || note || 'Коррекция процесса',
      note: note || null,
    };
    history.push({
      type: 'operate',
      at: now,
      action: lastOperate.action,
      note: note || null,
    });
    phase = 'test';
    iteration += 1;
    nextAction = action
      ? `Проверить результат после: ${action}`
      : cycle.wfo?.firstTest || 'Повторить тест по критерию успеха';
  } else if (eventType === 'exit') {
    phase = 'exit';
    status = 'done';
    nextAction = null;
    history.push({ type: 'exit', at: now, note: note || 'Ручной выход' });
  } else {
    const err = new Error(`unsupported eventType/phase: ${eventType || phase}`);
    err.status = 400;
    throw err;
  }

  return {
    ...cycle,
    phase,
    iteration,
    status,
    lastTest,
    lastOperate,
    nextAction,
    history,
    assessment: buildAssessment({ phase, status, lastTest, wfo: cycle.wfo }),
  };
}

function buildAssessment({ phase, status, lastTest, wfo }) {
  if (status === 'done' || phase === 'exit') {
    return `Exit: критерий «${wfo?.successMetric || 'успех'}» считается достигнутым или цикл закрыт.`;
  }
  if (phase === 'operate') {
    return `Test не пройден${lastTest?.note ? `: ${lastTest.note}` : ''}. Нужна коррекция (Operate).`;
  }
  return `Test: сверить факт с критерием «${wfo?.successMetric || 'успех'}».`;
}

function staffCycleLocal({ staff, focus, notes, owner, deadline }) {
  const role = String(staff || '').trim();
  if (!role) {
    const err = new Error('staff is required');
    err.status = 400;
    throw err;
  }
  const focusText = focus ? String(focus).trim() : 'закрыть ключевой результат периода';
  const outcome = `${role}: ${focusText}`;
  return {
    mode: 'operational',
    staff: role,
    owner: owner || role,
    deadline: deadline || null,
    notes: notes || null,
    wfo: {
      outcome,
      successMetric: `Есть проверяемый факт по фокусу: ${focusText}`,
      evidence: ['Артефакт/факт в рабочем контуре (задача, договор, отчёт, сообщение)'],
      firstTest: 'Сделать один проверяемый шаг по фокусу и зафиксировать результат',
    },
    todayTest: 'Один конкретный тест сегодня: действие → факт → сверка',
    operateIfFail: 'Убрать блокер, сменить канал/скрипт/ресурс, повторить тест',
    exitWhen: 'Критерий успеха подтверждён фактом',
    standupLine: `${role} | цель: ${focusText} | тест: 1 шаг сегодня | блокер: ?`,
  };
}

module.exports = {
  PHASES,
  advanceLocal,
  staffCycleLocal,
  buildAssessment,
};
