// HTTP API операционного NLP для коллектива (не терапия).
const express = require('express');
const { buildWfoLocal, validateWfo } = require('./wfo');
const { advanceLocal, staffCycleLocal } = require('./tote');
const {
  buildWfoPrompt,
  buildTotePrompt,
  buildStaffCyclePrompt,
  SYSTEM_BOUNDARY,
} = require('./prompts');

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

function createNlpRouter({ store, askPerplexity, enabled, hasApiKey }) {
  const router = express.Router();

  router.get('/meta', (_req, res) => {
    res.json({
      name: 'operational-nlp-collective',
      mode: 'operational',
      therapy: false,
      enabled,
      perplexity: Boolean(hasApiKey),
      boundary: SYSTEM_BOUNDARY,
      endpoints: [
        'GET /nlp/meta',
        'POST /nlp/wfo',
        'POST /nlp/staff-cycle',
        'POST /nlp/cycle',
        'GET /nlp/cycle',
        'GET /nlp/cycle/:id',
        'POST /nlp/cycle/:id/advance',
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

  // POST /nlp/wfo — оформить Well-Formed Outcome
  router.post('/wfo', async (req, res) => {
    try {
      const body = req.body || {};
      const useAi = Boolean(body.ai) && hasApiKey;
      let wfo = buildWfoLocal(body);
      let analysis = null;
      let aiParsed = null;

      if (useAi) {
        analysis = await askPerplexity(
          buildWfoPrompt({
            goal: body.goal,
            context: body.context,
            owner: body.owner,
            deadline: body.deadline,
          })
        );
        aiParsed = tryParseJsonContent(extractPerplexityText(analysis));
        if (aiParsed) {
          wfo = {
            ...wfo,
            ...aiParsed,
            evidence: aiParsed.evidence || wfo.evidence,
            resources: aiParsed.resources || wfo.resources,
            ecology: aiParsed.ecology || wfo.ecology,
            owner: body.owner || wfo.owner,
            deadline: body.deadline || wfo.deadline,
            mode: 'operational',
            source: 'perplexity',
          };
        }
      }

      const check = validateWfo(wfo);
      res.json({ wfo, valid: check.ok, missing: check.missing, analysis: useAi ? analysis : null });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  // POST /nlp/staff-cycle — быстрый цикл для сотрудника/роли
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
        }
      }

      // Опционально сразу создать TOTE-цикл
      let cycle = null;
      if (body.startCycle) {
        cycle = store.create({
          kind: 'staff',
          phase: 'test',
          iteration: 1,
          status: 'active',
          staff: plan.staff,
          owner: plan.owner,
          deadline: plan.deadline || null,
          wfo: plan.wfo,
          nextAction: plan.todayTest || plan.wfo.firstTest,
          history: [],
          lastTest: null,
          lastOperate: null,
        });
      }

      res.json({ plan, cycle, analysis: useAi ? analysis : null });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  // POST /nlp/cycle — создать TOTE-цикл из цели/WFO
  router.post('/cycle', async (req, res) => {
    try {
      const body = req.body || {};
      const wfo = body.wfo || buildWfoLocal(body);
      const check = validateWfo(wfo);
      if (!check.ok) {
        return res.status(400).json({ error: 'invalid wfo', missing: check.missing });
      }

      const cycle = store.create({
        kind: body.kind || 'collective',
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
        assessment: `Test: сверить факт с критерием «${wfo.successMetric}».`,
      });

      res.status(201).json({ cycle });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  router.get('/cycle', (_req, res) => {
    res.json({ cycles: store.list({ limit: 50 }) });
  });

  router.get('/cycle/:id', (req, res) => {
    const cycle = store.get(req.params.id);
    if (!cycle) return res.status(404).json({ error: 'cycle not found' });
    return res.json({ cycle });
  });

  // POST /nlp/cycle/:id/advance — шаг TOTE (test|operate|exit)
  router.post('/cycle/:id/advance', async (req, res) => {
    try {
      const cycle = store.get(req.params.id);
      if (!cycle) return res.status(404).json({ error: 'cycle not found' });
      if (cycle.status === 'done') {
        return res.status(409).json({ error: 'cycle already done', cycle });
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
      res.json({ cycle: saved, analysis: useAi ? analysis : null });
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  });

  return router;
}

module.exports = { createNlpRouter };
