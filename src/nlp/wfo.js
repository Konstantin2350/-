// Well-Formed Outcome — операционная формулировка результата (не терапия).

function normalizeList(value) {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map(String).map((s) => s.trim()).filter(Boolean);
  }
  return String(value)
    .split(/\n|;/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function inferEvidence(goal) {
  const g = String(goal || '').toLowerCase();
  if (/аренд|лот|помещ|сдат/.test(g)) {
    return [
      'Подписанный договор или подтверждённая предоплата',
      'Фиксация статуса лота: занят / бронь',
    ];
  }
  if (/лид|продаж|звонк/.test(g)) {
    return ['Запись в CRM/чате: следующий шаг и срок ответа клиента'];
  }
  return ['Есть наблюдаемый артефакт/факт, который подтверждает готовность'];
}

function inferFirstTest(goal) {
  const g = String(goal || '').toLowerCase();
  if (/аренд|лот|помещ|сдат/.test(g)) {
    return '1 показ или 5 целевых касаний + вечерняя сверка факта';
  }
  if (/лид|продаж|звонк/.test(g)) {
    return 'Сделать пачку касаний и зафиксировать число ответов';
  }
  return 'Сделать один конкретный шаг и зафиксировать факт результата';
}

/**
 * Собирает WFO из полей запроса без LLM.
 */
function buildWfoLocal({
  goal,
  owner,
  deadline,
  evidence,
  resources,
  ecology,
  firstTest,
  successMetric,
}) {
  const outcomeRaw = String(goal || '').trim();
  if (!outcomeRaw) {
    const err = new Error('goal is required');
    err.status = 400;
    throw err;
  }

  // Позитивная формулировка: убираем типичные «не/без» в начале.
  const outcome = outcomeRaw.replace(/^(не\s+|без\s+)/i, '').trim() || outcomeRaw;

  const evidenceList = normalizeList(evidence);
  if (evidenceList.length === 0) {
    evidenceList.push(...inferEvidence(outcome));
  }

  return {
    outcome,
    owner: owner ? String(owner).trim() : null,
    deadline: deadline ? String(deadline).trim() : null,
    evidence: evidenceList,
    resources: normalizeList(resources),
    ecology: normalizeList(ecology),
    firstTest: firstTest ? String(firstTest).trim() : inferFirstTest(outcome),
    successMetric: successMetric
      ? String(successMetric).trim()
      : `Цель закрыта по согласованным evidence: ${evidenceList[0]}`,
    mode: 'operational',
  };
}

function validateWfo(wfo) {
  const missing = [];
  if (!wfo?.outcome) missing.push('outcome');
  if (!wfo?.successMetric) missing.push('successMetric');
  if (!Array.isArray(wfo?.evidence) || wfo.evidence.length === 0) {
    missing.push('evidence');
  }
  if (!wfo?.firstTest) missing.push('firstTest');
  return { ok: missing.length === 0, missing };
}

module.exports = {
  buildWfoLocal,
  validateWfo,
  normalizeList,
  inferEvidence,
  inferFirstTest,
};
