import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, cp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const source = dirname(dirname(fileURLToPath(import.meta.url)));
const hash = text => createHash('sha256').update(text).digest('hex');
const readJson = async path => JSON.parse(await readFile(path, 'utf8'));
async function readLines(path) {
  try { return (await readFile(path, 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
}
async function until(action, description, timeout = 12000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await action();
    if (result) return result;
    await delay(80);
  }
  throw Error('Timed out: ' + description);
}

for (const summaryMode of ['external', 'agent']) test(`real CLI and detached worker with ${summaryMode} summary migrate session, send saved prompt, and stop at final stage`, { timeout: 40000 }, async () => {
  const temp = await mkdtemp(join(tmpdir(), 'workflow-hook-process-'));
  const copied = join(temp, 'hook');
  const fakeRoot = join(temp, 'openclaw');
  const stateDir = join(temp, 'state');
  const machinePath = join(fakeRoot, 'machine.json');
  const rpcPath = join(fakeRoot, 'rpc.ndjson');
  const workersPath = join(fakeRoot, 'workers.ndjson');
  const workspace = join(temp, 'workspace');
  const identity = { agentId: 'main', sessionKey: 'agent:main:process-test', sessionId: 'same-session' };
  const originalUser = 'Produce a report from evidence and keep the intermediate files.';
  const toolEvidence = 'COMPLETE_TOOL_RESULT_ONLY_IN_LOCAL_ARCHIVE';
  const artifact = join(workspace, 'research.md');
  const summaryRequests = [];
  let hook;
  let http;
  let failure;
  let emit;
  const config = {
    openclawPackageRoot: fakeRoot, stateDir, waitTimeoutMs: 10000,
    workflows: { report: ['research', 'draft'] },
    workflowSkills: { report: join(workspace, 'SKILL.md') },
    summarizer: { model: 'local-fixture', apiKeyEnv: 'WORKFLOW_PROCESS_TEST_KEY' },
  };
  const machine = {
    entry: { sessionId: identity.sessionId, lifecycleRevision: 'revision-research' },
    messages: [
      { role: 'user', content: originalUser },
      { role: 'assistant', content: 'I will save the research file.' },
      { role: 'toolResult', content: toolEvidence },
    ],
    events: [{ type: 'raw-event', text: 'RAW_TRANSCRIPT_EVENT' }],
  };
  const cli = args => new Promise((resolve, reject) => {
    execFile(process.execPath, [join(copied, 'checkpoint.mjs'), ...args], {
      cwd: copied, windowsHide: true, timeout: 12000, maxBuffer: 100000,
      env: { ...process.env, WORKFLOW_PROCESS_TEST_KEY: summaryMode === 'external' ? 'local-test-only' : '' },
    }, (error, stdout, stderr) => {
      if (error) return reject(Error('CLI failed: ' + stdout + '\n' + stderr, { cause: error }));
      try { resolve(JSON.parse(stdout.trim().split('\n').at(-1))); }
      catch { reject(Error('CLI did not return JSON: ' + stdout)); }
    });
  });
  const status = id => cli(['status', '--job', id]);
  const terminal = async id => {
    const job = await until(async () => {
      const value = await status(id);
      return ['done', 'held'].includes(value.status) && value;
    }, 'job terminal state');
    assert.equal(job.status, 'done', JSON.stringify(job));
    return job;
  };
  const event = (runId, phase) => emit({
    ...identity, runId, seq: phase === 'start' ? 1 : 2,
    stream: 'lifecycle', ts: Date.now(), data: { phase },
  });
  const token = async () => {
    const bootstrapFiles = [{ name: 'AGENTS.md', path: join(workspace, 'AGENTS.md'), content: 'Keep existing guidance.', missing: false }];
    await hook({ type: 'agent', action: 'bootstrap', sessionKey: identity.sessionKey, context: { ...identity, workspaceDir: workspace, bootstrapFiles } });
    assert.ok(bootstrapFiles[0].content.startsWith('Keep existing guidance.'));
    const value = /current-run binding token is: ([a-f0-9-]+)/.exec(bootstrapFiles[0].content)?.[1];
    assert.ok(value, 'default Hook injected a binding token');
    return value;
  };
  try {
    await cp(source, copied, { recursive: true, filter: path => !path.split(/[\\/]/).includes('node_modules') });
    await mkdir(fakeRoot, { recursive: true });
    await mkdir(workspace, { recursive: true });
    await writeFile(artifact, '# Research\nObserved evidence.\n');
    await writeFile(config.workflowSkills.report, '# Report Skill\nStages: research, draft. Stop after accepted=true.\n');
    await writeFile(machinePath, JSON.stringify(machine));
    await writeFile(join(fakeRoot, 'package.json'), JSON.stringify({
      name: 'openclaw', version: '2026.7.1', type: 'module',
      exports: Object.fromEntries(['agent-harness-runtime', 'session-store-runtime', 'session-transcript-runtime', 'gateway-runtime', 'session-key-runtime', 'agent-core', 'agent-runtime', 'config-runtime'].map(name => ['./plugin-sdk/' + name, './' + name + '.mjs'])),
    }));
    await writeFile(join(fakeRoot, 'common.mjs'), [
      "import { readFileSync, writeFileSync, appendFileSync, readdirSync, existsSync } from 'node:fs';",
      "import { dirname, join } from 'node:path';",
      "import { fileURLToPath } from 'node:url';",
      "export const root = dirname(fileURLToPath(import.meta.url));",
      "export const read = () => JSON.parse(readFileSync(join(root, 'machine.json'), 'utf8'));",
      "export const write = state => writeFileSync(join(root, 'machine.json'), JSON.stringify(state));",
      "export const log = value => appendFileSync(join(root, 'rpc.ndjson'), JSON.stringify(value) + '\\n');",
      "if (process.argv[2] === 'work') {",
      "  appendFileSync(join(root, 'workers.ndjson'), JSON.stringify({ pid: process.pid, event: 'start' }) + '\\n');",
      "  process.on('exit', () => appendFileSync(join(root, 'workers.ndjson'), JSON.stringify({ pid: process.pid, event: 'exit' }) + '\\n'));",
      "}",
      "export function archiveEvidence() {",
      "  const archives = join(root, '..', 'state', 'archives');",
      "  return readdirSync(archives).map(id => {",
      "    const dir = join(archives, id);",
      "    return { id, checkpoint: existsSync(join(dir, 'checkpoint.json')), context: existsSync(join(dir, 'context.json')), finalContext: existsSync(join(dir, 'context-final.json')), prompt: existsSync(join(dir, 'restart-prompt.md')) };",
      "  });",
      "}",
    ].join('\n'));
    await writeFile(join(fakeRoot, 'agent-harness-runtime.mjs'), [
      "export const OPENCLAW_VERSION = '2026.7.1';",
      "let listener;",
      "export const onAgentEvent = callback => { listener = callback; return () => { listener = undefined; }; };",
      "export const emit = payload => listener?.(payload);",
    ].join('\n'));
    await writeFile(join(fakeRoot, 'session-store-runtime.mjs'), "import { read } from './common.mjs';\nexport const getSessionEntry = () => read().entry;\n");
    await writeFile(join(fakeRoot, 'session-transcript-runtime.mjs'), [
      "import { read } from './common.mjs';",
      "export const readSessionTranscriptEvents = async () => [...read().events, ...read().messages.map(message => ({ type: 'message', message }))];",
    ].join('\n'));
    await writeFile(join(fakeRoot, 'agent-core.mjs'), "import { readFileSync } from 'node:fs';\nexport const SessionManager = { open: path => ({ getBranch: () => readFileSync(path, 'utf8').trim().split('\\n').map(JSON.parse).filter(e => e.type === 'message') }) };\n");
    await writeFile(join(fakeRoot, 'session-key-runtime.mjs'), 'export const isIncognitoSessionKey = () => false;\n');
    await writeFile(join(fakeRoot, 'config-runtime.mjs'), 'export const loadConfig = () => ({ agents: { list: [{ id: "main", model: "registered-primary" }] } });');
    await writeFile(join(fakeRoot, 'agent-runtime.mjs'), [
      "import { appendFileSync } from 'node:fs';",
      "import { join } from 'node:path';",
      "import { root } from './common.mjs';",
      "export const listAgentIds = cfg => cfg.agents.list.map(a => a.id);",
      "export const prepareSimpleCompletionModelForAgent = async p => { if (p.useUtilityModel !== false) throw Error('wrong selection'); return { model: p.cfg.agents.list.find(a => a.id === p.agentId).model, auth: { apiKey: 'registered-auth' } }; };",
      "export const completeWithPreparedSimpleCompletionModel = async p => {",
      "  if (p.model !== 'registered-primary' || p.auth.apiKey !== 'registered-auth') throw Error('wrong model/auth');",
      "  appendFileSync(join(root, 'agent-summary.ndjson'), JSON.stringify({ model: p.model, context: p.context }) + '\\n');",
      "  return { stopReason: 'stop', content: [{ type: 'text', text: JSON.stringify(" + JSON.stringify({ objective: { primary: originalUser, success_criteria: ['Report saved'] }, state: { facts: [], decisions: [], constraints: [], assumptions: [], open_questions: [], blockers: [] }, artifacts: [{ type: 'file', path: artifact, purpose: 'Research' }], next_stage_context: ['Read research'] }) + ") }] };",
      "};",
    ].join('\n'));
    await writeFile(join(fakeRoot, 'gateway-runtime.mjs'), [
      "import { read, write, log, archiveEvidence } from './common.mjs';",
      "export async function callGatewayFromCli(method, options, params, extra) {",
      "  const state = read();",
      "  log({ method, options, params, extra, entry: state.entry, archives: archiveEvidence() });",
      "  if (method === 'agent.wait') return { status: 'ok' };",
      "  if (method === 'sessions.reset') {",
      "    state.entry = { sessionId: 'next-session' };",
      "    state.messages = []; state.events = []; write(state);",
      "    return { ok: true, key: params.key, entry: state.entry };",
      "  }",
      "  if (method === 'agent') {",
      "    state.messages.push({ role: 'user', content: params.message }); write(state);",
      "    return { runId: 'run-draft' };",
      "  }",
      "  throw Error('UNEXPECTED_FIXTURE_RPC');",
      "}",
    ].join('\n'));
    http = createServer(async (request, response) => {
      try {
        let body = '';
        for await (const chunk of request) body += chunk;
        const payload = JSON.parse(body);
        const input = JSON.parse(payload.messages.at(-1).content);
        const archives = await readdir(join(stateDir, 'archives'));
        const snapshots = await Promise.all(archives.map(id => readJson(join(stateDir, 'archives', id, 'context.json'))));
        summaryRequests.push({ url: request.url, authorization: request.headers.authorization, payload, input, snapshots });
        const structured = {
          objective: { primary: originalUser, success_criteria: ['Report saved'] },
          state: { facts: ['Research file exists'], decisions: ['Write draft next'], constraints: ['Preserve intermediate files'], assumptions: [], open_questions: [], blockers: [] },
          artifacts: [{ type: 'file', path: artifact, purpose: 'Observed research notes' }],
          next_stage_context: ['Read the research file before drafting.'],
        };
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(structured) } }] }));
      } catch (error) {
        response.writeHead(500); response.end(String(error));
      }
    });
    await new Promise(resolve => http.listen(0, '127.0.0.1', resolve));
    config.summarizer.baseUrl = 'http://127.0.0.1:' + http.address().port + '/v1';
    if (summaryMode === 'agent') delete config.summarizer;
    await writeFile(join(copied, 'config.json'), JSON.stringify(config));
    hook = (await import(pathToFileURL(join(copied, 'handler.js')).href)).default;
    emit = (await import(pathToFileURL(join(fakeRoot, 'agent-harness-runtime.mjs')).href)).emit;
    await hook({ type: 'gateway', action: 'startup', context: {} });

    event('run-research', 'start');
    const bound = await token();
    const args = ['request', '--token', bound, '--workflow', 'report', '--stage', 'research', '--next', 'draft'];
    const requests = await Promise.all([cli(args), cli(args)]);
    assert.ok(requests.every(value => value.accepted));
    assert.equal(requests[0].job_id, requests[1].job_id, 'concurrent requests share one durable job');
    assert.equal(requests.filter(value => value.duplicate).length, 1);
    const firstId = requests[0].job_id;
    await until(async () => (await status(firstId)).status === 'working', 'worker has claimed the job');
    await delay(120);
    assert.deepEqual(await readLines(rpcPath), [], 'no Gateway RPC before source run ends');
    assert.equal(summaryRequests.length, 0, 'no snapshot summary before source run ends');

    machine.messages.push({ role: 'assistant', content: 'STAGE_A_FINAL_RESPONSE_ARCHIVED' });
    await writeFile(machinePath, JSON.stringify(machine));
    event('run-research', 'end');
    const done = await terminal(firstId);
    const archiveDir = join(stateDir, 'archives', done.checkpoint_id);
    const checkpoint = await readJson(join(archiveDir, 'checkpoint.json'));
    const archived = await readFile(checkpoint.handoff.archive_path, 'utf8');
    const prompt = await readFile(checkpoint.handoff.prompt_path, 'utf8');
    const calls = await readLines(rpcPath);
    assert.deepEqual(calls.map(value => value.method), ['agent.wait', 'sessions.reset', 'agent']);
    assert.deepEqual(JSON.parse(archived).messages, machine.messages, 'complete post-run transcript is archived');
    assert.deepEqual(JSON.parse(archived).events, [...machine.events, ...machine.messages.map(message => ({ type: 'message', message }))]);
    assert.equal(hash(archived), checkpoint.handoff.archive_sha256);
    assert.equal(hash(prompt), checkpoint.handoff.prompt_sha256);
    assert.ok(prompt.includes(originalUser));
    assert.ok(prompt.includes(JSON.stringify(artifact)));
    assert.ok(!prompt.includes(toolEvidence), 'raw tool output stays in local archive');
    assert.deepEqual(checkpoint.progress, { completed_stages: ['research'], remaining_stages: ['draft'] });
    assert.equal(calls[1].params.key, identity.sessionKey);
    assert.equal(calls[1].params.agentId, identity.agentId);
    assert.ok(calls[1].archives.every(value => value.context && value.prompt && value.checkpoint && value.finalContext));
    assert.equal(calls[2].params.sessionKey, identity.sessionKey);
    assert.equal(calls[2].params.sessionId, 'next-session');
    assert.equal(calls[2].params.message, prompt, 'exact saved prompt is sent after reset');
    assert.equal(calls[2].entry.sessionId, 'next-session');
    assert.equal(calls[2].params.deliver, false);
    assert.deepEqual(await readJson(join(archiveDir, 'context-final.json')).then(value => value.messages), machine.messages);
    assert.equal((await readJson(join(archiveDir, 'restart-receipt.json'))).status, 'submitted');
    assert.equal(hash(await readFile(checkpoint.continuation.skill.snapshot_path, 'utf8')), checkpoint.continuation.skill.sha256);
    if (summaryMode === 'external') {
    assert.equal(summaryRequests.length, 1);
    assert.equal(summaryRequests[0].url, '/v1/chat/completions');
    assert.equal(summaryRequests[0].authorization, 'Bearer local-test-only');
    assert.equal(summaryRequests[0].snapshots[0].messages.at(-1).content, 'STAGE_A_FINAL_RESPONSE_ARCHIVED');

    } else {
      assert.equal(summaryRequests.length, 0);
      const summaries = await readLines(join(fakeRoot, 'agent-summary.ndjson'));
      assert.equal(summaries.length, 1);
      assert.ok(summaries[0].context.messages[0].content.includes('STAGE_A_FINAL_RESPONSE_ARCHIVED'));
    }
    assert.equal(calls[2].params.expectedExistingSessionId, undefined);
    identity.sessionId = 'next-session';
    event('run-draft', 'start');
    const nextToken = await token();
    const nextMachine = await readJson(machinePath);
    nextMachine.messages.push({ role: 'assistant', content: 'Final report saved. No next stage.' });
    await writeFile(machinePath, JSON.stringify(nextMachine));
    const last = await cli(['request', '--token', nextToken, '--workflow', 'report', '--stage', 'draft']);
    assert.equal(last.accepted, true);
    event('run-draft', 'end');
    const finalDone = await terminal(last.job_id);
    const finalCheckpoint = await readJson(join(stateDir, 'archives', finalDone.checkpoint_id, 'checkpoint.json'));
    assert.equal(finalCheckpoint.workflow.status, 'completed');
    assert.deepEqual(finalCheckpoint.progress.completed_stages, ['research', 'draft']);
    assert.deepEqual(finalCheckpoint.progress.remaining_stages, []);
    assert.equal(finalCheckpoint.handoff.user_inputs.length, 1, 'restart prompt is not reclassified as user input');
    assert.equal((await readLines(rpcPath)).length, 3, 'final stage archives but never resets or submits another run');
    assert.equal(summaryRequests.length, summaryMode === 'external' ? 2 : 0);
    if (summaryMode === 'agent') assert.equal((await readLines(join(fakeRoot, 'agent-summary.ndjson'))).length, 2);
  } catch (error) {
    failure = error;
    try {
      const names = await readdir(join(stateDir, 'logs'));
      for (const name of names) error.message += '\nWorker log ' + name + ':\n' + await readFile(join(stateDir, 'logs', name), 'utf8');
    } catch { /* A failure before enqueue has no worker log. */ }
    throw error;
  } finally {
    if (hook) await hook({ type: 'gateway', action: 'shutdown', context: {} });
    if (http) {
      http.closeAllConnections();
      await new Promise(resolve => http.close(resolve));
    }
    // The SDK fixture records only this test's spawned worker processes.
    // Wait for normal exit before deleting files; terminate only our own leftovers.
    const exited = await until(async () => {
      const events = await readLines(workersPath);
      return events.filter(value => value.event === 'start').every(value => events.some(end => end.pid === value.pid && end.event === 'exit'));
    }, 'detached test worker exit', 2000).catch(() => false);
    if (!exited) {
      const events = await readLines(workersPath);
      for (const value of events.filter(value => value.event === 'start' && !events.some(end => end.pid === value.pid && end.event === 'exit'))) {
        try { process.kill(value.pid); } catch (error) { if (error.code !== 'ESRCH') throw error; }
      }
      await delay(200);
    }
    const absolute = resolve(temp);
    assert.ok(absolute.startsWith(resolve(tmpdir()) + sep) && absolute.includes('workflow-hook-process-'));
    await rm(absolute, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
    if (!exited && !failure) assert.fail('Detached worker did not exit normally');
  }
});
