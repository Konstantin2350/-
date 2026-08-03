// src/index.js
// Авто скрин для perplexity + операционный NLP для коллектива
// Express service that takes a screenshot of a URL via Playwright
// and asks the Perplexity API to describe / analyze the page.
// Also exposes operational NLP (WFO/TOTE) routes — not therapy.

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const express = require('express');
const { chromium } = require('playwright');
const { createStore, createNlpRouter } = require('./nlp');

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
  return v.length > 0 && !['your_key_here', 'changeme', 'xxx', 'todo'].includes(v);
}

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
fs.mkdirSync(PLAYWRIGHT_PROFILE_DIR, { recursive: true });

const app = express();
app.use(express.json());

const nlpStore = createStore(ARTIFACT_DIR);

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    model: PERPLEXITY_MODEL,
    nlp: {
      enabled: nlpEnabled,
      mode: 'operational',
      therapy: false,
    },
  });
});

// Capture a screenshot of a given URL.
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

// Ask the Perplexity API a question.
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
  const { url, prompt } = req.body || {};
  if (!url) {
    return res.status(400).json({ error: 'url is required' });
  }
  try {
    const screenshotPath = await captureScreenshot(url);
    let analysis = null;
    if (prompt && hasPerplexityKey(PERPLEXITY_API_KEY)) {
      analysis = await askPerplexity(prompt);
    }
    res.json({
      screenshot: screenshotPath,
      minConfidence: Number(MIN_CONFIDENCE),
      analysis,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Операционный NLP для коллектива (не терапия)
app.use(
  '/nlp',
  createNlpRouter({
    store: nlpStore,
    askPerplexity,
    enabled: nlpEnabled,
    hasApiKey: hasPerplexityKey(PERPLEXITY_API_KEY),
  })
);

app.listen(Number(PORT), () => {
  console.log(`auto-screen-perplexity listening on port ${PORT}`);
  console.log(`operational NLP: ${nlpEnabled ? 'ON' : 'OFF'} (NLP_STAFF_CYCLE)`);
});
