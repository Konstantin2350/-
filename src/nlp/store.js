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

  function list({ limit = 100, status, staff, kind } = {}) {
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
      .filter((c) => (status ? c.status === status : true))
      .filter((c) =>
        staff
          ? String(c.staff || '').toLowerCase() === String(staff).toLowerCase()
          : true
      )
      .filter((c) => (kind ? c.kind === kind : true))
      .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
    return files.slice(0, limit);
  }

  function findActiveByStaff(staff) {
    if (!staff) return null;
    return (
      list({ status: 'active', staff, limit: 1 })[0] ||
      list({ status: 'review', staff, limit: 1 })[0] ||
      null
    );
  }

  function create(initial) {
    const id = crypto.randomBytes(6).toString('hex');
    const now = new Date().toISOString();
    return save({
      id,
      createdAt: now,
      updatedAt: now,
      notesTail: [],
      blocker: null,
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

  function counts() {
    const all = list({ limit: 10000 });
    return all.reduce(
      (acc, c) => {
        acc.total += 1;
        acc[c.status] = (acc[c.status] || 0) + 1;
        return acc;
      },
      { total: 0, active: 0, done: 0, review: 0, archived: 0 }
    );
  }

  return { create, get, list, update, findActiveByStaff, counts, dir };
}

module.exports = { createStore };
