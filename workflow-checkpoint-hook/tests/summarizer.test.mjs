import test from 'node:test';
import assert from 'node:assert/strict';
import { completeSummary, validateSummaryConfig } from '../src/summarizer.mjs';

const request = { agentId: 'writer', systemPrompt: 'JSON only', messages: [{ role: 'user', content: 'evidence' }], maxTokens: 6000, temperature: 0 };
function fixture() {
  const calls = [];
  const cfg = { agents: { list: [{ id: 'writer', model: 'provider/registered' }] } };
  const model = { id: 'registered' }, auth = { apiKey: 'fixture-secret' };
  const runtime = { loadConfig: () => cfg, listAgentIds: () => ['writer', 'reviewer'],
    prepareSimpleCompletionModelForAgent: async params => { calls.push(params); return { model, auth }; },
    completeWithPreparedSimpleCompletionModel: async params => { calls.push(params); return { content: [{ type: 'text', text: '{"ok":true}' }], stopReason: 'stop' }; } };
  return { calls, cfg, model, auth, runtime, sdk: { loadAgentCompletionRuntime: async () => runtime } };
}
test('omitted, empty, and legacy blank summarizer reuse bound registered Agent model and authentication', async () => {
  for (const config of [undefined, {}, { baseUrl: '', model: '', apiKeyEnv: 'NOT_SET' }]) {
    const f = fixture();
    assert.equal((await completeSummary(config, request, f.sdk)).text, '{"ok":true}');
    assert.deepEqual(f.calls[0], { cfg: f.cfg, agentId: 'writer', useUtilityModel: false });
    assert.equal(f.calls[1].model, f.model);
    assert.equal(f.calls[1].auth, f.auth);
    assert.equal(f.calls[1].context.messages[0].content, 'evidence');
  }
});
test('Agent selection is resolved separately for every bound Agent', async () => {
  const f = fixture();
  await completeSummary(undefined, request, f.sdk);
  await completeSummary(undefined, { ...request, agentId: 'reviewer' }, f.sdk);
  assert.equal(f.calls[2].agentId, 'reviewer');
  await assert.rejects(completeSummary(undefined, { ...request, agentId: 'missing' }, f.sdk), /SUMMARY_AGENT_NOT_REGISTERED/);
});
test('Agent model/auth failure is sanitized and never falls back to an external service', async () => {
  const f = fixture();
  f.runtime.prepareSimpleCompletionModelForAgent = async () => { throw Error('fixture-secret'); };
  await assert.rejects(completeSummary(undefined, request, f.sdk), /^Error: AGENT_MODEL_PREPARE_FAILED$/);
  assert.equal(f.calls.length, 0);
});
test('empty or failed Agent completions are rejected', async () => {
  const f = fixture();
  for (const result of [{ content: [] }, { content: [{ type: 'text', text: '{}' }], stopReason: 'error' }]) {
    f.runtime.completeWithPreparedSimpleCompletionModel = async () => result;
    await assert.rejects(completeSummary(undefined, request, f.sdk), /SUMMARIZER_INVALID_RESPONSE/);
  }
});
test('partial external configuration and missing external key fail without Agent fallback', () => {
  assert.throws(() => validateSummaryConfig({ model: 'override' }), /SUMMARIZER_CONFIG_INCOMPLETE/);
  assert.throws(() => validateSummaryConfig({ baseUrl: 'https://example.com/v1' }), /SUMMARIZER_CONFIG_INCOMPLETE/);
  assert.throws(() => validateSummaryConfig({ baseUrl: 'https://example.com/v1', model: 'override', apiKeyEnv: 'CHECKPOINT_TEST_MISSING_KEY' }), /SUMMARIZER_API_KEY_MISSING/);
});
test('already aborted summary never loads Agent runtime', async () => {
  await assert.rejects(completeSummary(undefined, { ...request, signal: AbortSignal.abort() }, { loadAgentCompletionRuntime: () => assert.fail('unexpected model preparation') }), /abort/i);
});
