// Операционный NLP для коллектива (НЕ терапия).
// Язык результата, критерии, тесты и коррекции — без психологии/лечения.

const SYSTEM_BOUNDARY = [
  'Режим: операционный NLP для коллектива.',
  'ЗАПРЕЩЕНО: терапия, травмы, детство, «внутренний ребёнок», диагнозы, эмоции ради эмоций.',
  'РАЗРЕШЕНО: цели, критерии, роли, действия, сроки, проверки факта, коррекции процесса.',
  'Тон: прямой, конкретный, измеримый. Каждый вывод — с следующим шагом.',
].join(' ');

function buildWfoPrompt({ goal, context, owner, deadline }) {
  return [
    SYSTEM_BOUNDARY,
    'Задача: оформить Well-Formed Outcome (WFO) для рабочей цели коллектива.',
    `Сырая цель: ${goal}`,
    owner ? `Владелец результата: ${owner}` : null,
    deadline ? `Дедлайн: ${deadline}` : null,
    context ? `Контекст: ${context}` : null,
    '',
    'Верни строго JSON-объект со полями:',
    '{',
    '  "outcome": "позитивная формулировка результата (что будет, а не чего избегаем)",',
    '  "evidence": ["как поймём, что готово — наблюдаемые факты"],',
    '  "resources": ["что уже есть / что нужно"],',
    '  "ecology": ["влияние на смежные процессы/людей — только операционно"],',
    '  "firstTest": "первый конкретный тест на сегодня/завтра",',
    '  "successMetric": "одна измеримая метрика"',
    '}',
  ]
    .filter(Boolean)
    .join('\n');
}

function buildTotePrompt({ cycle, event }) {
  return [
    SYSTEM_BOUNDARY,
    'Задача: продвинуть TOTE-цикл (Test → Operate → Test → Exit) по рабочей цели.',
    `Цель (outcome): ${cycle.wfo.outcome}`,
    `Метрика успеха: ${cycle.wfo.successMetric}`,
    `Текущая фаза: ${cycle.phase}`,
    `Итерация: ${cycle.iteration}`,
    `Последний тест: ${JSON.stringify(cycle.lastTest || null)}`,
    `Последняя операция: ${JSON.stringify(cycle.lastOperate || null)}`,
    event ? `Новое событие от команды: ${JSON.stringify(event)}` : null,
    '',
    'Верни строго JSON:',
    '{',
    '  "phase": "test|operate|exit",',
    '  "assessment": "краткая сверка с критерием успеха",',
    '  "gap": "что ещё не закрыто (или null если exit)",',
    '  "nextAction": "одно конкретное действие владельца/команды",',
    '  "ownerHint": "кому делать",',
    '  "done": true/false',
    '}',
  ]
    .filter(Boolean)
    .join('\n');
}

function buildStaffCyclePrompt({ staff, focus, notes }) {
  return [
    SYSTEM_BOUNDARY,
    'Задача: операционный NLP-цикл сотрудника/роли в коллективе (не коучинг-терапия).',
    `Сотрудник/роль: ${staff}`,
    focus ? `Фокус периода: ${focus}` : null,
    notes ? `Заметки/факты: ${notes}` : null,
    '',
    'Верни строго JSON:',
    '{',
    '  "wfo": { "outcome": "", "successMetric": "", "evidence": [] },',
    '  "todayTest": "что проверить сегодня одним действием",',
    '  "operateIfFail": "что менять в процессе, если тест не пройден",',
    '  "exitWhen": "условие выхода из цикла",',
    '  "standupLine": "одна строка для стендапа: цель / тест / блокер"',
    '}',
  ]
    .filter(Boolean)
    .join('\n');
}

module.exports = {
  SYSTEM_BOUNDARY,
  buildWfoPrompt,
  buildTotePrompt,
  buildStaffCyclePrompt,
};
