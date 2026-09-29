import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { durableWrite } from './archive.mjs';
import { randomUUID } from 'node:crypto';
import { CheckpointError, keyOf } from './types.mjs';
export class Store {
  db;
  archiveRoot;
  constructor(path) {
    this.archiveRoot = join(dirname(path), 'archives');
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;
   CREATE TABLE IF NOT EXISTS workflows (key TEXT PRIMARY KEY, state TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS checkpoints (id TEXT PRIMARY KEY, key TEXT NOT NULL, body TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, status TEXT NOT NULL, run_id TEXT);
   CREATE TABLE IF NOT EXISTS locks (key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL);
   CREATE TABLE IF NOT EXISTS session_transitions (checkpoint_id TEXT PRIMARY KEY, target_key TEXT NOT NULL);`);
  }
  close() { this.db.close(); }
  archivePaths(id) {
    if (!/^cp_[a-f0-9]{64}$/.test(id))
      throw new CheckpointError('INVALID_CHECKPOINT_ID');
    return { archive_path: join(this.archiveRoot, id, 'context.json'), prompt_path: join(this.archiveRoot, id, 'restart-prompt.md') };
  }
  persistArchive(path, text) { return durableWrite(path, text); }
  state(id, workflow) {
    const row = this.db.prepare('SELECT state FROM workflows WHERE key=?').get(keyOf(id, workflow));
    return row ? JSON.parse(String(row.state)) : undefined;
  }
  checkpoint(id) {
    const row = this.db.prepare('SELECT body FROM checkpoints WHERE id=?').get(id);
    return row ? JSON.parse(String(row.body)) : undefined;
  }
  transferSession(cp, next) {
    if (next.agentId !== cp.session.agentId || next.sessionKey !== cp.session.sessionKey || next.sessionId === cp.session.sessionId)
      throw new CheckpointError('INVALID_SESSION_TRANSFER');
    const target = keyOf(next, cp.workflow.id);
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const existing = this.db.prepare('SELECT target_key FROM session_transitions WHERE checkpoint_id=?').get(cp.checkpoint_id);
      if (existing) {
        if (existing.target_key !== target) throw new CheckpointError('SESSION_TRANSFER_CONFLICT');
      } else {
        const state = this.state(cp.session, cp.workflow.id);
        if (state?.checkpoint_id !== cp.checkpoint_id || this.state(next, cp.workflow.id)) throw new CheckpointError('SESSION_TRANSFER_CONFLICT');
        this.db.prepare('INSERT INTO workflows VALUES (?, ?)').run(target, JSON.stringify({ ...state, session: next }));
        this.db.prepare('INSERT INTO session_transitions VALUES (?, ?)').run(cp.checkpoint_id, target);
      }
      this.db.exec('COMMIT');
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  list(identity) {
    const rows = this.db.prepare('SELECT c.body, d.status, d.run_id FROM checkpoints c JOIN deliveries d ON c.id=d.id').all();
    return rows.map(r => ({ checkpoint: JSON.parse(String(r.body)), status: r.status,
      ...(r.run_id ? { runId: String(r.run_id) } : {}) })).filter(r => !identity ||
      (r.checkpoint.session.sessionKey === identity.sessionKey && r.checkpoint.session.sessionId === identity.sessionId && r.checkpoint.session.agentId === identity.agentId));
  }
  async locked(key, action) {
    const owner = randomUUID();
    const result = this.db.prepare(`INSERT INTO locks VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET owner=excluded.owner, expires=excluded.expires WHERE locks.expires < ?`)
      .run(key, owner, Date.now() + 120000, Date.now());
    if (!result.changes)
      throw new CheckpointError('CHECKPOINT_BUSY', true);
    const timer = setInterval(() => {
      try {
        this.db.prepare('UPDATE locks SET expires=? WHERE key=? AND owner=?').run(Date.now() + 120000, key, owner);
      }
      catch { /* The fenced commit below fails if renewal was lost. */ }
    }, 10000);
    timer.unref();
    try {
      return await action(owner);
    }
    finally {
      clearInterval(timer);
      this.db.prepare('DELETE FROM locks WHERE key=? AND owner=?').run(key, owner);
    }
  }
  commit(cp, state, owner) {
    const key = keyOf(cp.session, cp.workflow.id);
    this.db.exec('BEGIN IMMEDIATE');
    try {
      if (!this.db.prepare('SELECT 1 FROM locks WHERE key=? AND owner=? AND expires>?').get(key, owner, Date.now()))
        throw new CheckpointError('CHECKPOINT_LOCK_LOST', true);
      this.db.prepare('INSERT INTO checkpoints VALUES (?, ?, ?)').run(cp.checkpoint_id, key, JSON.stringify(cp));
      this.db.prepare('INSERT INTO workflows VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET state=excluded.state').run(key, JSON.stringify(state));
      this.db.prepare('INSERT INTO deliveries VALUES (?, ?, NULL)').run(cp.checkpoint_id, cp.workflow.status === 'running' ? 'pending' : 'completed');
      this.db.exec('COMMIT');
    }
    catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
  move(id, from, to, runId) {
    return Boolean(this.db.prepare('UPDATE deliveries SET status=?, run_id=COALESCE(?, run_id) WHERE id=? AND status=?').run(to, runId ?? null, id, from).changes);
  }
}
