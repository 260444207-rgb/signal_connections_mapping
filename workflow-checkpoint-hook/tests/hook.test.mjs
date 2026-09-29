import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Registry } from '../src/registry.mjs';
import { executeJob } from '../src/worker.mjs';
import { OpenClawAdapter } from '../src/openclaw-adapter.mjs';
import { handle } from '../handler.js';
const identity = { agentId: 'main', sessionKey: 'agent:main:test', sessionId: 'session' };
const input = { workflow_id: 'report', stage_id: 'research', next_stage: 'draft', status: 'completed' };
const summary = { objective: { primary: 'Write report', success_criteria: [] },
  state: { facts: [], decisions: [], constraints: [], assumptions: [], open_questions: [], blockers: [] },
  artifacts: [{ type: 'file', path: '/work/result.json', purpose: 'research' }], next_stage_context: ['Read result.json'] };
test('snapshot archives every raw event but summarizes only the SDK-selected branch from a private copy', async t => {
  const f = setup(t);
  const events = [{ type: 'session', id: 'session' },
    { type: 'message', id: 'a', message: { role: 'user', content: 'active branch' } },
    { type: 'message', id: 'b', message: { role: 'user', content: 'other branch' } }];
  f.sdk.readSessionTranscriptEvents = async () => events;
  f.sdk.getSessionEntry = () => ({ sessionId: identity.sessionId });
  let copy;
  f.sdk.SessionManager = { open: path => {
    copy = path;
    assert.deepEqual(readFileSync(path, 'utf8').trim().split('\n').map(JSON.parse), events);
    return { getBranch: () => [events[1]] };
  } };
  const snapshot = await f.adapter.snapshot(identity);
  assert.deepEqual(snapshot.events, events);
  assert.deepEqual(snapshot.messages, [events[1].message]);
  assert.equal(snapshot.lifecycle_revision, identity.sessionId);
  assert.equal(existsSync(copy), false);
});

test('reset returning unchanged sessionId is held even if its revision changed', async t => {
  const f = setup(t);
  const call = f.sdk.callGatewayFromCli;
  f.sdk.callGatewayFromCli = (...args) => args[0] === 'sessions.reset'
    ? { ok: true, key: identity.sessionKey, entry: { sessionId: identity.sessionId, lifecycleRevision: 'different' } } : call(...args);
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  assert.equal((await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter })).job_status, 'held');
  assert.equal(f.calls.some(c => c.method === 'agent'), false);
});

test('session changed again after reset is held before sending', async t => {
  const f = setup(t);
  const call = f.sdk.callGatewayFromCli;
  f.sdk.callGatewayFromCli = async (...args) => {
    const result = await call(...args);
    if (args[0] === 'sessions.reset') f.sdk.getSessionEntry = () => ({ sessionId: 'another-manual-reset' });
    return result;
  };
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  assert.equal((await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter })).job_status, 'held');
  assert.equal(f.calls.some(c => c.method === 'agent'), false);
});
function setup(t) {
  const stateDir = mkdtempSync(join(tmpdir(), 'file-hook-test-'));
  const registry = new Registry(stateDir);
  t.after(() => { registry.close(); rmSync(stateDir, { recursive: true, force: true }); });
  const event = (phase, runId = 'source') => registry.observe({ ...identity, runId, stream: 'lifecycle', ts: Date.now(), data: { phase } });
  event('start');
  const token = registry.bind(identity, 'rev1');
  const calls = [];
  let revision = 'rev1';
  let currentId = identity.sessionId;
  const sdk = {
    getSessionEntry: () => ({ sessionId: currentId, lifecycleRevision: revision }),
    SessionManager: { open: () => ({ getBranch: () => [{ type: 'message', message: { role: 'user', content: 'Write report' } }] }) },
    readSessionTranscriptEvents: async () => [{ type: 'message', raw: 'Full record' }],
    callGatewayFromCli: async (method, opts, params) => {
      calls.push({ method, params });
      if (method === 'agent.wait')
        return { status: 'ok' };
      if (method === 'sessions.reset') {
        revision = undefined; currentId = 'next-session';
        return { ok: true, key: identity.sessionKey, entry: { sessionId: currentId, lifecycleRevision: revision } };
      }
      if (method === 'agent')
        return { runId: 'next' };
      throw Error('UNEXPECTED_RPC');
    }
  };
  const config = { stateDir, workflows: { report: ['research', 'draft'] }, waitTimeoutMs: 1000 };
  const adapter = new OpenClawAdapter(sdk, config);
  adapter.summarize = async () => structuredClone(summary);
  return { registry, event, token, calls, sdk, config, adapter };
}
test('binding rejects missing identity; duplicate request and conflicting transition are checked', t => {
  const f = setup(t);
  const job = f.registry.enqueue(f.token, input);
  assert.equal(f.registry.enqueue(f.token, input).duplicate, true);
  assert.throws(() => f.registry.enqueue(f.token, { ...input, next_stage: 'other' }), /CONFLICTING/);
  const second = f.registry.bind(identity, 'rev1');
  assert.throws(() => f.registry.enqueue(second, { ...input, stage_id: 'draft', next_stage: undefined }), /BOUNDARY_ALREADY/);
  assert.equal(f.registry.claim(job.id), true);
  assert.equal(f.registry.claim(job.id), false);
  const unknown = f.registry.bind({ ...identity, sessionId: 'other' }, 'rev1');
  f.registry.observe({ runId: 'forged', stream: 'lifecycle', data: { phase: 'start' } });
  assert.throws(() => f.registry.enqueue(unknown, input), /BINDING_UNAVAILABLE/);
});
test('worker waits for source end, saves prompt then resets same session and sends exact saved prompt', async (t) => {
  const f = setup(t);
  const job = f.registry.enqueue(f.token, input);
  const pending = executeJob(job.id, f.config, f.sdk, { adapter: f.adapter, pollMs: 5 });
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(f.calls.length, 0);
  f.event('end');
  const result = await pending;
  assert.equal(result.job_status, 'done');
  assert.deepEqual(f.calls.map(c => c.method), ['agent.wait', 'sessions.reset', 'agent']);
  assert.equal(f.calls[1].params.key, identity.sessionKey);
  const cp = JSON.parse(readFileSync(join(f.config.stateDir, 'archives', result.checkpoint_id, 'checkpoint.json'), 'utf8'));
  assert.equal(f.calls[2].params.message, readFileSync(cp.handoff.prompt_path, 'utf8'));
  assert.match(f.calls[2].params.message, /result.json/);
  assert.equal(f.calls[2].params.sessionId, 'next-session');
});
test('source failure holds request without archive or reset', async (t) => {
  const f = setup(t);
  const job = f.registry.enqueue(f.token, input);
  f.event('error');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.code, 'SOURCE_RUN_FAILED_OR_UNKNOWN');
  assert.equal(f.calls.length, 0);
});
test('another active run prevents reset', async (t) => {
  const f = setup(t);
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  f.event('start', 'other');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.code, 'ANOTHER_RUN_ACTIVE');
  assert.equal(f.calls.length, 0);
});
test('terminal checkpoint is done and never resets', async (t) => {
  const f = setup(t);
  f.config.workflows.report = ['research'];
  const job = f.registry.enqueue(f.token, { ...input, next_stage: undefined });
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.job_status, 'done');
  assert.equal(f.calls.length, 0);
});
test('summary failure leaves source context intact', async (t) => {
  const f = setup(t);
  f.adapter.summarize = async () => { throw Error('unavailable'); };
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.ok, false);
  assert.equal(f.registry.job(job.id).status, 'held');
  assert.equal(f.calls.length, 0);
});
test('unconfirmed reset never sends continuation', async (t) => {
  const f = setup(t);
  const original = f.sdk.callGatewayFromCli;
  f.sdk.callGatewayFromCli = async (...args) => args[0] === 'sessions.reset' ? { ok: false } : original(...args);
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.job_status, 'held');
  assert.equal(f.calls.some(c => c.method === 'agent'), false);
});
test('bootstrap injects binding while preserving existing guidance; shutdown unsubscribes', async (t) => {
  const f = setup(t);
  let listener;
  let stopped = false;
  const sdk = { ...f.sdk, onAgentEvent: fn => { listener = fn; return () => { stopped = true; }; } };
  await handle({ type: 'gateway', action: 'startup' }, sdk, f.config);
  try {
    const files = [{ name: 'AGENTS.md', content: 'Existing instructions', missing: false }];
    await handle({ type: 'agent', action: 'bootstrap', sessionKey: identity.sessionKey, context: { ...identity, workspaceDir: f.config.stateDir, bootstrapFiles: files } }, sdk, f.config);
    assert.match(files[0].content, /Existing instructions/);
    assert.match(files[0].content, /END THE CURRENT RUN/);
    listener({ ...identity, runId: 'bound', stream: 'lifecycle', data: { phase: 'start' }, ts: Date.now() });
    const token = files[0].content.match(/binding token is: ([a-f0-9-]+)/)[1];
    assert.equal(f.registry.binding(token).run_id, 'bound');
  }
  finally {
    await handle({ type: 'gateway', action: 'shutdown' }, sdk, f.config);
  }
  assert.equal(stopped, true);
});

test('incognito entry or key is held without issuing reset', async (t) => {
  const f = setup(t);
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const getEntry = f.sdk.getSessionEntry;
  f.sdk.getSessionEntry = () => ({ ...getEntry(), incognito: true });
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.code, 'INCOGNITO_SESSION_UNSUPPORTED');
  assert.equal(f.calls.length, 0);

  let initialized = false;
  const files = [];
  const sdk = { ...f.sdk, getSessionEntry: getEntry, isIncognitoSessionKey: () => true,
    onAgentEvent: () => { initialized = true; return () => {}; } };
  try {
    await handle({ type: 'agent', action: 'bootstrap', sessionKey: identity.sessionKey,
      context: { ...identity, workspaceDir: f.config.stateDir, bootstrapFiles: files } }, sdk, f.config);
    assert.equal(initialized, true);
    assert.equal(files.length, 0);
  } finally { await handle({ type: 'gateway', action: 'shutdown' }, sdk, f.config); }
});

test('incognito change during summarization is rejected before reset', async (t) => {
  const f = setup(t);
  const getEntry = f.sdk.getSessionEntry;
  f.adapter.summarize = async () => {
    f.sdk.getSessionEntry = () => ({ ...getEntry(), incognito: true });
    return structuredClone(summary);
  };
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.job_status, 'held');
  assert.deepEqual(f.calls.map(c => c.method), ['agent.wait']);
});

test('configured Skill is archived and referenced in saved continuation', async (t) => {
  const f = setup(t);
  const skillPath = join(f.config.stateDir, 'source-skill.md');
  writeFileSync(skillPath, '# Workflow\n## draft\nRead research.json and draft the report.');
  f.config.workflowSkills = { report: skillPath };
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.job_status, 'done');
  const cp = JSON.parse(readFileSync(join(f.config.stateDir, 'archives', result.checkpoint_id, 'checkpoint.json'), 'utf8'));
  assert.equal(cp.continuation.skill.source_path, skillPath);
  assert.equal(readFileSync(cp.continuation.skill.snapshot_path, 'utf8'), readFileSync(skillPath, 'utf8'));
  assert.match(f.calls.at(-1).params.message, /source_path/);
  assert.match(cp.continuation.instruction, /Read the Skill snapshot/);
});

test('missing configured Skill preserves context and never resets', async (t) => {
  const f = setup(t);
  f.config.workflowSkills = { report: join(f.config.stateDir, 'missing-skill.md') };
  const job = f.registry.enqueue(f.token, input);
  f.event('end');
  const result = await executeJob(job.id, f.config, f.sdk, { adapter: f.adapter });
  assert.equal(result.code, 'SKILL_ARCHIVE_FAILED');
  assert.equal(f.calls.length, 0);
});
