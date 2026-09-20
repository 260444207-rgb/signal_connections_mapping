import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { Store } from '../src/store.ts';
import { Coordinator, marker } from '../src/coordinator.ts';
import { parseInput, validateSummary } from '../src/types.ts';
import type { Checkpoint, Run, SessionContextAdapter, Summary } from '../src/types.ts';

const summary: Summary = { objective: { primary: 'Build report', success_criteria: ['verified'] },
  state: { facts: ['Research result'], decisions: ['Use source A'], constraints: ['Chinese'], assumptions: [], open_questions: [], blockers: [] },
  artifacts: [{ type: 'file', path: '/workspace/report.json', purpose: 'research results' }], next_stage_context: ['Use report.json'] };
const run: Run = { agentId: 'main', sessionKey: 'agent:main:justdo:test', sessionId: 'generation-1', runId: 'run-A' };
const a = { workflow_id: 'report', stage_id: 'A', status: 'completed', next_stage: 'C' };
function fixture(t: { after: (fn: () => void) => void }) {
  const dir = mkdtempSync(join(tmpdir(), 'workflow-checkpoint-'));
  const path = join(dir, 'state.sqlite');
  let store = new Store(path);
  const sent: Checkpoint[] = [];
  const adapter: SessionContextAdapter = { snapshot: async () => ({ messages: [{ role: 'user', content: 'Build report' }], events: [{ kind: 'raw', payload: 'A full tool history' }], lifecycle_revision: 'before-reset' }), history: async () => [{ role: 'user', content: 'Build report' }],
    summarize: async () => structuredClone(summary), isCurrent: async () => true,
    requestContinuation: async cp => { sent.push(cp); return 'run-C'; } };
  let coordinator = new Coordinator(store, adapter, { report: ['A', 'C', 'D'], other: ['A', 'C'] }, () => {});
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  return { get store() { return store; }, get coordinator() { return coordinator; }, adapter, sent,
    restart() { store.close(); store = new Store(path); coordinator = new Coordinator(store, adapter, { report: ['A', 'C', 'D'] }, () => {}); }, path };
}
test('A -> C -> D preserves session, artifacts, and ends each source run', async t => {
  const f = fixture(t);
  const result = await f.coordinator.checkpoint(run, a);
  assert.equal(result.ok, true); assert.equal(f.sent.length, 0); assert.equal(f.coordinator.blocked(run), true);
  assert.equal((await f.coordinator.checkpoint(run, { ...a, stage_id: 'C', next_stage: 'D' })).code, 'RUN_BOUNDARY_REQUIRED');
  await f.coordinator.end(run, true);
  assert.equal(f.sent.length, 1); assert.deepEqual(f.sent[0].session, { agentId: run.agentId, sessionId: run.sessionId, sessionKey: run.sessionKey });
  const c = { ...run, runId: 'run-C' };
  assert.match(f.coordinator.prepare(c, marker(f.sent[0]))!, /report.json/);
  assert.equal(f.store.list()[0].status, 'started');
  assert.equal((await f.coordinator.checkpoint(c, { ...a, stage_id: 'C', next_stage: 'D' })).ok, true);
  await f.coordinator.end(c, true);
  const d = { ...run, runId: 'run-D' };
  f.coordinator.prepare(d, marker(f.sent[1]));
  assert.equal((await f.coordinator.checkpoint(d, { workflow_id: 'report', stage_id: 'D', status: 'completed' })).ok, true);
  await f.coordinator.end(d, true);
  assert.equal(f.sent.length, 2); assert.equal(f.store.state(run, 'report')?.status, 'completed');
});
test('duplicate checkpoint and agent_end only dispatch once', async t => {
  const f = fixture(t);
  const first = await f.coordinator.checkpoint(run, a);
  const second = await f.coordinator.checkpoint(run, a);
  assert.equal(second.duplicate, true); assert.equal(first.checkpoint_id, second.checkpoint_id);
  await Promise.all([f.coordinator.end(run, true), f.coordinator.end(run, true)]);
  assert.equal(f.sent.length, 1);
});
test('persistence failure never transitions and permits retry', async t => {
  const f = fixture(t);
  const commit = f.store.commit.bind(f.store);
  f.store.commit = () => { throw new Error('disk full'); };
  assert.equal((await f.coordinator.checkpoint(run, a)).code, 'CHECKPOINT_PERSIST_FAILED');
  assert.equal(f.store.state(run, 'report'), undefined); assert.equal(f.coordinator.blocked(run), false);
  await f.coordinator.end(run, true); assert.equal(f.sent.length, 0);
  f.store.commit = commit;
  assert.equal((await f.coordinator.checkpoint(run, a)).ok, true);
});
test('crash after durable checkpoint before continuation recovers', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a); f.restart();
  await f.coordinator.recover(); assert.equal(f.sent.length, 1);
  assert.equal(f.sent[0].transition.to, 'C');
});
test('uncertain accepted delivery is held on restart, not blindly replayed', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a); await f.coordinator.end(run, true); f.restart();
  await f.coordinator.recover(); assert.equal(f.sent.length, 1); assert.equal(f.store.list()[0].status, 'held');
});
test('completed stages cannot be repeated or transition changed', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a);
  assert.equal((await f.coordinator.checkpoint({ ...run, runId: 'new' }, { ...a, next_stage: 'D' })).code, 'CONFLICTING_DUPLICATE');
  assert.equal((await f.coordinator.checkpoint({ ...run, runId: 'new' }, { ...a, status: 'failed', next_stage: undefined })).code, 'INVALID_TRANSITION');
});
test('session generation and workflow keys are isolated', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a);
  const another = { ...run, sessionKey: 'agent:main:justdo:other', runId: 'other' };
  assert.equal(f.coordinator.prepare(another, 'hello'), undefined);
  assert.equal((await f.coordinator.checkpoint(another, a)).duplicate, undefined);
  assert.equal((await f.coordinator.checkpoint({ ...run, sessionId: 'new-generation' }, a)).duplicate, undefined);
  assert.equal((await f.coordinator.checkpoint({ ...run, runId: 'other-workflow' }, { ...a, workflow_id: 'other' })).ok, true);
  assert.equal(f.store.list().length, 4);
});
test('user message does not acknowledge scheduled continuation', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a);
  assert.match(f.coordinator.prepare({ ...run, runId: 'user-turn' }, 'Add a new constraint')!, /Resume Stage C/);
  assert.equal(f.store.list()[0].status, 'pending');
});
test('reset before recovery never starts a replacement session', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a); f.adapter.isCurrent = async () => false;
  await f.coordinator.recover(); assert.equal(f.sent.length, 0); assert.equal(f.store.list()[0].status, 'superseded');
});
test('two store connections cannot concurrently checkpoint one workflow', async t => {
  const f = fixture(t); const other = new Store(f.path);
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  f.adapter.summarize = async () => { await wait; return summary; };
  const first = f.coordinator.checkpoint(run, a);
  const contender = new Coordinator(other, f.adapter, { report: ['A', 'C', 'D'] }, () => {});
  assert.equal((await contender.checkpoint(run, a)).code, 'CHECKPOINT_BUSY');
  release(); assert.equal((await first).ok, true); other.close();
});
test('paused and failed checkpoints do not advance or schedule', async t => {
  const f = fixture(t);
  assert.equal((await f.coordinator.checkpoint(run, { workflow_id: 'report', stage_id: 'A', status: 'paused' })).ok, true);
  await f.coordinator.end(run, true); assert.equal(f.sent.length, 0);
  assert.equal(f.store.state(run, 'report')?.current_stage, 'A');
  assert.deepEqual(f.store.state(run, 'report')?.completed_stages, []);
  assert.equal((await f.coordinator.checkpoint({ ...run, runId: 'resume' }, a)).ok, true);
});
test('invalid model summary and forged session input fail closed', async t => {
  assert.throws(() => parseInput({ ...a, sessionKey: 'forged' }));
  assert.throws(() => validateSummary({ summary: 'prose' }));
  const f = fixture(t); f.adapter.summarize = async () => ({ ...summary, objective: { primary: '', success_criteria: [] } });
  assert.equal((await f.coordinator.checkpoint(run, a)).code, 'INVALID_SUMMARY');
  assert.equal(f.store.list().length, 0);
});
test('aborted source turn holds continuation for user-controlled recovery', async t => {
  const f = fixture(t); await f.coordinator.checkpoint(run, a); await f.coordinator.end(run, false);
  assert.equal(f.sent.length, 0); assert.equal(f.store.list()[0].status, 'held');
});

test('archive failure retains source context and never advances workflow', async t => {
  const f = fixture(t);
  f.store.persistArchive = () => { throw new Error('archive disk unavailable'); };
  assert.equal((await f.coordinator.checkpoint(run, a)).code, 'CHECKPOINT_ARCHIVE_FAILED');
  assert.equal(f.store.state(run, 'report'), undefined);
  await f.coordinator.end(run, true);
  assert.equal(f.sent.length, 0);
});

test('complete raw context is archived before model summarization starts', async t => {
  const f = fixture(t);
  f.adapter.summarize = async () => {
    const archives = join(dirname(f.path), 'archives');
    const folders = readdirSync(archives);
    assert.equal(folders.length, 1);
    assert.match(readFileSync(join(archives, folders[0], 'context.json'), 'utf8'), /A full tool history/);
    return summary;
  };
  const result = await f.coordinator.checkpoint(run, a);
  assert.equal(result.ok, true);
  const state = JSON.parse(readFileSync(join(dirname(f.path), 'archives', String(result.checkpoint_id), 'checkpoint.json'), 'utf8'));
  assert.deepEqual(state.progress.completed_stages, ['A']);
  assert.equal(state.handoff.user_inputs[0].content, 'Build report');
});
