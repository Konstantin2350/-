// Well-Formed Outcome — операционная формулировка результата (не терапия).

function normalizeList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(String).map((s) => s.trim()).filter(Boolean);
  return String(value)
    .split(/\n|;/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Собирает WFO из полей запроса без LLM.
 * Если чего-то не хватает — заполняет рабочими заглушками, которые команда уточнит.
 */
function buildWfoLocal({ goal, owner, deadline, evidence, resources, ecology, firstTest, successMetric }) {
  const outcome = String(goal || '').trim();
  if (!outcome) {
    const err = new Error('goal is required');
    err.status = 400;
    throw err;
  }

  // Позитивная формулировка: убираем типичные «не/без» в начале как мягкую подсказку.
  const positive = outcome.replace(/^(не\s+|без\s+)/i, '').trim() || outcome;

  const evidenceList = normalizeList(evidence);
  if (evidenceList.length === 0) {
    evidenceList.push('Есть наблюдаемый артефакт/факт, который подтверждает готовность');
  }

  return {
    outcome: positive,
    owner: owner ? String(owner).trim() : null,
    deadline: deadline ? String(deadline).trim() : null,
    evidence: evidenceList,
    resources: normalizeList(resources),
    ecology: normalizeList(ecology),
    firstTest: firstTest
      ? String(firstTest).trim()
      : 'Сделать один конкретный шаг и зафиксировать факт результата',
    successMetric: successMetric
      ? String(successMetric).trim()
      : 'Цель закрыта по согласованным evidence',
    mode: 'operational', // явно не therapy
  };
}

function validateWfo(wfo) {
  const missing = [];
  if (!wfo?.outcome) missing.push('outcome');
  if (!wfo?.successMetric) missing.push('successMetric');
  if (!Array.isArray(wfo?.evidence) || wfo.evidence.length === 0) missing.push('evidence');
  if (!wfo?.firstTest) missing.push('firstTest');
  return { ok: missing.length === 0, missing };
}

module.exports = {
  buildWfoLocal,
  validateWfo,
  normalizeList,
};
