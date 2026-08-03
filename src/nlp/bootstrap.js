// Под ключ: один запуск — команда, OKR, навыки, утренние циклы, дайджест.
const {
  staffCycleLocal,
  withRuntimeFlags,
  DEFAULT_MAX_ITERATIONS,
} = require('./tote');
const { buildModelPack } = require('./models');
const { suggestOkrsFromGoal } = require('./okr');
const { buildMasterPlaybook } = require('./masterSkills');
const { buildDigest } = require('./checkin');

const DEFAULT_ROSTER = [
  {
    staff: 'Альбина',
    role: 'sales',
    focus: 'сдать пустующие лоты на Северной 100',
    deadline: '2026-08-17',
  },
  {
    staff: 'Олег',
    role: 'closer',
    focus: 'закрыть 5 тёплых лидов',
    deadline: '2026-08-17',
  },
  {
    staff: 'Менеджер',
    role: 'manager',
    focus: 'держать ритм check-in и digest команды',
    deadline: '2026-08-17',
  },
];

function createCycleFromPlan(store, plan, extras = {}) {
  return store.create({
    kind: extras.kind || 'staff',
    phase: 'test',
    iteration: 1,
    status: 'active',
    staff: plan.staff,
    owner: plan.owner,
    deadline: plan.deadline || extras.deadline || null,
    wfo: plan.wfo,
    nextAction: plan.todayTest || plan.wfo.firstTest,
    history: [],
    lastTest: null,
    lastOperate: null,
    blocker: null,
    notesTail: plan.notes
      ? [{ at: new Date().toISOString(), note: String(plan.notes) }]
      : [],
    maxIterations: Number(extras.maxIterations || DEFAULT_MAX_ITERATIONS),
    assessment: `Test: сверить факт с критерием «${plan.wfo.successMetric}».`,
    role: extras.role || null,
    okrId: extras.okrId || null,
  });
}

function runBootstrap({ store, okrStore, body = {} }) {
  const roster = Array.isArray(body.roster) && body.roster.length
    ? body.roster
    : DEFAULT_ROSTER;
  const reuseActive = body.reuseActive !== false;
  const companyGoal =
    body.companyGoal ||
    'Собрать предсказуемый ритм сделок и сдачи помещений';

  const companyPack = buildModelPack({
    goal: companyGoal,
    owner: body.owner || 'Менеджер',
    deadline: body.deadline || '2026-08-17',
    present: body.present || 'Ритм исполнения нестабилен',
    commitment: 9,
  });

  const companyOkr = okrStore.create({
    ...suggestOkrsFromGoal({
      goal: companyGoal,
      owner: body.owner || 'Менеджер',
      deadline: body.deadline || '2026-08-17',
    }),
    team: body.team || 'коллектив',
    period: body.period || 'month',
    parentId: null,
  });

  const employees = [];
  const cycles = [];
  const okrs = [companyOkr];

  for (const item of roster) {
    const staff = String(item.staff || '').trim();
    if (!staff) continue;
    const role = item.role || 'general';
    const focus = item.focus || companyGoal;
    const deadline = item.deadline || body.deadline || null;

    const playbook = buildMasterPlaybook({ role, staff, focus });
    const plan = staffCycleLocal({
      staff,
      focus,
      owner: staff,
      deadline,
      notes: item.notes,
    });

    const personalOkr = okrStore.create({
      ...suggestOkrsFromGoal({ goal: focus, owner: staff, deadline }),
      team: body.team || 'коллектив',
      period: body.period || 'month',
      parentId: companyOkr.id,
    });
    okrs.push(personalOkr);

    let cycle;
    const existing = reuseActive ? store.findActiveByStaff(staff) : null;
    if (existing) {
      cycle = withRuntimeFlags(
        store.update(existing.id, {
          wfo: { ...existing.wfo, ...plan.wfo },
          nextAction: plan.todayTest,
          deadline: deadline || existing.deadline,
          owner: staff,
          role,
          okrId: personalOkr.id,
          assessment: `Bootstrap: тест дня — ${plan.todayTest}`,
        })
      );
      cycle.reused = true;
    } else {
      cycle = withRuntimeFlags(
        createCycleFromPlan(store, plan, {
          role,
          okrId: personalOkr.id,
          deadline,
          maxIterations: body.maxIterations,
        })
      );
      cycle.reused = false;
    }

    cycles.push(cycle);
    employees.push({
      staff,
      role,
      focus,
      cycleId: cycle.id,
      okrId: personalOkr.id,
      skills: playbook.skills.map((s) => s.id),
      systemPrompt: playbook.systemPrompt,
      dailyRitual: playbook.dailyRitual,
      todayTest: plan.todayTest,
      standupLine: plan.standupLine,
    });
  }

  const digest = buildDigest({
    cycles: store.list({ limit: 200 }),
    okrs: okrStore.list({ limit: 200 }),
  });

  return {
    ok: true,
    therapy: false,
    mode: 'turnkey-bootstrap',
    company: {
      goal: companyGoal,
      packSummary: companyPack.summary,
      okrId: companyOkr.id,
      recommendedFlow: companyPack.recommendedFlow,
    },
    employees,
    cycles,
    okrs: okrs.map((o) => ({
      id: o.id,
      objective: o.objective,
      owner: o.owner,
      parentId: o.parentId || null,
      progress: o.progress,
      status: o.status,
      keyResults: o.keyResults.map((kr) => ({
        id: kr.id,
        title: kr.title,
        current: kr.current,
        target: kr.target,
        unit: kr.unit,
        status: kr.status,
      })),
    })),
    digest,
    howToOperate: [
      '1) Каждому ИИ-сотруднику выдать systemPrompt из employees[].systemPrompt',
      '2) Днём: POST /nlp/skills/apply под задачу',
      '3) Вечером: POST /nlp/cycle/:id/advance {eventType:"test", passed:true/false}',
      '4) Раз в неделю: POST /nlp/checkin с confidence + PPP',
      '5) Руководителю: GET /nlp/digest',
    ],
    quickLinks: {
      board: 'GET /nlp/board',
      digest: 'GET /nlp/digest',
      skills: 'GET /nlp/skills',
      smoke: 'npm run nlp:smoke',
    },
  };
}

module.exports = {
  DEFAULT_ROSTER,
  runBootstrap,
};
