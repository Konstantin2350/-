// src/index.js
// Авто скрин для perplexity
// Express service that takes a screenshot of a URL via Playwright
// and asks the Perplexity API to describe / analyze the page.

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const express = require('express');
const { chromium } = require('playwright');
const {
  WazzupApiError,
  buildFileMessage,
  isBearerAuthorized,
  sendFileMessage,
} = require('./wazzup');

const {
  PERPLEXITY_API_KEY,
  PERPLEXITY_URL = 'https://api.perplexity.ai/chat/completions',
  PERPLEXITY_MODEL = 'sonar',
  MIN_CONFIDENCE = '0.78',
  PLAYWRIGHT_PROFILE_DIR = './pw-profile',
  ARTIFACT_DIR = './artifacts',
  WAZZUP_API_KEY,
  WAZZUP_API_BASE_URL = 'https://api.wazzup24.com',
  WAZZUP_CHANNEL_ID,
  WAZZUP_SEND_API_KEY,
  PORT = '8787',
} = process.env;

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
fs.mkdirSync(PLAYWRIGHT_PROFILE_DIR, { recursive: true });

const app = express();
app.use(express.json({ limit: '32kb' }));

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', model: PERPLEXITY_MODEL });
});

// POST /whatsapp/send-file
// The file must already be available through a direct public HTTPS URL.
app.post('/whatsapp/send-file', async (req, res) => {
  if (!WAZZUP_API_KEY || !WAZZUP_CHANNEL_ID || !WAZZUP_SEND_API_KEY) {
    return res.status(503).json({ error: 'WhatsApp sending is not configured' });
  }
  if (!isBearerAuthorized(req.get('authorization'), WAZZUP_SEND_API_KEY)) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  try {
    const message = buildFileMessage({
      channelId: WAZZUP_CHANNEL_ID,
      phone: req.body?.phone,
      contentUri: req.body?.contentUri,
      crmMessageId: req.body?.crmMessageId,
    });
    const result = await sendFileMessage({
      apiKey: WAZZUP_API_KEY,
      apiBaseUrl: WAZZUP_API_BASE_URL,
      message,
    });
    return res.status(201).json({
      status: 'sent',
      messageId: result.messageId,
      chatId: result.chatId || message.chatId,
    });
  } catch (err) {
    if (err instanceof TypeError) {
      const configurationError = err.message.startsWith('WAZZUP_');
      return res
        .status(configurationError ? 503 : 400)
        .json({ error: configurationError ? 'WhatsApp configuration is invalid' : err.message });
    }
    if (err instanceof WazzupApiError) {
      console.error('Wazzup send failed:', err.message, err.responseBody || '');
      return res.status(502).json({
        error: 'Wazzup rejected the file message',
        upstreamStatus: err.statusCode,
      });
    }
    console.error('Unexpected WhatsApp send error:', err);
    return res.status(500).json({ error: 'Failed to send WhatsApp file' });
  }
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
    if (prompt && PERPLEXITY_API_KEY) {
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

if (require.main === module) {
  app.listen(Number(PORT), () => {
    console.log(`auto-screen-perplexity listening on port ${PORT}`);
  });
}

module.exports = { app };
