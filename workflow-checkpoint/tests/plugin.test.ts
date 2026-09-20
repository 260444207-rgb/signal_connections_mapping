import { test } from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { OpenClawPluginApi } from 'openclaw/plugin-sdk/core';

test('registered plugin uses verified SDK contracts and stops tools before same-session RPC', async t => {
  const sends: unknown[][] = [];
  const identity = { agentId: 'main', sessionKey: 'agent:main:justdo:test', sessionId: 'same-generation', runId: 'source' };
  let revision = 'before-reset';
  let mode = 'normal';
  const fake = {
    getSessionEntry: () => ({ sessionId: identity.sessionId, lifecycleRevision: revision }),
    readSessionTranscriptEvents: async () => [{ type: 'toolResult', content: 'FULL_A_CONTEXT_SENTINEL' }],
    readVisibleSessionTranscriptMessageEntries: async () => [{ entryId: '1', message: { role: 'user', content: mode === 'new-user-input' ? 'Stop, change the task' : 'Research and write' } }],
    callGatewayFromCli: async (...args: unknown[]) => {
      sends.push(args);
      if (args[0] === 'agent.wait') return { status: 'ok' };
      if (args[0] === 'sessions.reset' && mode === 'reset-fails') throw new Error('reset denied');
      if (args[0] === 'sessions.reset') { revision = 'after-reset'; return { ok: true, key: identity.sessionKey, entry: { sessionId: identity.sessionId, lifecycleRevision: revision } }; }
      return { runId: 'continuation' };
    },
  };
  const global = globalThis as unknown as { checkpointSdkTest: typeof fake };
  global.checkpointSdkTest = fake;
  const mocked = registerHooks({
    resolve(specifier, context, next) {
      if (specifier.startsWith('openclaw/plugin-sdk/')) return { url: `mock-sdk:${specifier}`, shortCircuit: true };
      return next(specifier, context);
    },
    load(url, context, next) {
      if (url.startsWith('mock-sdk:')) return { format: 'module', shortCircuit: true,
        source: 'export const {getSessionEntry, readVisibleSessionTranscriptMessageEntries, readSessionTranscriptEvents, callGatewayFromCli} = globalThis.checkpointSdkTest;' };
      return next(url, context);
    },
  });
  const dir = mkdtempSync(join(tmpdir(), 'workflow-plugin-'));
  const hooks: Record<string, (...args: any[]) => any> = {};
  let service: any;
  let factory: any;
  const api = {
    runtime: { version: '2026.9.2', llm: { complete: async () => ({ text: JSON.stringify({
      objective: { primary: 'Research and write', success_criteria: [] },
      state: { facts: [], decisions: [], constraints: [], assumptions: [], open_questions: [], blockers: [] }, artifacts: [], next_stage_context: [],
    }) }) } },
    pluginConfig: { workflows: { report: ['A', 'C'] } },
    logger: { info() {}, warn() {}, error() {} },
    registerService(s: unknown) { service = s; },
    registerTool(f: unknown) { factory = f; },
    on(name: string, callback: (...args: any[]) => any) { hooks[name] = callback; },
  };
  try {
    const { default: plugin } = await import('../index.ts');
    plugin.register(api as unknown as OpenClawPluginApi);
    await service.start({ stateDir: dir });
    hooks.agent_turn_prepare({ prompt: 'Research and write', messages: [], queuedInjections: [] }, identity);
    hooks.before_tool_call({ toolName: 'workflow_checkpoint', toolCallId: 'call-1', runId: 'source' }, identity);
    const result = await factory(identity).execute('call-1', { workflow_id: 'report', stage_id: 'A', status: 'completed', next_stage: 'C' });
    assert.equal(result.isError, false); assert.equal(sends.length, 0);
    assert.equal(hooks.before_tool_call({ toolName: 'exec', runId: 'source' }, identity).block, true);
    assert.equal(hooks.before_agent_finalize({}, identity).action, 'finalize');
    await hooks.agent_end({ success: true, runId: 'source' }, identity);
    for (let i = 0; i < 100 && sends.length < 3; i++) await new Promise(resolve => setTimeout(resolve, 5));
    assert.deepEqual(sends.map(s => s[0]), ['agent.wait', 'sessions.reset', 'agent']);
    const params = sends[2][2] as Record<string, unknown>;
    const checkpointResult = JSON.parse(result.content[0].text);
    const archiveDir = join(dir, 'workflow-checkpoint', 'archives', checkpointResult.checkpoint_id);
    assert.match(readFileSync(join(archiveDir, 'context.json'), 'utf8'), /FULL_A_CONTEXT_SENTINEL/);
    assert.match(readFileSync(join(archiveDir, 'context-final.json'), 'utf8'), /FULL_A_CONTEXT_SENTINEL/);
    assert.doesNotMatch(String(params.message), /FULL_A_CONTEXT_SENTINEL/);
    assert.match(String(params.message), /Research and write/);
    assert.equal(params.message, readFileSync(join(archiveDir, 'restart-prompt.md'), 'utf8'));
    assert.equal(params.sessionKey, identity.sessionKey);
    assert.equal(params.expectedExistingSessionId, identity.sessionId);
    const injected = hooks.agent_turn_prepare({ prompt: params.message }, { ...identity, runId: 'continuation' });
    assert.match(injected.prependContext, /Resume Stage C/);
    assert.equal(hooks.before_tool_call({ toolName: 'exec', runId: 'continuation' }, { ...identity, runId: 'continuation' }), undefined);
    await hooks.agent_end({ success: true, runId: 'continuation' }, { ...identity, runId: 'continuation' });
    assert.equal(sends.length, 3);
    const { Store } = await import('../src/store.ts');
    const reader = new Store(join(dir, 'workflow-checkpoint', 'state.sqlite'));
    const savedCheckpoint = reader.checkpoint(checkpointResult.checkpoint_id)!;
    reader.close();
    const { OpenClawAdapter } = await import('../src/openclaw-adapter.ts');
    const adapter = new OpenClawAdapter(api as unknown as OpenClawPluginApi);
    await t.test('changed local prompt cannot trigger reset', async () => {
      const path = savedCheckpoint.handoff!.prompt_path;
      const original = readFileSync(path, 'utf8');
      writeFileSync(path, original + 'corrupted');
      const count = sends.length;
      try { await assert.rejects(adapter.requestContinuation(savedCheckpoint), /RESTART_ARCHIVE_CHANGED/); }
      finally { writeFileSync(path, original); }
      assert.equal(sends.length, count);
    });
    await t.test('new user input after archive prevents reset', async () => {
      revision = 'before-reset'; mode = 'new-user-input';
      const count = sends.length;
      await assert.rejects(adapter.requestContinuation(savedCheckpoint), /USER_INPUT_CHANGED_BEFORE_RESET/);
      assert.deepEqual(sends.slice(count).map(s => s[0]), ['agent.wait']);
      mode = 'normal';
    });
    await t.test('external reset with unchanged sessionId is detected by revision', async () => {
      revision = 'external-reset';
      const count = sends.length;
      await assert.rejects(adapter.requestContinuation(savedCheckpoint), /SESSION_BOUNDARY_CHANGED/);
      assert.deepEqual(sends.slice(count).map(s => s[0]), ['agent.wait']);
    });
    await t.test('reset failure never dispatches the next stage', async () => {
      revision = 'before-reset'; mode = 'reset-fails';
      const count = sends.length;
      await assert.rejects(adapter.requestContinuation(savedCheckpoint), /reset denied/);
      assert.deepEqual(sends.slice(count).map(s => s[0]), ['agent.wait', 'sessions.reset']);
      assert.match(readFileSync(join(archiveDir, 'context-final.json'), 'utf8'), /FULL_A_CONTEXT_SENTINEL/);
    });
  } finally {
    await service?.stop(); mocked.deregister(); rmSync(dir, { recursive: true, force: true });
  }
});
