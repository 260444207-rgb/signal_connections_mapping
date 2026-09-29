import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { Registry } from '../src/registry.mjs';
import { Store } from '../src/store.mjs';
import { Coordinator } from '../src/coordinator.mjs';
import { requeuePersistedJob } from '../src/recovery.mjs';
import { executeJob } from '../src/worker.mjs';

const identity = { agentId: 'main', sessionKey: 'agent:main:recovery-test', sessionId: 'same-session' };
const run = { ...identity, runId: 'source-run' };
const input = { workflow_id: 'report', stage_id: 'research', status: 'completed', next_stage: 'draft' };
const summary = {
  objective: { primary: 'Write report', success_criteria: ['Report saved'] },
  state: { facts: ['Research complete'], decisions: [], constraints: [], assumptions: [], open_questions: [], blockers: [] },
  artifacts: [{ type: 'file', path: '/workspace/research.md', purpose: 'Research notes' }],
  next_stage_context: ['Use the research notes'],
};

// This child claims the real durable job, then exits (or stays alive for the
// liveness rejection case). The test never guesses an unused process id.
async function claimFromChild(directory, jobId, stayAlive) {
  const code = [
    'import { Registry } from ' + JSON.stringify(new URL('../src/registry.mjs', import.meta.url).href) + ';',
    'const registry = new Registry(process.argv[1]);',
    'if (!registry.claim(process.argv[2])) throw Error("CLAIM_FAILED");',
    'registry.close();',
    'console.log("CLAIMED");',
    stayAlive ? 'setInterval(() => {}, 1000);' : '',
  ].join('\n');
  const child = spawn(process.execPath, ['--input-type=module', '-e', code, directory, jobId], {
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '';
  let stderr = '';
  const exited = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  child.stderr.on('data', data => { stderr += data; });
  const claimed = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Claim child timed out: ' + stderr)), 5000);
    child.stdout.on('data', data => {
      stdout += data;
      if (stdout.includes('CLAIMED')) { clearTimeout(timer); resolve(); }
    });
    exited.then(result => {
      clearTimeout(timer);
      if (!stdout.includes('CLAIMED')) reject(Error('Claim child exited early: ' + JSON.stringify(result) + stderr));
    }, reject);
  });
  try {
    await claimed;
    if (!stayAlive) assert.equal((await exited).code, 0);
  } catch (error) {
    child.kill();
    await exited.catch(() => {});
    throw error;
  }
  return { child, exited };
}

async function fixture(t, options = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'workflow-hook-recovery-'));
  const registry = new Registry(directory);
  const store = new Store(join(directory, 'state.sqlite'));
  let owned;
  t.after(async () => {
    if (owned && owned.child.exitCode === null && owned.child.signalCode === null) {
      owned.child.kill();
      await owned.exited;
    }
    store.close();
    registry.close();
    const absolute = resolve(directory);
    assert.ok(absolute.startsWith(resolve(tmpdir()) + sep) && absolute.includes('workflow-hook-recovery-'));
    await rm(absolute, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  });
  const config = { stateDir: directory, workflows: { report: ['research', 'draft'] }, waitTimeoutMs: 1000 };
  const timestamp = Date.now();
  registry.observe({ ...run, ts: timestamp, stream: 'lifecycle', data: { phase: 'start' } });
  const token = registry.bind(identity, 'original-revision');
  const job = registry.enqueue(token, input);
  registry.observe({ ...run, ts: timestamp + 1, stream: 'lifecycle', data: { phase: 'end' } });
  const sent = [];
  const adapter = {
    isCurrent: async () => true,
    snapshot: async () => ({ messages: [{ role: 'user', content: 'Write report' }], events: [{ type: 'raw', content: 'Full evidence' }], lifecycle_revision: 'original-revision' }),
    summarize: async () => structuredClone(summary),
    requestContinuation: async checkpoint => { sent.push(checkpoint); return 'draft-run'; },
  };
  let saved;
  if (options.persist !== false) {
    const coordinator = new Coordinator(store, adapter, config.workflows, () => {});
    saved = await coordinator.checkpoint(run, input);
    assert.equal(saved.ok, true);
    assert.equal(store.list()[0].status, 'pending');
  }
  owned = await claimFromChild(directory, job.id, options.live === true);
  assert.equal(registry.job(job.id).worker_pid, owned.child.pid);
  assert.equal(registry.job(job.id).status, 'working');
  if (!options.live) {
    assert.equal(owned.child.exitCode, 0, 'the recorded worker really exited');
    assert.throws(() => process.kill(owned.child.pid, 0), error => error.code === 'ESRCH');
  }
  const sdk = { getSessionEntry: () => ({ sessionId: identity.sessionId, lifecycleRevision: 'original-revision' }), isIncognitoSessionKey: () => false };
  return { registry, store, config, job, saved, adapter, sdk, sent, timestamp };
}

test('explicit recovery resumes a persisted pending checkpoint after the recorded worker exits', { timeout: 10000 }, async t => {
  const f = await fixture(t);
  const checkpoint = f.store.checkpoint(f.saved.checkpoint_id);
  const savedArchive = await readFile(checkpoint.handoff.archive_path, 'utf8');
  const savedPrompt = await readFile(checkpoint.handoff.prompt_path, 'utf8');
  f.adapter.snapshot = async () => { throw Error('RECOVERY_MUST_REUSE_CHECKPOINT'); };
  f.adapter.summarize = async () => { throw Error('RECOVERY_MUST_NOT_RESUMMARIZE'); };
  const queued = requeuePersistedJob(f.job.id, f.config);
  assert.deepEqual(queued, { id: f.job.id, status: 'queued', duplicate: true, recovered: true });
  assert.equal(f.registry.job(f.job.id).checkpoint_id, f.saved.checkpoint_id);
  const result = await executeJob(f.job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.ok, true);
  assert.equal(result.duplicate, true);
  assert.equal(result.job_status, 'done');
  assert.equal(f.registry.job(f.job.id).status, 'done');
  assert.equal(f.store.list()[0].status, 'submitted');
  assert.equal(f.sent.length, 1);
  assert.equal(f.sent[0].checkpoint_id, f.saved.checkpoint_id);
  assert.equal(await readFile(checkpoint.handoff.archive_path, 'utf8'), savedArchive);
  assert.equal(await readFile(checkpoint.handoff.prompt_path, 'utf8'), savedPrompt);
  assert.deepEqual(await executeJob(f.job.id, f.config, f.sdk, { adapter: f.adapter }), { skipped: true });
  assert.equal(f.sent.length, 1, 'a recovered job is still claimed only once');
});

test('recovery refuses a recorded worker process that is still alive', { timeout: 10000 }, async t => {
  const f = await fixture(t, { live: true });
  assert.throws(() => requeuePersistedJob(f.job.id, f.config), /RECOVERY_WORKER_STILL_PRESENT/);
  assert.equal(f.registry.job(f.job.id).status, 'working');
  assert.equal(f.store.list()[0].status, 'pending');
  assert.equal(f.sent.length, 0);
});

test('recovery refuses dispatching, held and submitted deliveries without replaying them', { timeout: 20000 }, async t => {
  for (const status of ['dispatching', 'held', 'submitted']) {
    const f = await fixture(t);
    assert.equal(f.store.move(f.saved.checkpoint_id, 'pending', status), true);
    assert.throws(() => requeuePersistedJob(f.job.id, f.config), /RECOVERY_DELIVERY_AMBIGUOUS/, status);
    assert.equal(f.registry.job(f.job.id).status, 'working');
    assert.equal(f.store.list()[0].status, status);
    assert.equal(f.sent.length, 0);
  }
});

test('recovery refuses a stopped worker that has no persisted checkpoint', { timeout: 10000 }, async t => {
  const f = await fixture(t, { persist: false });
  assert.throws(() => requeuePersistedJob(f.job.id, f.config), /RECOVERY_CHECKPOINT_NOT_PERSISTED/);
  assert.equal(f.registry.job(f.job.id).status, 'working');
  assert.equal(f.store.list().length, 0);
  assert.equal(f.sent.length, 0);
});

test('recovery refuses a newer run even when that run has already ended', { timeout: 10000 }, async t => {
  const f = await fixture(t);
  f.registry.observe({ ...identity, runId: 'newer-run', ts: f.timestamp + 20, stream: 'lifecycle', data: { phase: 'end' } });
  assert.throws(() => requeuePersistedJob(f.job.id, f.config), /RECOVERY_NEWER_RUN_EXISTS/);
  assert.equal(f.registry.job(f.job.id).status, 'working');
  assert.equal(f.store.list()[0].status, 'pending');
  assert.equal(f.sent.length, 0);
});
