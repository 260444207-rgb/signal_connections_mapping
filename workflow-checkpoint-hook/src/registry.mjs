import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
const scope = identity => JSON.stringify([identity.agentId, identity.sessionKey, identity.sessionId]);
export class Registry {
  constructor(directory) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    this.db = new DatabaseSync(join(directory, 'bindings.sqlite'));
    this.db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;" +
      "CREATE TABLE IF NOT EXISTS bindings(token TEXT PRIMARY KEY, scope TEXT, identity TEXT, revision TEXT, run_id TEXT, created INTEGER);" +
      "CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, scope TEXT, status TEXT, updated INTEGER);" +
      "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, token TEXT, input TEXT, status TEXT, code TEXT, checkpoint_id TEXT);");
    if (!this.db.prepare('PRAGMA table_info(jobs)').all().some(column => column.name === 'worker_pid'))
      this.db.exec('ALTER TABLE jobs ADD COLUMN worker_pid INTEGER');
  }
  close() { this.db.close(); }
  bind(identity, revision) {
    const token = randomUUID();
    const current = this.db.prepare("SELECT id FROM runs WHERE scope=? AND status='running' ORDER BY updated DESC LIMIT 1").get(scope(identity));
    this.db.prepare('INSERT INTO bindings VALUES(?,?,?,?,?,?)').run(token, scope(identity), JSON.stringify(identity), revision, current?.id ?? null, Date.now());
    return token;
  }
  observe(event) {
    if (!event.runId || !event.sessionKey || !event.sessionId || !event.agentId)
      return;
    const key = scope(event);
    const phase = event.stream === 'lifecycle' ? event.data?.phase : undefined;
    const status = phase === 'error' || event.data?.aborted === true ? 'failed' : phase === 'end' ? 'ended' : 'running';
    this.db.prepare("INSERT INTO runs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=" +
      "CASE WHEN excluded.status='running' THEN runs.status ELSE excluded.status END, updated=excluded.updated")
      .run(event.runId, key, status, event.ts || Date.now());
    this.db.prepare('UPDATE bindings SET run_id=? WHERE scope=? AND run_id IS NULL AND created<=?').run(event.runId, key, (event.ts || Date.now()) + 2000);
  }
  binding(token) {
    const row = this.db.prepare('SELECT b.*,r.status AS run_status FROM bindings b LEFT JOIN runs r ON r.id=b.run_id WHERE token=?').get(token);
    if (!row)
      throw Error('UNKNOWN_BINDING_TOKEN');
    return { ...row, identity: JSON.parse(row.identity) };
  }
  enqueue(token, input) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = this.enqueueLocked(token, input);
      this.db.exec('COMMIT');
      return result;
    }
    catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
  hasOtherRunning(identity, runId) {
    return Boolean(this.db.prepare("SELECT 1 FROM runs WHERE scope=? AND id<>? AND status='running'").get(scope(identity), runId));
  }
  enqueueLocked(token, input) {
    const binding = this.binding(token);
    if (!binding.run_id)
      throw Error('RUN_BINDING_UNAVAILABLE');
    if (binding.run_status !== 'running')
      throw Error('SOURCE_RUN_NOT_ACTIVE');
    if (Date.now() - binding.created > 24 * 3600000)
      throw Error('BINDING_EXPIRED');
    const id = 'job_' + createHash('sha256').update(JSON.stringify([scope(binding.identity), input.workflow_id, input.stage_id, input.status, 1])).digest('hex');
    const old = this.db.prepare('SELECT * FROM jobs WHERE id=?').get(id);
    if (old) {
      if (JSON.parse(old.input).next_stage !== input.next_stage)
        throw Error('CONFLICTING_DUPLICATE');
      return { id, duplicate: true, status: old.status };
    }
    if (this.db.prepare("SELECT 1 FROM jobs j JOIN bindings b ON b.token=j.token WHERE b.run_id=?").get(binding.run_id))
      throw Error('RUN_BOUNDARY_ALREADY_REQUESTED');
    this.db.prepare("INSERT INTO jobs(id,token,input,status) VALUES(?,?,?,'queued')").run(id, token, JSON.stringify(input));
    return { id, duplicate: false, status: 'queued' };
  }
  job(id) {
    const row = this.db.prepare('SELECT * FROM jobs WHERE id=?').get(id);
    if (!row)
      throw Error('UNKNOWN_JOB');
    return { ...row, input: JSON.parse(row.input) };
  }
  claim(id) { return Boolean(this.db.prepare("UPDATE jobs SET status='working',worker_pid=? WHERE id=? AND status='queued'").run(process.pid, id).changes); }
  finish(id, status, code = null, checkpointId = null) { this.db.prepare('UPDATE jobs SET status=?,code=?,checkpoint_id=? WHERE id=?').run(status, code, checkpointId, id); }
}
