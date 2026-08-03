// OKR-слой по мотивам Tability / Weekdone / Perdoo.
// Objective + Key Results + прогресс + статус on_track|at_risk|off_track.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const STATUSES = ['on_track', 'at_risk', 'off_track'];

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function statusFrom({ progress, confidence, overdue }) {
  if (overdue && progress < 100) return 'off_track';
  if (typeof confidence === 'number') {
    if (confidence <= 3) return 'off_track';
    if (confidence <= 6) return 'at_risk';
  }
  if (progress < 30) return 'at_risk';
  return 'on_track';
}

function createOkrStore(baseDir) {
  const dir = path.join(baseDir, 'nlp-okrs');
  fs.mkdirSync(dir, { recursive: true });

  function fileFor(id) {
    return path.join(dir, `${id}.json`);
  }

  function save(okr) {
    fs.writeFileSync(fileFor(okr.id), JSON.stringify(okr, null, 2), 'utf8');
    return okr;
  }

  function get(id) {
    const fp = fileFor(id);
    if (!fs.existsSync(fp)) return null;
    return enrich(JSON.parse(fs.readFileSync(fp, 'utf8')));
  }

  function list({ limit = 100, status, owner } = {}) {
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith('.json'))
      .map((f) => {
        try {
          return enrich(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .filter((o) => (status ? o.status === status : true))
      .filter((o) =>
        owner
          ? String(o.owner || '').toLowerCase() === String(owner).toLowerCase()
          : true
      )
      .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
      .slice(0, limit);
  }

  function enrich(okr) {
    const keyResults = (okr.keyResults || []).map((kr) => {
      const target = Number(kr.target || 100) || 100;
      const current = Number(kr.current || 0) || 0;
      const progress = clamp(Math.round((current / target) * 100), 0, 100);
      const overdue =
        Boolean(kr.deadline) &&
        Date.parse(kr.deadline) < Date.now() &&
        progress < 100;
      const status = statusFrom({
        progress,
        confidence: kr.confidence,
        overdue,
      });
      return { ...kr, progress, overdue, status };
    });

    const progress =
      keyResults.length === 0
        ? 0
        : Math.round(
            keyResults.reduce((s, kr) => s + kr.progress, 0) / keyResults.length
          );
    const confidences = keyResults
      .map((kr) => kr.confidence)
      .filter((c) => typeof c === 'number');
    const confidence =
      confidences.length === 0
        ? null
        : Math.round(
            confidences.reduce((s, c) => s + c, 0) / confidences.length
          );
    const overdue = keyResults.some((kr) => kr.overdue);
    const status = statusFrom({ progress, confidence, overdue });

    return {
      ...okr,
      keyResults,
      progress,
      confidence,
      overdue,
      status,
    };
  }

  function create({
    objective,
    owner,
    period,
    parentId,
    keyResults,
    team,
    deadline,
  }) {
    const obj = String(objective || '').trim();
    if (!obj) {
      const err = new Error('objective is required');
      err.status = 400;
      throw err;
    }
    const now = new Date().toISOString();
    const krs = (Array.isArray(keyResults) ? keyResults : []).map((kr, i) => ({
      id: crypto.randomBytes(4).toString('hex'),
      title: String(kr.title || kr.name || `KR ${i + 1}`).trim(),
      metric: kr.metric || null,
      current: Number(kr.current || 0) || 0,
      target: Number(kr.target || 100) || 100,
      unit: kr.unit || '%',
      confidence: typeof kr.confidence === 'number' ? kr.confidence : 5,
      deadline: kr.deadline || deadline || null,
      owner: kr.owner || owner || null,
    }));

    if (krs.length === 0) {
      krs.push({
        id: crypto.randomBytes(4).toString('hex'),
        title: `Прогресс по: ${obj}`,
        metric: 'completion',
        current: 0,
        target: 100,
        unit: '%',
        confidence: 5,
        deadline: deadline || null,
        owner: owner || null,
      });
    }

    return save(
      enrich({
        id: crypto.randomBytes(6).toString('hex'),
        kind: 'okr',
        objective: obj,
        owner: owner || null,
        team: team || null,
        period: period || 'quarter',
        parentId: parentId || null,
        deadline: deadline || null,
        keyResults: krs,
        checkIns: [],
        createdAt: now,
        updatedAt: now,
        therapy: false,
      })
    );
  }

  function updateKr(okrId, krId, patch = {}) {
    const okr = get(okrId);
    if (!okr) return null;
    const keyResults = okr.keyResults.map((kr) => {
      if (kr.id !== krId) return kr;
      const next = { ...kr };
      if (patch.title != null) next.title = String(patch.title);
      if (patch.current != null) next.current = Number(patch.current) || 0;
      if (patch.target != null) next.target = Number(patch.target) || 100;
      if (patch.confidence != null) {
        next.confidence = clamp(Number(patch.confidence), 1, 10);
      }
      if (patch.deadline != null) next.deadline = patch.deadline;
      if (patch.metric != null) next.metric = patch.metric;
      if (patch.unit != null) next.unit = patch.unit;
      return next;
    });
    if (!keyResults.find((kr) => kr.id === krId)) {
      const err = new Error('key result not found');
      err.status = 404;
      throw err;
    }
    return save(
      enrich({
        ...okr,
        keyResults,
        updatedAt: new Date().toISOString(),
      })
    );
  }

  function addCheckIn(okrId, checkIn) {
    const okr = get(okrId);
    if (!okr) return null;
    const entry = {
      id: crypto.randomBytes(4).toString('hex'),
      at: new Date().toISOString(),
      ...checkIn,
    };
    const checkIns = [...(okr.checkIns || []), entry].slice(-52);
    // если в check-in пришли обновления KR — применим
    let keyResults = okr.keyResults;
    if (Array.isArray(checkIn.krUpdates)) {
      for (const u of checkIn.krUpdates) {
        keyResults = keyResults.map((kr) => {
          if (kr.id !== u.id && kr.title !== u.title) return kr;
          return {
            ...kr,
            current: u.current != null ? Number(u.current) : kr.current,
            confidence:
              u.confidence != null
                ? clamp(Number(u.confidence), 1, 10)
                : kr.confidence,
          };
        });
      }
    } else if (typeof checkIn.confidence === 'number') {
      keyResults = keyResults.map((kr) => ({
        ...kr,
        confidence: clamp(Number(checkIn.confidence), 1, 10),
      }));
    }

    return save(
      enrich({
        ...okr,
        keyResults,
        checkIns,
        updatedAt: entry.at,
      })
    );
  }

  return { create, get, list, updateKr, addCheckIn, dir, STATUSES };
}

/** Быстрый конструктор OKR из бизнес-цели (аренда/продажи и т.п.) */
function suggestOkrsFromGoal({ goal, owner, deadline }) {
  const g = String(goal || '').trim();
  if (!g) {
    const err = new Error('goal is required');
    err.status = 400;
    throw err;
  }
  const lower = g.toLowerCase();
  let keyResults;
  if (/аренд|лот|помещ|сдат/.test(lower)) {
    keyResults = [
      { title: 'Число подписанных договоров / предоплат', current: 0, target: 3, unit: 'шт', confidence: 5 },
      { title: 'Показы в неделю', current: 0, target: 6, unit: 'шт', confidence: 5 },
      { title: 'Целевые касания в неделю', current: 0, target: 40, unit: 'шт', confidence: 5 },
    ];
  } else if (/лид|продаж|выручк/.test(lower)) {
    keyResults = [
      { title: 'Закрытые сделки', current: 0, target: 5, unit: 'шт', confidence: 5 },
      { title: 'Конверсия лид→сделка', current: 0, target: 20, unit: '%', confidence: 5 },
    ];
  } else {
    keyResults = [
      { title: 'Выполнение цели', current: 0, target: 100, unit: '%', confidence: 5 },
      { title: 'Еженедельные check-in без пропуска', current: 0, target: 8, unit: 'шт', confidence: 6 },
    ];
  }
  return {
    objective: g,
    owner: owner || null,
    deadline: deadline || null,
    keyResults,
  };
}

module.exports = {
  createOkrStore,
  suggestOkrsFromGoal,
  statusFrom,
  STATUSES,
};
