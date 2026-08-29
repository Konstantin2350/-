const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');

const {
  WazzupApiError,
  buildFileMessage,
  isBearerAuthorized,
  normalizeWhatsAppChatId,
  sendFileMessage,
  validatePublicFileUrl,
} = require('../src/wazzup');

const CHANNEL_ID = 'e0629e11-0f67-4567-92a9-2237e91ec1b9';

test('normalizes a WhatsApp phone number for Wazzup', () => {
  assert.equal(normalizeWhatsAppChatId('+7 (918) 555-12-34'), '79185551234');
  assert.throws(() => normalizeWhatsAppChatId('not-a-phone'), /phone/);
  assert.throws(() => normalizeWhatsAppChatId('123'), /8 to 15/);
});

test('accepts only public HTTPS file URLs', () => {
  assert.equal(
    validatePublicFileUrl('https://files.example.com/lease.docx'),
    'https://files.example.com/lease.docx'
  );
  assert.throws(() => validatePublicFileUrl('http://files.example.com/a.docx'), /HTTPS/);
  assert.throws(() => validatePublicFileUrl('https://127.0.0.1/a.docx'), /public host/);
  assert.throws(() => validatePublicFileUrl('https://user:pass@example.com/a.docx'), /credentials/);
});

test('builds a Wazzup attachment payload without a text field', () => {
  const message = buildFileMessage({
    channelId: CHANNEL_ID,
    phone: '+7 918 555-12-34',
    contentUri: 'https://files.example.com/lease.docx',
    crmMessageId: 'lease-2026-001',
  });

  assert.deepEqual(message, {
    channelId: CHANNEL_ID,
    chatType: 'whatsapp',
    chatId: '79185551234',
    contentUri: 'https://files.example.com/lease.docx',
    crmMessageId: 'lease-2026-001',
    clearUnanswered: false,
  });
  assert.equal('text' in message, false);
});

test('checks the internal bearer token', () => {
  assert.equal(isBearerAuthorized('Bearer internal-secret', 'internal-secret'), true);
  assert.equal(isBearerAuthorized('Bearer wrong', 'internal-secret'), false);
  assert.equal(isBearerAuthorized(undefined, 'internal-secret'), false);
});

test('sends a file payload to Wazzup with upstream authorization', async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url, options };
    return new Response(
      JSON.stringify({ messageId: 'message-123', chatId: '79185551234' }),
      {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }
    );
  };
  const message = buildFileMessage({
    channelId: CHANNEL_ID,
    phone: '79185551234',
    contentUri: 'https://files.example.com/lease.docx',
    crmMessageId: 'lease-2026-001',
  });

  const result = await sendFileMessage({
    apiKey: 'upstream-secret',
    message,
    fetchImpl,
  });

  assert.equal(request.url, 'https://api.wazzup24.com/v3/message');
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers.Authorization, 'Bearer upstream-secret');
  assert.deepEqual(JSON.parse(request.options.body), message);
  assert.equal(result.messageId, 'message-123');
});

test('turns a rejected Wazzup response into a typed error', async () => {
  const fetchImpl = async () =>
    new Response(JSON.stringify({ error: 'WRONG_TRANSPORT' }), { status: 400 });

  await assert.rejects(
    sendFileMessage({
      apiKey: 'upstream-secret',
      message: {},
      fetchImpl,
    }),
    (error) =>
      error instanceof WazzupApiError &&
      error.statusCode === 400 &&
      error.responseBody.error === 'WRONG_TRANSPORT'
  );
});

test('POST /whatsapp/send-file forwards a validated document to Wazzup', async (t) => {
  let upstreamRequest;
  const upstream = http.createServer((req, res) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => {
      body += chunk;
    });
    req.on('end', () => {
      upstreamRequest = {
        method: req.method,
        url: req.url,
        authorization: req.headers.authorization,
        body: JSON.parse(body),
      };
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ messageId: 'message-456', chatId: '79185551234' }));
    });
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => upstream.close(resolve)));

  process.env.WAZZUP_API_KEY = 'upstream-secret';
  process.env.WAZZUP_API_BASE_URL = `http://127.0.0.1:${upstream.address().port}`;
  process.env.WAZZUP_CHANNEL_ID = CHANNEL_ID;
  process.env.WAZZUP_SEND_API_KEY = 'internal-secret';
  process.env.ARTIFACT_DIR = '/tmp/auto-screen-test-artifacts';
  process.env.PLAYWRIGHT_PROFILE_DIR = '/tmp/auto-screen-test-profile';
  delete require.cache[require.resolve('../src/index')];
  const { app } = require('../src/index');

  const server = app.listen(0, '127.0.0.1');
  await new Promise((resolve) => server.once('listening', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const endpoint = `http://127.0.0.1:${server.address().port}/whatsapp/send-file`;

  const unauthorizedResponse = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      phone: '79185551234',
      contentUri: 'https://files.example.com/lease.docx',
    }),
  });
  assert.equal(unauthorizedResponse.status, 401);

  const invalidUrlResponse = await fetch(endpoint, {
    method: 'POST',
    headers: {
      Authorization: 'Bearer internal-secret',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      phone: '79185551234',
      contentUri: 'http://localhost/lease.docx',
    }),
  });
  assert.equal(invalidUrlResponse.status, 400);

  const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer internal-secret',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        phone: '+7 (918) 555-12-34',
        contentUri: 'https://files.example.com/lease.docx',
        crmMessageId: 'lease-2026-001',
      }),
    });

  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), {
    status: 'sent',
    messageId: 'message-456',
    chatId: '79185551234',
  });
  assert.equal(upstreamRequest.method, 'POST');
  assert.equal(upstreamRequest.url, '/v3/message');
  assert.equal(upstreamRequest.authorization, 'Bearer upstream-secret');
  assert.equal(upstreamRequest.body.chatType, 'whatsapp');
  assert.equal(upstreamRequest.body.contentUri, 'https://files.example.com/lease.docx');
  assert.equal('text' in upstreamRequest.body, false);
});
