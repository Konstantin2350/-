// Weekly check-in + PPP + digest + retro — лучшие практики Tability / Weekdone / Range.
const { withRuntimeFlags, buildBoard } = require('./tote');

function clampConfidence(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return null;
  return Math.max(1, Math.min(10, Math.round(n)));
}

/**
 * Нормализует weekly check-in:
 * - confidence 1..10
 * - PPP: plans / progress / problems (Weekdone)
 * - blocker, win, nextTest
 */
function buildCheckInPayload(body = {}) {
  const confidence = clampConfidence(body.confidence);
  if (confidence == null) {
    const err = new Error('confidence (1-10) is required');
    err.status = 400;
    throw err;
  }

  const plans = body.plans || body.plan || null;
  const progress = body.progress || body.progressNote || null;
  const problems = body.problems || body.blocker || body.blockers || null;

  return {
    kind: 'weekly',
    staff: body.staff || body.owner || null,
    confidence,
    ppp: {
      plans: plans ? String(plans) : null,
      progress: progress ? String(progress) : null,
      problems: problems
        ? Array.isArray(problems)
          ? problems.map(String)
          : [String(problems)]
        : [],
    },
    win: body.win ? String(body.win) : null,
    nextTest: body.nextTest || body.nextAction || null,
    note: body.note ? String(body.note) : null,
    krUpdates: Array.isArray(body.krUpdates) ? body.krUpdates : undefined,
    commitment: clampConfidence(body.commitment), // GROW Will 1..10
  };
}

function applyCheckInToCycle(cycle, payload) {
  const now = new Date().toISOString();
  const checkIns = Array.isArray(cycle.checkIns) ? [...cycle.checkIns] : [];
  checkIns.push({ ...payload, at: now });
  const blocker =
    payload.ppp.problems[0] || cycle.blocker || null;
  const nextAction =
    payload.nextTest ||
    cycle.nextAction ||
    cycle.wfo?.firstTest ||
    null;

  let status = cycle.status;
  let phase = cycle.phase;
  // низкая уверенность → нужно operate / review сигнала
  if (cycle.status === 'active' && payload.confidence <= 3) {
    phase = 'operate';
  }

  const history = [
    ...(cycle.history || []),
    {
      type: 'checkin',
      at: now,
      confidence: payload.confidence,
      note: payload.note || payload.ppp.progress,
      problems: payload.ppp.problems,
    },
  ];

  return withRuntimeFlags({
    ...cycle,
    checkIns: checkIns.slice(-52),
    confidence: payload.confidence,
    commitment: payload.commitment,
    blocker,
    nextAction,
    phase,
    status,
    history,
    lastCheckInAt: now,
    trafficLight:
      payload.confidence <= 3
        ? 'off_track'
        : payload.confidence <= 6
          ? 'at_risk'
          : 'on_track',
  });
}

function buildDigest({ cycles = [], okrs = [] } = {}) {
  const board = buildBoard(cycles);
  const enrichedCycles = cycles.map((c) => withRuntimeFlags(c));
  const dueCheckIn = enrichedCycles.filter((c) => {
    if (c.status !== 'active') return false;
    if (!c.lastCheckInAt) return true;
    const ageH = (Date.now() - Date.parse(c.lastCheckInAt)) / 36e5;
    return ageH >= 7 * 24;
  });

  const okrSummary = okrs.map((o) => ({
    id: o.id,
    objective: o.objective,
    progress: o.progress,
    confidence: o.confidence,
    status: o.status,
    owner: o.owner,
  }));

  const moved = okrs.filter((o) => o.progress > 0 && o.status === 'on_track');
  const slipping = [
    ...okrs.filter((o) => o.status === 'at_risk' || o.status === 'off_track'),
    ...enrichedCycles.filter(
      (c) => c.trafficLight === 'at_risk' || c.trafficLight === 'off_track' || c.stalled
    ),
  ];

  const lines = [
    `Дайджест ${new Date().toISOString().slice(0, 10)}`,
    `Активных циклов: ${board.counts.active} | review: ${board.counts.review} | stall: ${board.counts.stalled}`,
    `OKR on_track: ${okrs.filter((o) => o.status === 'on_track').length}, at_risk: ${okrs.filter((o) => o.status === 'at_risk').length}, off_track: ${okrs.filter((o) => o.status === 'off_track').length}`,
    `Ждут weekly check-in: ${dueCheckIn.length}`,
  ];

  return {
    generatedAt: new Date().toISOString(),
    therapy: false,
    lines,
    boardCounts: board.counts,
    okrs: okrSummary,
    moved: moved.map((o) => ({ id: o.id, objective: o.objective, progress: o.progress })),
    slipping: slipping.slice(0, 20).map((x) => ({
      id: x.id,
      title: x.objective || x.wfo?.outcome || x.staff,
      status: x.status || x.trafficLight,
      reason: x.blocker || (x.stalled ? 'stall' : x.overdue ? 'overdue' : null),
    })),
    dueCheckIn: dueCheckIn.map((c) => ({
      id: c.id,
      staff: c.staff,
      outcome: c.wfo?.outcome,
      lastCheckInAt: c.lastCheckInAt || null,
    })),
    standupLines: board.standupLines,
    nextActions: [
      ...dueCheckIn.slice(0, 3).map((c) => `Check-in: ${c.staff || c.id}`),
      ...board.focusNow.slice(0, 3).map((f) => f.nextAction).filter(Boolean),
    ].slice(0, 8),
  };
}

function buildRetro(cycle) {
  if (!cycle) {
    const err = new Error('cycle not found');
    err.status = 404;
    throw err;
  }
  const history = cycle.history || [];
  const tests = history.filter((h) => h.type === 'test');
  const operates = history.filter((h) => h.type === 'operate');
  const checkins = history.filter((h) => h.type === 'checkin');
  const passed = tests.filter((t) => t.passed).length;
  const failed = tests.filter((t) => t.passed === false).length;

  const learnings = [];
  if (failed > passed) {
    learnings.push('Тесты чаще проваливались — усилить Operate и сузить firstTest');
  }
  if (operates.length === 0 && failed > 0) {
    learnings.push('Были провалы без зафиксированных коррекций — ввести обязательный operate');
  }
  if ((cycle.confidence || 10) <= 5) {
    learnings.push('Низкая confidence — пересмотреть ресурсы или критерий успеха');
  }
  if (learnings.length === 0) {
    learnings.push('Ритм рабочий: сохранить ежедневный/еженедельный тест');
  }

  return {
    therapy: false,
    cycleId: cycle.id,
    outcome: cycle.wfo?.outcome,
    status: cycle.status,
    stats: {
      iterations: cycle.iteration,
      tests: tests.length,
      passed,
      failed,
      operates: operates.length,
      checkins: checkins.length,
    },
    whatWorked: operates.slice(-3).map((o) => o.action).filter(Boolean),
    whatBlocked: [...new Set([cycle.blocker, ...tests.filter((t) => !t.passed).map((t) => t.note)].filter(Boolean))],
    learnings,
    nextPeriod: {
      keep: cycle.wfo?.successMetric,
      improve: learnings[0],
      firstTest: cycle.wfo?.firstTest,
    },
  };
}

module.exports = {
  buildCheckInPayload,
  applyCheckInToCycle,
  buildDigest,
  buildRetro,
  clampConfidence,
};
