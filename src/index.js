// src/index.js
// Авто скрин для perplexity + операционный NLP для коллектива (под ключ)
// Express: Playwright screenshots, optional Perplexity, WFO/TOTE NLP board.

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const express = require('express');
const { chromium } = require('playwright');
const { createStore, createNlpRouter, createOkrStore } = require('./nlp');

const {
  PERPLEXITY_API_KEY,
  PERPLEXITY_URL = 'https://api.perplexity.ai/chat/completions',
  PERPLEXITY_MODEL = 'sonar',
  MIN_CONFIDENCE = '0.78',
  PLAYWRIGHT_PROFILE_DIR = './pw-profile',
  ARTIFACT_DIR = './artifacts',
  PORT = '8787',
  NLP_STAFF_CYCLE = '1',
} = process.env;

const nlpEnabled = !['0', 'false', 'off', 'no'].includes(
  String(NLP_STAFF_CYCLE).toLowerCase()
);

function hasPerplexityKey(value) {
  if (!value) return false;
  const v = String(value).trim().toLowerCase();
  return (
    v.length > 0 && !['your_key_here', 'changeme', 'xxx', 'todo'].includes(v)
  );
}

function assertHttpUrl(raw) {
  let parsed;
  try {
    parsed = new URL(String(raw || ''));
  } catch {
    const err = new Error('url must be a valid absolute URL');
    err.status = 400;
    throw err;
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    const err = new Error('url must start with http:// or https://');
    err.status = 400;
    throw err;
  }
  return parsed.toString();
}

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
fs.mkdirSync(PLAYWRIGHT_PROFILE_DIR, { recursive: true });

const app = express();
app.use(express.json({ limit: '1mb' }));

const nlpStore = createStore(ARTIFACT_DIR);
const okrStore = createOkrStore(ARTIFACT_DIR);
const perplexityReady = hasPerplexityKey(PERPLEXITY_API_KEY);

app.get('/', (_req, res) => {
  res.json({
    service: 'auto-screen-perplexity',
    mode: {
      screenshots: true,
      perplexity: perplexityReady,
      nlp: nlpEnabled,
      nlpTherapy: false,
    },
    links: {
      health: '/health',
      capture: 'POST /capture',
      nlpMeta: '/nlp/meta',
      nlpBoard: '/nlp/board',
      nlpDigest: '/nlp/digest',
      nlpMorning: 'POST /nlp/morning',
      nlpCheckin: 'POST /nlp/checkin',
      nlpModels: '/nlp/models',
      nlpModelPack: 'POST /nlp/models/pack',
      nlpOkr: 'POST /nlp/okr',
    },
  });
});

app.get('/health', (_req, res) => {
  const counts = nlpEnabled ? nlpStore.counts() : null;
  const okrs = nlpEnabled ? okrStore.list({ limit: 1000 }) : [];
  res.json({
    status: 'ok',
    model: PERPLEXITY_MODEL,
    perplexity: perplexityReady,
    nlp: {
      enabled: nlpEnabled,
      mode: 'operational',
      therapy: false,
      cycles: counts,
      okrs: {
        total: okrs.length,
        on_track: okrs.filter((o) => o.status === 'on_track').length,
        at_risk: okrs.filter((o) => o.status === 'at_risk').length,
        off_track: okrs.filter((o) => o.status === 'off_track').length,
      },
    },
  });
});

async function captureScreenshot(url) {
  const context = await chromium.launchPersistentContext(PLAYWRIGHT_PROFILE_DIR, {
    headless: true,
  });
  try {
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
    const fileName = `shot-${Date.now()}.png`;
    const filePath = path.join(ARTIFACT_DIR, fileName);
    await page.screenshot({ path: filePath, fullPage: true });
    return filePath;
  } finally {
    await context.close();
  }
}

async function askPerplexity(prompt) {
  const resp = await fetch(PERPLEXITY_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${PERPLEXITY_API_KEY}`,
    },
    body: JSON.stringify({
      model: PERPLEXITY_MODEL,
      messages: [{ role: 'user', content: prompt }],
    }),
  });
  if (!resp.ok) {
    throw new Error(`Perplexity API error: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

// POST /capture { "url": "https://...", "prompt": "optional" }
app.post('/capture', async (req, res) => {
  try {
    const { prompt } = req.body || {};
    if (!req.body?.url) {
      return res.status(400).json({ error: 'url is required' });
    }
    const url = assertHttpUrl(req.body.url);
    const screenshotPath = await captureScreenshot(url);
    let analysis = null;
    if (prompt && perplexityReady) {
      analysis = await askPerplexity(prompt);
    }
    res.json({
      screenshot: screenshotPath,
      minConfidence: Number(MIN_CONFIDENCE),
      analysis,
      analysisSkipped: Boolean(prompt) && !perplexityReady,
    });
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

app.use(
  '/nlp',
  createNlpRouter({
    store: nlpStore,
    okrStore,
    askPerplexity,
    enabled: nlpEnabled,
    hasApiKey: perplexityReady,
  })
);

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(err.status || 500).json({ error: err.message || 'internal error' });
});

app.listen(Number(PORT), () => {
  console.log(`auto-screen-perplexity listening on port ${PORT}`);
  console.log(`operational NLP: ${nlpEnabled ? 'ON' : 'OFF'} (NLP_STAFF_CYCLE)`);
  console.log(`perplexity: ${perplexityReady ? 'READY' : 'OFF'}`);
});
