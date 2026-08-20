// Legacy auto-screen-perplexity service.
require('dotenv').config();
const fs = require('fs');
const path = require('path');
const express = require('express');
const { chromium } = require('playwright');

const {
  PERPLEXITY_API_KEY,
  PERPLEXITY_URL = 'https://api.perplexity.ai/chat/completions',
  PERPLEXITY_MODEL = 'sonar',
  MIN_CONFIDENCE = '0.78',
  PLAYWRIGHT_PROFILE_DIR = './pw-profile',
  ARTIFACT_DIR = './artifacts',
  PORT = '8787',
} = process.env;

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
fs.mkdirSync(PLAYWRIGHT_PROFILE_DIR, { recursive: true });

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok', model: PERPLEXITY_MODEL });
});

async function captureScreenshot(url) {
  const context = await chromium.launchPersistentContext(PLAYWRIGHT_PROFILE_DIR, {
    headless: true,
  });
  try {
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
    const filePath = path.join(ARTIFACT_DIR, `shot-${Date.now()}.png`);
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

app.post('/capture', async (req, res) => {
  const { url, prompt } = req.body || {};
  if (!url) return res.status(400).json({ error: 'url is required' });
  try {
    const screenshotPath = await captureScreenshot(url);
    const analysis = prompt && PERPLEXITY_API_KEY
      ? await askPerplexity(prompt)
      : null;
    res.json({
      screenshot: screenshotPath,
      minConfidence: Number(MIN_CONFIDENCE),
      analysis,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(Number(PORT), () => {
  console.log(`auto-screen-perplexity listening on port ${PORT}`);
});
