// Навыки NLP-мастера для ИИ-сотрудников — ТОЛЬКО рабочие процессы.
// Не терапия, не «лечение», не работа с травмой/личностью.

const MASTER_BOUNDARY = [
  'Режим: NLP-мастер для рабочих процессов коллектива.',
  'ТОЛЬКО: цели, критерии, коммуникации о работе, переговоры, скрипты, приоритеты, ритм исполнения.',
  'ЗАПРЕЩЕНО: терапия, травмы, детство, диагнозы, гипноз «для исцеления», работа с личными переживаниями.',
  'Каждый навык заканчивается конкретным nextAction и критерием факта.',
].join(' ');

/**
 * Максимальный набор операционных навыков NLP-мастера для AI-сотрудников.
 * Источники техник — классика NLP, но применение узко: бизнес/операционка.
 */
const MASTER_SKILLS = [
  {
    id: 'wfo-master',
    name: 'Мастер хорошо сформулированного результата',
    useWhen: 'Цель размыта или звучит как «надо лучше»',
    steps: [
      'Сформулировать позитивно (что будет)',
      'Доказать evidence наблюдаемыми фактами',
      'Назначить владельца и срок',
      'Задать firstTest на сегодня',
    ],
    output: ['outcome', 'evidence', 'owner', 'deadline', 'firstTest'],
  },
  {
    id: 'tote-master',
    name: 'Мастер TOTE-цикла',
    useWhen: 'Нужен ритм: тест → коррекция → снова тест',
    steps: [
      'Определить критерий Test',
      'Зафиксировать факт pass/fail',
      'Operate: одна коррекция процесса',
      'Exit только по evidence',
    ],
    output: ['test', 'operate', 'exitWhen'],
  },
  {
    id: 'meta-model',
    name: 'Мета-модель (точная речь)',
    useWhen: 'В речи удаления, обобщения, искажения («всегда», «не могут», «надо»)',
    steps: [
      'Поймать неточный фрагмент',
      'Задать 1–3 уточняющих вопроса',
      'Переписать в измеримую формулировку',
    ],
    output: ['vaguePhrase', 'questions', 'preciseRewrite'],
  },
  {
    id: 'chunking',
    name: 'Чанкинг вверх/вниз',
    useWhen: 'Цель слишком крупная или слишком мелкая',
    steps: [
      'Chunk-up: зачем бизнесу',
      'Chunk-down: 3 исполнимых шага',
      'Выбрать шаг #1 как тест дня',
    ],
    output: ['chunkUp', 'chunkDown', 'todayTest'],
  },
  {
    id: 'score-master',
    name: 'SCORE для операционных сбоев',
    useWhen: 'Есть симптом в процессе (нет показов, срыв срока)',
    steps: [
      'Symptom → Cause → Outcome',
      'Resources → Effects',
      'Связать с одним вмешательством',
    ],
    output: ['symptom', 'cause', 'outcome', 'intervene'],
  },
  {
    id: 'reframing',
    name: 'Рабочий рефрейминг',
    useWhen: 'Команда застряла в формулировке проблемы',
    steps: [
      'Отделить факт от интерпретации',
      'Контекстный рефрейм: где это ресурс',
      'Содержательный: какая другая причина/смысл у факта',
      'Вернуть в nextAction',
    ],
    output: ['fact', 'oldFrame', 'newFrame', 'nextAction'],
  },
  {
    id: 'positions',
    name: 'Позиции восприятия (1–2–3)',
    useWhen: 'Переговоры, конфликт ролей, клиент/коллега',
    steps: [
      '1 позиция: цель и критерий нашей стороны',
      '2 позиция: интересы и критерий другой стороны',
      '3 позиция: наблюдатель — зона соглашения',
    ],
    output: ['self', 'other', 'observer', 'agreementMove'],
  },
  {
    id: 'strategy-elicitation',
    name: 'Элиситация стратегии успеха',
    useWhen: 'Нужно скопировать рабочий алгоритм лучшего исполнителя',
    steps: [
      'Триггер: что запускает действие',
      'Процедура: шаги 1…n',
      'Тест: как понимает «готово»',
      'Exit: когда останавливается / эскалирует',
    ],
    output: ['trigger', 'procedure', 'test', 'exit', 'playbook'],
  },
  {
    id: 'criteria',
    name: 'Критерии и приоритеты решения',
    useWhen: 'Выбор между вариантами (цена/срок/качество)',
    steps: [
      'Собрать критерии решения',
      'Отсортировать must / should',
      'Прогнать варианты через must',
      'Выбрать и назначить тест',
    ],
    output: ['must', 'should', 'decision', 'test'],
  },
  {
    id: 'objection-handle',
    name: 'Работа с возражениями (продажи/согласования)',
    useWhen: 'Клиент или стейкхолдер говорит «дорого/не сейчас/надо подумать»',
    steps: [
      'Уточнить точный смысл возражения',
      'Отделить условие от отказа',
      'Предложить проверяемый next step',
    ],
    output: ['objection', 'meaning', 'condition', 'nextStep'],
  },
  {
    id: 'agreement-frame',
    name: 'Рамка соглашения',
    useWhen: 'Нужно зафиксировать договорённость без воды',
    steps: [
      'Что согласовано',
      'Кто делает',
      'Срок и evidence',
      'Что будет при срыве (эскалация)',
    ],
    output: ['agreement', 'owner', 'deadline', 'evidence', 'escalation'],
  },
  {
    id: 'ecology-ops',
    name: 'Экология рабочей системы',
    useWhen: 'Новая цель может перегрузить команду',
    steps: [
      'Кому станет легче/сложнее',
      'Что выключаем из WIP',
      'Сигнал нарушения экологии',
    ],
    output: ['plus', 'minus', 'stopDoing', 'signal'],
  },
  {
    id: 'grow-will',
    name: 'GROW + воля (commitment)',
    useWhen: 'Есть идеи, нет обязательства к действию',
    steps: [
      'Goal / Reality / Options',
      'Will: одно действие',
      'Commitment 1–10; если <8 — упростить',
    ],
    output: ['will', 'commitment', 'raiseIfLow'],
  },
  {
    id: 'ppp-cadence',
    name: 'PPP weekly cadence',
    useWhen: 'Нужен короткий статус для руководителя',
    steps: [
      'Plans на период',
      'Progress факты',
      'Problems/блокеры',
      'Confidence 1–10',
    ],
    output: ['plans', 'progress', 'problems', 'confidence'],
  },
  {
    id: 'outcome-evidence',
    name: 'Сенсорные evidence результата',
    useWhen: 'Спорят «сделано / не сделано»',
    steps: [
      'Описать, что увидит наблюдатель',
      'Какой артефакт обязателен',
      'Binary: есть/нет',
    ],
    output: ['observerSee', 'artifact', 'binaryCheck'],
  },
];

const ROLE_PRESETS = {
  sales: [
    'wfo-master',
    'objection-handle',
    'positions',
    'tote-master',
    'ppp-cadence',
    'agreement-frame',
    'meta-model',
  ],
  ops: [
    'tote-master',
    'score-master',
    'wfo-master',
    'ecology-ops',
    'ppp-cadence',
    'chunking',
    'criteria',
  ],
  manager: [
    'grow-will',
    'wfo-master',
    'ecology-ops',
    'ppp-cadence',
    'criteria',
    'positions',
    'meta-model',
    'reframing',
  ],
  analyst: [
    'meta-model',
    'score-master',
    'outcome-evidence',
    'chunking',
    'criteria',
    'strategy-elicitation',
  ],
  closer: [
    'objection-handle',
    'agreement-frame',
    'positions',
    'outcome-evidence',
    'tote-master',
    'wfo-master',
  ],
  general: MASTER_SKILLS.map((s) => s.id),
};

function getSkill(id) {
  return MASTER_SKILLS.find((s) => s.id === id) || null;
}

function buildEmployeeSkillPack({ role = 'general', staff, focus } = {}) {
  const roleKey = String(role || 'general').toLowerCase();
  const ids = ROLE_PRESETS[roleKey] || ROLE_PRESETS.general;
  const skills = ids.map(getSkill).filter(Boolean);

  const systemPrompt = [
    MASTER_BOUNDARY,
    staff ? `ИИ-сотрудник / роль: ${staff}.` : 'ИИ-сотрудник коллектива.',
    focus ? `Рабочий фокус: ${focus}.` : null,
    `Роль-профиль: ${roleKey}.`,
    'Ты применяешь навыки NLP-мастера только к рабочим процессам.',
    'Формат ответа всегда:',
    '1) навык который используешь',
    '2) точная рабочая формулировка',
    '3) nextAction (один шаг)',
    '4) evidence факта (как проверить)',
    'Не морализируй. Не углубляйся в личное.',
    'Доступные навыки: ' + skills.map((s) => s.id).join(', ') + '.',
  ]
    .filter(Boolean)
    .join('\n');

  return {
    therapy: false,
    mode: 'nlp-master-work-only',
    staff: staff || null,
    role: roleKey,
    focus: focus || null,
    skills,
    systemPrompt,
    howToUse: [
      'Подключи systemPrompt к ИИ-сотруднику как системную инструкцию',
      'Для задачи вызови POST /nlp/skills/apply с skillId и situation',
      'Держи TOTE/OKR/check-in как внешний ритм исполнения',
    ],
  };
}

function applyMasterSkill({ skillId, situation, staff, role, goal, blocker, counterpart }) {
  const skill = getSkill(skillId);
  if (!skill) {
    const err = new Error(`unknown skillId: ${skillId}`);
    err.status = 400;
    throw err;
  }
  const sit = String(situation || goal || '').trim();
  if (!sit) {
    const err = new Error('situation or goal is required');
    err.status = 400;
    throw err;
  }

  const base = {
    skillId: skill.id,
    skillName: skill.name,
    therapy: false,
    staff: staff || null,
    role: role || null,
    situation: sit,
    steps: skill.steps,
  };

  // Детерминированные рабочие заготовки по навыку (без LLM).
  switch (skill.id) {
    case 'wfo-master':
      return {
        ...base,
        result: {
          outcome: sit.replace(/^(не\s+|без\s+)/i, '').trim(),
          evidence: ['Наблюдаемый артефакт (договор/статус/отчёт)'],
          owner: staff || 'владелец процесса',
          firstTest: 'Один проверяемый шаг сегодня + фиксация факта',
        },
        nextAction: 'Один проверяемый шаг сегодня + фиксация факта',
        evidence: 'Артефакт появился в рабочем контуре',
      };
    case 'tote-master':
      return {
        ...base,
        result: {
          test: `Сверка факта по: ${sit}`,
          operate: blocker
            ? `Снять блокер: ${blocker}`
            : 'Сменить канал/скрипт/ресурс и повторить тест',
          exitWhen: 'Критерий успеха подтверждён фактом',
        },
        nextAction: 'Запустить test и записать pass/fail',
        evidence: 'Есть запись test в цикле',
      };
    case 'meta-model':
      return {
        ...base,
        result: {
          vaguePhrase: sit,
          questions: [
            'Что именно будет готово?',
            'Как это проверит наблюдатель?',
            'Кто владелец и какой срок первого факта?',
          ],
          preciseRewrite: `К сроку X владелец Y достигает: ${sit}, evidence = артефакт Z`,
        },
        nextAction: 'Ответить на 3 уточняющих вопроса и переписать цель',
        evidence: 'Появилась формулировка с владельцем/сроком/evidence',
      };
    case 'chunking':
      return {
        ...base,
        result: {
          chunkUp: [`Бизнес-эффект от: ${sit}`],
          chunkDown: [
            'Зафиксировать критерий успеха',
            'Сделать первый тест',
            'Сверка факта вечером',
          ],
          todayTest: 'Зафиксировать критерий успеха и сделать первый тест',
        },
        nextAction: 'Сделать chunk-down шаг #1',
        evidence: 'Шаг #1 отмечен фактом',
      };
    case 'score-master':
      return {
        ...base,
        result: {
          symptom: sit,
          cause: blocker || 'Не зафиксирован ежедневный тест/факт',
          outcome: `Устранён сбой: ${sit}`,
          intervene: 'Один процессный рычаг + тест сегодня',
        },
        nextAction: 'Проверить гипотезу причины одним тестом',
        evidence: 'Симптом снизился по метрике',
      };
    case 'reframing':
      return {
        ...base,
        result: {
          fact: sit,
          oldFrame: 'Это тупик',
          newFrame: 'Это сигнал, какой рычаг процесса усилить',
          nextAction: 'Выбрать один рычаг и протестировать до вечера',
        },
        nextAction: 'Выбрать один рычаг и протестировать до вечера',
        evidence: 'Есть новый тест после рефрейма',
      };
    case 'positions':
      return {
        ...base,
        result: {
          self: { goal: sit, criterion: 'Наш measurable outcome' },
          other: {
            party: counterpart || 'вторая сторона',
            criterion: 'Их выгода/риск',
          },
          observer: 'Зона соглашения = пересечение критериев',
          agreementMove: 'Предложить проверяемый next step обеим сторонам',
        },
        nextAction: 'Предложить next step, приемлемый для обеих сторон',
        evidence: 'Есть согласие на следующий шаг со сроком',
      };
    case 'strategy-elicitation':
      return {
        ...base,
        result: {
          trigger: 'Старт дня / новый лид / новый статус',
          procedure: [
            'Квалификация',
            'Касание',
            'Фиксация next step',
            'Сверка факта',
          ],
          test: 'Есть next step со сроком',
          exit: 'Эскалация если 2 цикла без прогресса',
          playbook: `Стратегия под задачу: ${sit}`,
        },
        nextAction: 'Прогнать процедуру на 1 реальном кейсе',
        evidence: 'Кейс прошёл trigger→test',
      };
    case 'criteria':
      return {
        ...base,
        result: {
          must: ['Измеримый результат', 'Владелец', 'Срок'],
          should: ['Низкая нагрузка на смежных', 'Повторное использование'],
          decision: `Вариант, закрывающий must для: ${sit}`,
          test: 'Пилот на 1 итерацию',
        },
        nextAction: 'Отсечь варианты без must и запустить пилот',
        evidence: 'Выбран 1 вариант + тест',
      };
    case 'objection-handle':
      return {
        ...base,
        result: {
          objection: sit,
          meaning: 'Уточнить: цена / срок / риск / приоритет?',
          condition: 'При каком условии готовы к следующему шагу?',
          nextStep: 'Малый проверяемый шаг (созвон/показ/сравнение)',
        },
        nextAction: 'Уточнить условие и предложить малый next step',
        evidence: 'Назначен следующий контакт/действие',
      };
    case 'agreement-frame':
      return {
        ...base,
        result: {
          agreement: sit,
          owner: staff || 'владелец',
          deadline: 'срок в рамках текущего периода',
          evidence: 'Артефакт договорённости',
          escalation: 'Если нет факта к сроку — разбор у руководителя',
        },
        nextAction: 'Записать договорённость: кто/что/срок/evidence',
        evidence: 'Запись видна обеим сторонам',
      };
    case 'ecology-ops':
      return {
        ...base,
        result: {
          plus: ['Ясный результат'],
          minus: ['Риск перегрузки WIP'],
          stopDoing: 'Остановить наименее ценную активность',
          signal: '2 дня без факта или срыв смежного срока',
        },
        nextAction: 'Выключить 1 задачу из WIP перед стартом',
        evidence: 'WIP уменьшен, цель в фокусе',
      };
    case 'grow-will':
      return {
        ...base,
        result: {
          will: `Сделать один шаг по: ${sit}`,
          commitment: 8,
          raiseIfLow: ['Упростить до 30 минут', 'Публичный check-in'],
        },
        nextAction: `Сделать один шаг по: ${sit}`,
        evidence: 'Шаг отмечен в check-in/цикле',
      };
    case 'ppp-cadence':
      return {
        ...base,
        result: {
          plans: `План по: ${sit}`,
          progress: 'Факты за период (числа/артефакты)',
          problems: blocker ? [String(blocker)] : ['Нет блокера / указать'],
          confidence: 6,
        },
        nextAction: 'Отправить PPP + confidence в /nlp/checkin',
        evidence: 'Check-in сохранён',
      };
    case 'outcome-evidence':
      return {
        ...base,
        result: {
          observerSee: `Наблюдатель видит готовый результат: ${sit}`,
          artifact: 'Файл/статус/договор/сообщение',
          binaryCheck: 'есть / нет',
        },
        nextAction: 'Зафиксировать binary evidence в цикле',
        evidence: 'Binary check = есть',
      };
    default:
      return {
        ...base,
        result: {},
        nextAction: skill.steps[0],
        evidence: 'Факт зафиксирован',
      };
  }
}

function buildMasterPlaybook({ role = 'general', staff, focus } = {}) {
  const pack = buildEmployeeSkillPack({ role, staff, focus });
  return {
    ...pack,
    dailyRitual: [
      'Утро: WFO/TOTE — один firstTest',
      'День: meta-model + execute',
      'Вечер: PPP/check-in confidence',
      'Неделя: digest + retro',
    ],
    escalationRules: [
      'confidence ≤ 3 два check-in подряд → review',
      'нет факта 48ч → operate обязателен',
      'commitment < 8 → не раздувать scope',
    ],
  };
}

module.exports = {
  MASTER_BOUNDARY,
  MASTER_SKILLS,
  ROLE_PRESETS,
  getSkill,
  buildEmployeeSkillPack,
  applyMasterSkill,
  buildMasterPlaybook,
};
