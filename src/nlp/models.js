// Операционные NLP-модели для рабочего процесса (НЕ терапия).
// Помогают формулировать результат, строить путь к цели и снимать блокеры.

const { buildWfoLocal, normalizeList, inferEvidence, inferFirstTest } = require('./wfo');

const MODEL_CATALOG = [
  {
    id: 'wfo',
    name: 'Хорошо сформулированный результат (WFO)',
    purpose: 'Сделать цель конкретной, позитивной и проверяемой',
    endpoint: 'POST /nlp/models/wfo',
  },
  {
    id: 'goal-path',
    name: 'Модель достижения цели',
    purpose: 'Разложить путь: сейчас → вехи → результат → первый шаг',
    endpoint: 'POST /nlp/models/goal-path',
  },
  {
    id: 'score',
    name: 'SCORE',
    purpose: 'Симптом → причина → результат → ресурсы → эффект',
    endpoint: 'POST /nlp/models/score',
  },
  {
    id: 'ecology',
    name: 'Экологическая проверка',
    purpose: 'Проверить влияние цели на смежные процессы и людей',
    endpoint: 'POST /nlp/models/ecology',
  },
  {
    id: 'clarify',
    name: 'Уточняющие вопросы (операционный мета-модель)',
    purpose: 'Снять туман: кто/что/когда/как измерим',
    endpoint: 'POST /nlp/models/clarify',
  },
  {
    id: 'disney',
    name: 'Disney (Мечтатель / Реалист / Критик)',
    purpose: 'Спланировать инициативу без хаоса и без паралича',
    endpoint: 'POST /nlp/models/disney',
  },
  {
    id: 'chunking',
    name: 'Чанкинг (крупнее / конкретнее)',
    purpose: 'Поднять смысл цели или разбить на исполнимые куски',
    endpoint: 'POST /nlp/models/chunking',
  },
  {
    id: 'pack',
    name: 'Пакет моделей под цель',
    purpose: 'Сразу WFO + путь + SCORE + экология + первый тест',
    endpoint: 'POST /nlp/models/pack',
  },
];

function requireText(value, field) {
  const text = String(value || '').trim();
  if (!text) {
    const err = new Error(`${field} is required`);
    err.status = 400;
    throw err;
  }
  return text;
}

/** Полный чеклист хорошо сформулированного результата */
function buildWfoModel(input = {}) {
  const wfo = buildWfoLocal(input);
  const goal = wfo.outcome;
  const checks = [
    {
      key: 'positive',
      ok: !/^(не|без)\b/i.test(goal),
      label: 'Сформулирован позитивно (что будет, а не чего избегаем)',
    },
    {
      key: 'specific',
      ok: goal.length >= 12,
      label: 'Достаточно конкретен (не «улучшить всё»)',
    },
    {
      key: 'evidence',
      ok: Array.isArray(wfo.evidence) && wfo.evidence.length > 0,
      label: 'Есть сенсорные/наблюдаемые критерии готовности',
    },
    {
      key: 'selfInitiated',
      ok: Boolean(wfo.owner),
      label: 'Есть владелец результата (кто запускает действия)',
    },
    {
      key: 'deadline',
      ok: Boolean(wfo.deadline),
      label: 'Есть срок',
    },
    {
      key: 'firstStep',
      ok: Boolean(wfo.firstTest),
      label: 'Есть первый проверяемый шаг/тест',
    },
    {
      key: 'ecology',
      ok: Array.isArray(wfo.ecology) && wfo.ecology.length > 0,
      label: 'Продумано влияние на смежные процессы',
      optional: true,
    },
  ];

  const requiredFailed = checks.filter((c) => !c.optional && !c.ok);
  const tips = [];
  if (!wfo.owner) tips.push('Назначьте владельца результата');
  if (!wfo.deadline) tips.push('Поставьте дедлайн (хотя бы неделю)');
  if (!wfo.ecology.length) {
    tips.push('Добавьте 1–2 пункта экологии: кому/чему цель поможет или помешает');
  }

  return {
    model: 'wfo',
    therapy: false,
    wfo,
    checklist: checks,
    score: {
      passed: checks.filter((c) => c.ok).length,
      total: checks.length,
      ready: requiredFailed.length === 0,
    },
    nextActions: tips.length
      ? tips
      : ['Запустить TOTE-цикл: первый тест по firstTest'],
  };
}

/** Модель достижения цели: present → path → desired */
function buildGoalPathModel(input = {}) {
  const goal = requireText(input.goal || input.desired, 'goal');
  const present = String(input.present || input.current || 'Текущее состояние не описано').trim();
  const owner = input.owner ? String(input.owner).trim() : null;
  const deadline = input.deadline ? String(input.deadline).trim() : null;
  const obstacles = normalizeList(input.obstacles || input.blockers);
  const resources = normalizeList(input.resources);
  const wfo = buildWfoLocal({
    goal,
    owner,
    deadline,
    evidence: input.evidence,
    resources,
    firstTest: input.firstTest,
    successMetric: input.successMetric,
  });

  const milestones = normalizeList(input.milestones);
  if (milestones.length === 0) {
    milestones.push(
      'Зафиксировать критерий успеха и владельца',
      'Сделать первый тест и получить факт',
      'Убрать главный блокер процесса',
      'Повторять тест до закрытия критерия'
    );
  }

  const steps = [
    {
      stage: 'present',
      title: 'Где мы сейчас',
      detail: present,
    },
    {
      stage: 'gap',
      title: 'Разрыв',
      detail:
        obstacles.length > 0
          ? `Мешают: ${obstacles.join('; ')}`
          : 'Разрыв между текущим фактом и желаемым результатом',
    },
    {
      stage: 'milestones',
      title: 'Вехи пути',
      items: milestones,
    },
    {
      stage: 'desired',
      title: 'Желаемый результат',
      detail: wfo.outcome,
      evidence: wfo.evidence,
      successMetric: wfo.successMetric,
    },
    {
      stage: 'firstMove',
      title: 'Первый ход сегодня',
      detail: wfo.firstTest,
      owner: wfo.owner,
    },
  ];

  return {
    model: 'goal-path',
    therapy: false,
    owner,
    deadline,
    present,
    obstacles,
    resources: resources.length ? resources : ['Время владельца', 'Рабочий канал коммуникации'],
    wfo,
    path: steps,
    toteHint: {
      test: wfo.firstTest,
      operateIfFail: obstacles[0]
        ? `Снять блокер: ${obstacles[0]}`
        : 'Скорректировать канал/скрипт/ресурс и повторить тест',
      exitWhen: wfo.successMetric,
    },
    nextActions: [
      `Сделать: ${wfo.firstTest}`,
      owner ? `Ответственный: ${owner}` : 'Назначить ответственного',
    ],
  };
}

/** SCORE: Symptom, Cause, Outcome, Resources, Effects */
function buildScoreModel(input = {}) {
  const symptom = requireText(input.symptom || input.problem, 'symptom');
  const cause = String(input.cause || 'Причина не названа — уточнить процессный корень').trim();
  const outcome = String(input.outcome || input.goal || '').trim() ||
    `Устранён симптом: ${symptom}`;
  const resources = normalizeList(input.resources);
  if (resources.length === 0) {
    resources.push('Владелец процесса', 'Факты/метрика за последние 7 дней');
  }
  const effects = normalizeList(input.effects);
  if (effects.length === 0) {
    effects.push('Смежные роли получают предсказуемый статус', 'Меньше ручного контроля');
  }

  const wfo = buildWfoLocal({
    goal: outcome,
    owner: input.owner,
    deadline: input.deadline,
    evidence: input.evidence,
    firstTest: input.firstTest,
    successMetric: input.successMetric,
  });

  return {
    model: 'score',
    therapy: false,
    score: {
      symptom,
      cause,
      outcome: wfo.outcome,
      resources,
      effects,
    },
    wfo,
    bridgeToAction: {
      diagnose: `Проверить гипотезу причины: ${cause}`,
      intervene: wfo.firstTest,
      measure: wfo.successMetric,
    },
    nextActions: [wfo.firstTest, `Зафиксировать, верна ли причина: ${cause}`],
  };
}

/** Экологическая проверка цели */
function buildEcologyModel(input = {}) {
  const goal = requireText(input.goal || input.outcome, 'goal');
  const stakeholders = normalizeList(input.stakeholders || input.people);
  const plus = normalizeList(input.plus || input.benefits);
  const minus = normalizeList(input.minus || input.risks);
  const mitigations = normalizeList(input.mitigations);

  if (plus.length === 0) {
    plus.push('Появится ясный проверяемый результат у владельца');
  }
  if (minus.length === 0) {
    minus.push('Возможна перегрузка, если не снять старые задачи');
  }
  if (mitigations.length === 0) {
    mitigations.push('Ограничить WIP: одна главная цель на человека в периоде');
  }
  if (stakeholders.length === 0) {
    stakeholders.push(input.owner || 'владелец', 'смежная роль / клиент');
  }

  const questions = [
    'Кому станет легче, если цель достигнута?',
    'Кому станет сложнее / что может сломаться?',
    'Какую старую активность останавливаем, чтобы вместить новую?',
    'Какой сигнал скажет, что экология нарушена?',
  ];

  const ok = minus.length <= plus.length || mitigations.length > 0;

  return {
    model: 'ecology',
    therapy: false,
    goal,
    stakeholders,
    plus,
    minus,
    mitigations,
    questions,
    verdict: ok
      ? 'Экология приемлема при выполнении mitigations'
      : 'Нужно усилить компенсации рисков',
    nextActions: mitigations.slice(0, 2),
  };
}

/** Уточняющие вопросы к размытой цели */
function buildClarifyModel(input = {}) {
  const goal = requireText(input.goal || input.text, 'goal');
  const vague =
    goal.length < 20 ||
    /лучше|активнее|больше|качественнее|прокачать|улучшить всё|как-то/i.test(goal);

  const questions = [
    { ask: 'Что именно будет готово, когда цель достигнута?', targets: 'outcome' },
    { ask: 'Как это увидит/проверит сторонний наблюдатель?', targets: 'evidence' },
    { ask: 'Кто владелец результата и кто только информирован?', targets: 'owner' },
    { ask: 'К какому сроку нужен первый измеримый факт?', targets: 'deadline' },
    { ask: 'Что уже пробовали и какой был факт?', targets: 'present' },
    { ask: 'Что мешает прямо сейчас (один главный блокер)?', targets: 'blocker' },
    { ask: 'Какой один тест сделаем сегодня?', targets: 'firstTest' },
  ];

  const draft = buildWfoLocal({
    goal,
    owner: input.owner,
    deadline: input.deadline,
    evidence: input.evidence,
    firstTest: input.firstTest,
    successMetric: input.successMetric,
  });

  return {
    model: 'clarify',
    therapy: false,
    inputGoal: goal,
    isVague: vague,
    questions,
    draftWfo: draft,
    nextActions: vague
      ? ['Ответить на 3 вопроса: outcome / evidence / firstTest', 'Потом создать TOTE-цикл']
      : ['Цель достаточно ясна — можно запускать /nlp/cycle'],
  };
}

/** Disney: Dreamer / Realist / Critic для рабочей инициативы */
function buildDisneyModel(input = {}) {
  const idea = requireText(input.idea || input.goal, 'idea');
  const owner = input.owner ? String(input.owner).trim() : null;
  const dreamer = normalizeList(input.dreamer);
  const realist = normalizeList(input.realist);
  const critic = normalizeList(input.critic);

  if (dreamer.length === 0) {
    dreamer.push(
      `Успех выглядит так: ${idea}`,
      'Команда видит прогресс каждый день по одному факту'
    );
  }
  if (realist.length === 0) {
    realist.push(
      'План на 7 дней: ежедневный тест + вечерняя сверка',
      inferFirstTest(idea),
      'Один владелец, один канал статуса'
    );
  }
  if (critic.length === 0) {
    critic.push(
      'Риск: нет владельца или размытый критерий',
      'Риск: много активностей без WIP-лимита',
      'Контроль: если 2 дня нет факта — эскалация на разбор'
    );
  }

  const wfo = buildWfoLocal({
    goal: idea,
    owner,
    deadline: input.deadline,
    evidence: input.evidence,
    firstTest: realist[1] || input.firstTest,
    successMetric: input.successMetric,
  });

  return {
    model: 'disney',
    therapy: false,
    idea,
    positions: {
      dreamer,
      realist,
      critic,
    },
    synthesis: {
      go: true,
      condition: 'Есть владелец, критерий и ежедневный тест',
      firstTest: wfo.firstTest,
      killCriteria: critic.slice(0, 2),
    },
    wfo,
    nextActions: [wfo.firstTest, owner ? `Владелец: ${owner}` : 'Назначить владельца'],
  };
}

/** Чанкинг: смысл выше / шаги ниже */
function buildChunkingModel(input = {}) {
  const goal = requireText(input.goal, 'goal');
  const up = normalizeList(input.up);
  const down = normalizeList(input.down);

  if (up.length === 0) {
    up.push(
      `Зачем это бизнесу: прогресс по «${goal}»`,
      'Какой портфельный результат усиливается этой целью'
    );
  }
  if (down.length === 0) {
    down.push(
      inferFirstTest(goal),
      'Сверка факта в конце дня',
      'Коррекция процесса при провале теста'
    );
  }

  return {
    model: 'chunking',
    therapy: false,
    goal,
    chunkUp: up,
    chunkDown: down,
    recommendation:
      down.length >= 2
        ? 'Для исполнения берите chunk-down #1 как сегодняшний тест'
        : 'Добавьте 2–3 конкретных шага вниз',
    nextActions: [down[0], 'Если шаг слишком крупный — ещё раз chunk-down'],
  };
}

/** Пакет моделей сразу под рабочую цель */
function buildModelPack(input = {}) {
  const goal = requireText(input.goal, 'goal');
  const base = {
    goal,
    owner: input.owner,
    deadline: input.deadline,
    present: input.present || input.current,
    symptom: input.symptom || input.problem || `Нет прогресса по: ${goal}`,
    cause: input.cause || input.blocker || 'Не зафиксирован ежедневный тест/факт',
    obstacles: input.obstacles || input.blockers,
    resources: input.resources,
    stakeholders: input.stakeholders,
    evidence: input.evidence,
    firstTest: input.firstTest,
    successMetric: input.successMetric,
    idea: goal,
  };

  const wfo = buildWfoModel(base);
  const goalPath = buildGoalPathModel(base);
  const score = buildScoreModel(base);
  const ecology = buildEcologyModel(base);
  const clarify = buildClarifyModel(base);
  const disney = buildDisneyModel(base);
  const chunking = buildChunkingModel(base);

  return {
    model: 'pack',
    therapy: false,
    goal,
    summary: {
      outcome: wfo.wfo.outcome,
      successMetric: wfo.wfo.successMetric,
      firstTest: wfo.wfo.firstTest,
      owner: wfo.wfo.owner,
      ready: wfo.score.ready,
    },
    models: {
      wfo,
      goalPath,
      score,
      ecology,
      clarify,
      disney,
      chunking,
    },
    recommendedFlow: [
      '1. Уточнить цель (clarify), если isVague=true',
      '2. Зафиксировать WFO checklist ready',
      '3. Пройти ecology mitigations',
      '4. Запустить TOTE через /nlp/cycle или /nlp/morning',
      '5. Каждый день: test → при нужде operate',
    ],
    nextActions: [
      wfo.wfo.firstTest,
      ...ecology.mitigations.slice(0, 1),
    ],
  };
}

module.exports = {
  MODEL_CATALOG,
  buildWfoModel,
  buildGoalPathModel,
  buildScoreModel,
  buildEcologyModel,
  buildClarifyModel,
  buildDisneyModel,
  buildChunkingModel,
  buildModelPack,
};
