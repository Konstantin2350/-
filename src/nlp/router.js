// HTTP API операционного NLP для коллектива (не терапия). Под ключ.
const express = require('express');
const { buildWfoLocal, validateWfo } = require('./wfo');
const {
  advanceLocal,
  appendNote,
  staffCycleLocal,
  buildBoard,
  withRuntimeFlags,
  DEFAULT_MAX_ITERATIONS,
} = require('./tote');
const {
  buildWfoPrompt,
  buildTotePrompt,
  buildStaffCyclePrompt,
  SYSTEM_BOUNDARY,
} = require('./prompts');
const {
  MODEL_CATALOG,
  buildWfoModel,
  buildGoalPathModel,
  buildScoreModel,
  buildEcologyModel,
  buildClarifyModel,
  buildDisneyModel,
  buildChunkingModel,
  buildGrowModel,
  buildModelPack,
} = require('./models');
const { suggestOkrsFromGoal } = require('./okr');
const {
  buildCheckInPayload,
  applyCheckInToCycle,
  buildDigest,
  buildRetro,
} = require('./checkin');

function tryParseJsonContent(text) {
  if (!text || typeof text !== 'string') return null;
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = trimmed.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      return JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
}

function extractPerplexityText(analysis) {
  return (
    analysis?.choices?.[0]?.message?.content ||
    analysis?.choices?.[0]?.text ||
    null
  );
}

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
  });
}

function createNlpRouter({ store, okrStore, askPerplexity, enabled, hasApiKey }) {
  const router = express.Router();

  router.get('/meta', (_req, res) => {
    res.json({
      name: 'operational-nlp-collective',
      mode: 'operational',
      therapy: false,
      enabled,
      perplexity: Boolean(hasApiKey),
      boundary: SYSTEM_BOUNDARY,
      inspiredBy: [
        'Tability (weekly check-in + confidence)',
        'Weekdone (PPP + OKR)',
        'GROW coaching',
        'Range (async standup cadence)',
      ],
      models: MODEL_CATALOG.map((m) => m.id),
      endpoints: [
        'GET /nlp/meta',
        'GET /nlp/board',
        'GET /nlp/digest',
        'POST /nlp/morning',
        'POST /nlp/checkin',
        'GET /nlp/models',
        'POST /nlp/models/wfo',
        'POST /nlp/models/goal-path',
        'POST /nlp/models/score',
        'POST /nlp/models/ecology',
        'POST /nlp/models/clarify',
        'POST /nlp/models/disney',
        'POST /nlp/models/chunking',
        'POST /nlp/models/grow',
        'POST /nlp/models/pack',
        'POST /nlp/okr',
        'POST /nlp/okr/suggest',
        'GET /nlp/okr',
        'GET /nlp/okr/:id',
        'POST /nlp/okr/:id/checkin',
        'PATCH /nlp/okr/:id/kr/:krId',
        'POST /nlp/wfo',
        'POST /nlp/staff-cycle',
        'POST /nlp/cycle',
        'GET /nlp/cycle',
        'GET /nlp/cycle/:id',
        'POST /nlp/cycle/:id/advance',
        'POST /nlp/cycle/:id/checkin',
        'POST /nlp/cycle/:id/retro',
        'POST /nlp/cycle/:id/note',
        'POST /nlp/cycle/:id/archive',
        'POST /nlp/cycle/:id/reopen',
      ],
    });
  });

  function guard(_req, res, next) {
    if (!enabled) {
      return res.status(503).json({
        error: 'NLP_STAFF_CYCLE disabled',
        hint: 'Set NLP_STAFF_CYCLE=1 to enable operational NLP routes',
      });
    }
    return next();
  }

  router.use(guard);

  // Каталог и эндпоинты операционных моделей
  router.get('/models', (_req, res) => {
    res.json({
      therapy: false,
      models: MODEL_CATALOG,
      usage:
        'Выберите модель под задачу или вызовите POST /nlp/models/pack для полного пакета',
    });
  });

  function runModel(builder) {
    return (req, res) => {
      try {
        const result = builder(req.body || {});
        res.json(result);
      } catch (err) {
        res.status(err.status || 500).json({ error: err.message });
      }
    };
  }

  router.post('/models/wfo', runModel(buildWfoModel));
  router.post('/models/goal-path', runModel(buildGoalPathModel));
  router.post('/models/score', runModel(buildScoreModel));
  router.post('/models/ecology', runModel(buildEcologyModel));
  router.post('/models/clarify', runModel(buildClarifyModel));
  router.post('/models/disney', runModel(buildDisneyModel));
  router.post('/models/chunking', runModel(buildChunkingModel));
  router.post('/models/grow', runModel(buildGrowModel));

  // --- OKR (Tability/Weekdone-style) ---
  router.post('/okr/suggest', (req, res) => {
    try {
      res.json({ draft: suggestOkrsFromGoal(req.body || {}) });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/okr', (req, res) => {
    try {
      if (!okrStore) {
        return res.status(503).json({ error: 'okr store unavailable' });
      }
      const body = req.body || {};
      const draft =
        body.keyResults && body.objective
          ? body
          : { ...suggestOkrsFromGoal(body), ...body, objective: body.objective || body.goal };
      const okr = okrStore.create(draft);
      res.status(201).json({ okr });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.get('/okr', (req, res) => {
    if (!okrStore) return res.status(503).json({ error: 'okr store unavailable' });
    const okrs = okrStore.list({
      limit: Number(req.query.limit || 50),
      status: req.query.status,
      owner: req.query.owner,
    });
    res.json({ okrs });
  });

  router.get('/okr/:id', (req, res) => {
    if (!okrStore) return res.status(503).json({ error: 'okr store unavailable' });
    const okr = okrStore.get(req.params.id);
    if (!okr) return res.status(404).json({ error: 'okr not found' });
    return res.json({ okr });
  });

  router.patch('/okr/:id/kr/:krId', (req, res) => {
    try {
      if (!okrStore) return res.status(503).json({ error: 'okr store unavailable' });
      const okr = okrStore.updateKr(req.params.id, req.params.krId, req.body || {});
      if (!okr) return res.status(404).json({ error: 'okr not found' });
      res.json({ okr });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/okr/:id/checkin', (req, res) => {
    try {
      if (!okrStore) return res.status(503).json({ error: 'okr store unavailable' });
      const payload = buildCheckInPayload(req.body || {});
      const okr = okrStore.addCheckIn(req.params.id, payload);
      if (!okr) return res.status(404).json({ error: 'okr not found' });
      res.json({ okr, checkIn: payload });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  // Weekly digest (как Monday digest в OKR-инструментах)
  router.get('/digest', (_req, res) => {
    const cycles = store.list({ limit: 200 });
    const okrs = okrStore ? okrStore.list({ limit: 200 }) : [];
    res.json({ digest: buildDigest({ cycles, okrs }) });
  });

  // Универсальный check-in: по cycleId или staff (активный цикл)
  router.post('/checkin', (req, res) => {
    try {
      const body = req.body || {};
      const payload = buildCheckInPayload(body);
      let cycle = null;
      if (body.cycleId) cycle = store.get(body.cycleId);
      else if (body.staff) cycle = store.findActiveByStaff(body.staff);
      if (!cycle) {
        return res.status(404).json({
          error: 'active cycle not found',
          hint: 'Передайте cycleId или staff с активным циклом',
        });
      }
      const next = applyCheckInToCycle(cycle, payload);
      const saved = store.update(cycle.id, next);

      let okr = null;
      if (body.okrId && okrStore) {
        okr = okrStore.addCheckIn(body.okrId, payload);
      }

      res.json({
        cycle: withRuntimeFlags(saved),
        okr,
        checkIn: payload,
      });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  // Пакет моделей; опционально сразу стартует TOTE-цикл
  router.post('/models/pack', (req, res) => {
    try {
      const body = req.body || {};
      const pack = buildModelPack(body);
      let cycle = null;
      if (body.startCycle) {
        const plan = {
          staff: body.staff || body.owner || pack.summary.owner || 'команда',
          owner: pack.summary.owner || body.owner || body.staff || 'команда',
          deadline: body.deadline || null,
          notes: body.present || body.symptom || null,
          wfo: pack.models.wfo.wfo,
          todayTest: pack.summary.firstTest,
        };
        const reuseActive = body.reuseActive !== false;
        const existing =
          reuseActive && body.staff
            ? store.findActiveByStaff(body.staff)
            : null;
        if (existing) {
          cycle = withRuntimeFlags(
            store.update(existing.id, {
              wfo: { ...existing.wfo, ...plan.wfo },
              nextAction: plan.todayTest,
              deadline: plan.deadline || existing.deadline,
              modelsUsed: ['pack', 'wfo', 'goal-path', 'score'],
            })
          );
        } else {
          cycle = withRuntimeFlags(
            createCycleFromPlan(store, plan, {
              kind: body.staff ? 'staff' : 'collective',
              maxIterations: body.maxIterations,
              deadline: body.deadline,
            })
          );
          store.update(cycle.id, {
            modelsUsed: ['pack', 'wfo', 'goal-path', 'score'],
          });
          cycle = withRuntimeFlags(store.get(cycle.id));
        }
      }
      res.status(body.startCycle ? 201 : 200).json({ ...pack, cycle });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  // Доска коллектива для стендапа
  router.get('/board', (req, res) => {
    const stallHours = Number(req.query.stallHours || 24);
    const cycles = store.list({ limit: 200 });
    res.json({ board: buildBoard(cycles, { stallHours }) });
  });

  // Утренний запуск: roster [{staff, focus, deadline?}]
  router.post('/morning', async (req, res) => {
    try {
      const body = req.body || {};
      const roster = Array.isArray(body.roster) ? body.roster : null;
      if (!roster || roster.length === 0) {
        return res.status(400).json({
          error: 'roster is required',
          example: {
            roster: [{ staff: 'Альбина', focus: 'сдать лоты Северная 100' }],
            reuseActive: true,
          },
        });
      }

      const reuseActive = body.reuseActive !== false;
      const created = [];
      const reused = [];

      for (const item of roster) {
        const plan = staffCycleLocal(item);
        const existing = reuseActive ? store.findActiveByStaff(plan.staff) : null;
        if (existing) {
          const patched = store.update(existing.id, {
            nextAction: plan.todayTest,
            wfo: {
              ...existing.wfo,
              ...plan.wfo,
            },
            deadline: item.deadline || existing.deadline || null,
            assessment: `Утро: обновить тест — ${plan.todayTest}`,
          });
          reused.push(withRuntimeFlags(patched));
        } else {
          created.push(
            withRuntimeFlags(
              createCycleFromPlan(store, plan, {
                maxIterations: body.maxIterations,
                deadline: item.deadline,
              })
            )
          );
        }
      }

      const board = buildBoard(store.list({ limit: 200 }));
      res.status(201).json({
        created: created.length,
        reused: reused.length,
        cycles: [...created, ...reused],
        board,
      });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/wfo', async (req, res) => {
    try {
      const body = req.body || {};
      const useAi = Boolean(body.ai) && hasApiKey;
      let model = buildWfoModel(body);
      let analysis = null;

      if (useAi) {
        analysis = await askPerplexity(
          buildWfoPrompt({
            goal: body.goal,
            context: body.context,
            owner: body.owner,
            deadline: body.deadline,
          })
        );
        const aiParsed = tryParseJsonContent(extractPerplexityText(analysis));
        if (aiParsed) {
          model = buildWfoModel({
            ...body,
            goal: aiParsed.outcome || body.goal,
            evidence: aiParsed.evidence || body.evidence,
            resources: aiParsed.resources || body.resources,
            ecology: aiParsed.ecology || body.ecology,
            firstTest: aiParsed.firstTest || body.firstTest,
            successMetric: aiParsed.successMetric || body.successMetric,
          });
          model.wfo.source = 'perplexity';
        }
      }

      const check = validateWfo(model.wfo);
      res.json({
        ...model,
        valid: check.ok,
        missing: check.missing,
        analysis: useAi ? analysis : null,
      });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/staff-cycle', async (req, res) => {
    try {
      const body = req.body || {};
      const useAi = Boolean(body.ai) && hasApiKey;
      let plan = staffCycleLocal(body);
      let analysis = null;

      if (useAi) {
        analysis = await askPerplexity(
          buildStaffCyclePrompt({
            staff: body.staff,
            focus: body.focus,
            notes: body.notes,
          })
        );
        const parsed = tryParseJsonContent(extractPerplexityText(analysis));
        if (parsed) {
          plan = {
            ...plan,
            ...parsed,
            mode: 'operational',
            staff: body.staff,
            source: 'perplexity',
          };
          if (parsed.wfo) {
            plan.wfo = { ...plan.wfo, ...parsed.wfo, mode: 'operational' };
          }
        }
      }

      let cycle = null;
      const reuseActive = body.reuseActive !== false;
      if (body.startCycle) {
        const existing =
          reuseActive ? store.findActiveByStaff(plan.staff) : null;
        if (existing) {
          cycle = withRuntimeFlags(
            store.update(existing.id, {
              wfo: { ...existing.wfo, ...plan.wfo },
              nextAction: plan.todayTest || plan.wfo.firstTest,
              deadline: plan.deadline || existing.deadline || null,
              owner: plan.owner || existing.owner,
            })
          );
          cycle.reused = true;
        } else {
          cycle = withRuntimeFlags(
            createCycleFromPlan(store, plan, {
              maxIterations: body.maxIterations,
            })
          );
        }
      }

      res.json({ plan, cycle, analysis: useAi ? analysis : null });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/cycle', async (req, res) => {
    try {
      const body = req.body || {};
      const wfo = body.wfo || buildWfoLocal(body);
      const check = validateWfo(wfo);
      if (!check.ok) {
        return res.status(400).json({ error: 'invalid wfo', missing: check.missing });
      }

      if (body.reuseActive && body.staff) {
        const existing = store.findActiveByStaff(body.staff);
        if (existing) {
          const updated = store.update(existing.id, {
            wfo: { ...existing.wfo, ...wfo, mode: 'operational' },
            nextAction: wfo.firstTest,
            owner: wfo.owner || body.owner || existing.owner,
            deadline: wfo.deadline || body.deadline || existing.deadline,
          });
          return res.json({ cycle: withRuntimeFlags(updated), reused: true });
        }
      }

      const cycle = store.create({
        kind: body.kind || (body.staff ? 'staff' : 'collective'),
        phase: 'test',
        iteration: 1,
        status: 'active',
        staff: body.staff || null,
        owner: wfo.owner || body.owner || null,
        deadline: wfo.deadline || body.deadline || null,
        wfo: { ...wfo, mode: 'operational' },
        nextAction: wfo.firstTest,
        history: [],
        lastTest: null,
        lastOperate: null,
        blocker: null,
        notesTail: [],
        maxIterations: Number(body.maxIterations || DEFAULT_MAX_ITERATIONS),
        assessment: `Test: сверить факт с критерием «${wfo.successMetric}».`,
      });

      res.status(201).json({ cycle: withRuntimeFlags(cycle), reused: false });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.get('/cycle', (req, res) => {
    const cycles = store
      .list({
        limit: Number(req.query.limit || 50),
        status: req.query.status,
        staff: req.query.staff,
        kind: req.query.kind,
      })
      .map((c) => withRuntimeFlags(c));
    res.json({ cycles, counts: store.counts() });
  });

  router.get('/cycle/:id', (req, res) => {
    const cycle = store.get(req.params.id);
    if (!cycle) return res.status(404).json({ error: 'cycle not found' });
    return res.json({ cycle: withRuntimeFlags(cycle) });
  });

  router.post('/cycle/:id/advance', async (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      if (cycle.status === 'done') {
        return res.status(409).json({ error: 'cycle already done', cycle });
      }
      if (cycle.status === 'archived') {
        return res.status(409).json({ error: 'cycle archived', cycle });
      }

      const body = req.body || {};
      let next = advanceLocal(cycle, {
        eventType: body.eventType || body.phase,
        note: body.note,
        passed: body.passed,
        action: body.action,
      });

      let analysis = null;
      const useAi = Boolean(body.ai) && hasApiKey;
      if (useAi) {
        analysis = await askPerplexity(
          buildTotePrompt({
            cycle: next,
            event: {
              eventType: body.eventType || body.phase,
              note: body.note,
              passed: body.passed,
              action: body.action,
            },
          })
        );
        const parsed = tryParseJsonContent(extractPerplexityText(analysis));
        if (parsed) {
          next = {
            ...next,
            assessment: parsed.assessment || next.assessment,
            nextAction: parsed.done ? null : parsed.nextAction || next.nextAction,
            aiHint: {
              phase: parsed.phase,
              gap: parsed.gap,
              ownerHint: parsed.ownerHint,
              done: parsed.done,
            },
          };
          if (parsed.done) {
            next.phase = 'exit';
            next.status = 'done';
          }
        }
      }

      const saved = store.update(cycle.id, next);
      res.json({
        cycle: withRuntimeFlags(saved),
        analysis: useAi ? analysis : null,
      });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/cycle/:id/checkin', (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      const payload = buildCheckInPayload({ ...req.body, staff: req.body?.staff || cycle.staff });
      const next = applyCheckInToCycle(cycle, payload);
      const saved = store.update(cycle.id, next);
      res.json({ cycle: withRuntimeFlags(saved), checkIn: payload });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/cycle/:id/retro', (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      res.json({ retro: buildRetro(withRuntimeFlags(cycle)) });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/cycle/:id/note', (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      const next = appendNote(cycle, req.body?.note);
      const saved = store.update(cycle.id, next);
      res.json({ cycle: withRuntimeFlags(saved) });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.post('/cycle/:id/archive', (req, res) => {
    const cycle = store.get(req.params.id);
    if (!cycle) return res.status(404).json({ error: 'cycle not found' });
    const saved = store.update(cycle.id, {
      status: 'archived',
      phase: cycle.phase === 'exit' ? 'exit' : cycle.phase,
      nextAction: null,
      assessment: 'Цикл в архиве (не активен).',
      history: [
        ...(cycle.history || []),
        {
          type: 'archive',
          at: new Date().toISOString(),
          note: req.body?.note || 'archive',
        },
      ],
    });
    res.json({ cycle: withRuntimeFlags(saved) });
  });

  router.post('/cycle/:id/reopen', (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      const next = advanceLocal(cycle, {
        eventType: 'reopen',
        note: req.body?.note,
      });
      const saved = store.update(cycle.id, next);
      res.json({ cycle: withRuntimeFlags(saved) });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  return router;
}

module.exports = { createNlpRouter };
