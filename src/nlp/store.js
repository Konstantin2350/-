// Простое файловое хранилище циклов (без БД).
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function createStore(baseDir) {
  const dir = path.join(baseDir, 'nlp-cycles');
  fs.mkdirSync(dir, { recursive: true });

  function fileFor(id) {
    return path.join(dir, `${id}.json`);
  }

  function save(cycle) {
    fs.writeFileSync(fileFor(cycle.id), JSON.stringify(cycle, null, 2), 'utf8');
    return cycle;
  }

  function get(id) {
    const fp = fileFor(id);
    if (!fs.existsSync(fp)) return null;
    return JSON.parse(fs.readFileSync(fp, 'utf8'));
  }

  function list({ limit = 50 } = {}) {
    const files = fs
      .readdirSync(dir)
      .filter((f) => f.endsWith('.json'))
      .map((f) => {
        try {
          return JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
    return files.slice(0, limit);
  }

  function create(initial) {
    const id = crypto.randomBytes(6).toString('hex');
    const now = new Date().toISOString();
    return save({
      id,
      createdAt: now,
      updatedAt: now,
      ...initial,
    });
  }

  function update(id, patch) {
    const current = get(id);
    if (!current) return null;
    return save({
      ...current,
      ...patch,
      id,
      updatedAt: new Date().toISOString(),
    });
  }

  return { create, get, list, update, dir };
}

module.exports = { createStore };
