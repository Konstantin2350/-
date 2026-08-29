const crypto = require('crypto');
const net = require('net');

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

class WazzupApiError extends Error {
  constructor(message, statusCode, responseBody) {
    super(message);
    this.name = 'WazzupApiError';
    this.statusCode = statusCode;
    this.responseBody = responseBody;
  }
}

function normalizeWhatsAppChatId(value) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new TypeError('phone is required');
  }

  const trimmed = value.trim();
  if (!/^\+?[\d\s()-]+$/.test(trimmed)) {
    throw new TypeError('phone must contain only digits and common separators');
  }

  const chatId = trimmed.replace(/\D/g, '');
  if (chatId.length < 8 || chatId.length > 15) {
    throw new TypeError('phone must contain 8 to 15 digits including country code');
  }
  return chatId;
}

function validateChannelId(value) {
  if (typeof value !== 'string' || !UUID_V4_PATTERN.test(value)) {
    throw new TypeError('WAZZUP_CHANNEL_ID must be a UUID v4');
  }
  return value;
}

function isPrivateIp(hostname) {
  const version = net.isIP(hostname);
  if (version === 4) {
    const octets = hostname.split('.').map(Number);
    return (
      octets[0] === 10 ||
      octets[0] === 127 ||
      (octets[0] === 169 && octets[1] === 254) ||
      (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
      (octets[0] === 192 && octets[1] === 168)
    );
  }
  if (version === 6) {
    const normalized = hostname.toLowerCase();
    return (
      normalized === '::1' ||
      normalized.startsWith('fc') ||
      normalized.startsWith('fd') ||
      normalized.startsWith('fe80:')
    );
  }
  return false;
}

function validatePublicFileUrl(value) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new TypeError('contentUri is required');
  }
  if (value.length > 2048) {
    throw new TypeError('contentUri is too long');
  }

  let url;
  try {
    url = new URL(value);
  } catch {
    throw new TypeError('contentUri must be a valid URL');
  }

  if (url.protocol !== 'https:') {
    throw new TypeError('contentUri must use HTTPS');
  }
  if (url.username || url.password) {
    throw new TypeError('contentUri must not include credentials');
  }

  const hostname = url.hostname.toLowerCase();
  if (
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    hostname.endsWith('.local') ||
    isPrivateIp(hostname)
  ) {
    throw new TypeError('contentUri must point to a public host');
  }

  return url.toString();
}

function buildFileMessage({ channelId, phone, contentUri, crmMessageId }) {
  if (
    crmMessageId !== undefined &&
    (typeof crmMessageId !== 'string' ||
      crmMessageId.length < 1 ||
      crmMessageId.length > 128)
  ) {
    throw new TypeError('crmMessageId must be a non-empty string up to 128 characters');
  }

  return {
    channelId: validateChannelId(channelId),
    chatType: 'whatsapp',
    chatId: normalizeWhatsAppChatId(phone),
    contentUri: validatePublicFileUrl(contentUri),
    crmMessageId: crmMessageId || crypto.randomUUID(),
    clearUnanswered: false,
  };
}

function isBearerAuthorized(header, expectedKey) {
  if (!expectedKey || typeof header !== 'string' || !header.startsWith('Bearer ')) {
    return false;
  }

  const suppliedKey = header.slice('Bearer '.length);
  const supplied = Buffer.from(suppliedKey);
  const expected = Buffer.from(expectedKey);
  return supplied.length === expected.length && crypto.timingSafeEqual(supplied, expected);
}

async function readResponseBody(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text.slice(0, 500) };
  }
}

async function sendFileMessage({
  apiKey,
  apiBaseUrl = 'https://api.wazzup24.com',
  message,
  timeoutMs = 30000,
  fetchImpl = fetch,
}) {
  if (!apiKey) {
    throw new TypeError('WAZZUP_API_KEY is not configured');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${apiBaseUrl.replace(/\/+$/, '')}/v3/message`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(message),
      signal: controller.signal,
    });
    const body = await readResponseBody(response);

    if (!response.ok) {
      throw new WazzupApiError(
        `Wazzup API returned HTTP ${response.status}`,
        response.status,
        body
      );
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new WazzupApiError('Wazzup API request timed out', 504);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

module.exports = {
  WazzupApiError,
  buildFileMessage,
  isBearerAuthorized,
  normalizeWhatsAppChatId,
  sendFileMessage,
  validatePublicFileUrl,
};
