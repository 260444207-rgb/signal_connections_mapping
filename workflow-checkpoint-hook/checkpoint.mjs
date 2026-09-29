import { validateSummaryConfig } from './src/summarizer.mjs';
import { readConfig } from './src/config.mjs';
import { Registry } from './src/registry.mjs';
import { parseInput } from './src/types.mjs';
import { loadSdk } from './src/sdk.mjs';
import { executeJob } from './src/worker.mjs';
import { requeuePersistedJob } from './src/recovery.mjs';
import { launchWorker } from './src/launch.mjs';
const [action, ...args] = process.argv.slice(2);
const options = {};
try {
  for (let i = 0; i < args.length; i += 2) {
    if (!args[i].startsWith('--') || args[i + 1] === undefined || options[args[i].slice(2)] !== undefined)
      throw Error('INVALID_ARGUMENTS');
    options[args[i].slice(2)] = args[i + 1];
  }
  const config = readConfig();
  if (action === 'work') {
    if (!/^job_[a-f0-9]{64}$/.test(options.job || ''))
      throw Error('INVALID_JOB_ID');
    console.log(JSON.stringify(await executeJob(options.job, config, await loadSdk())));
  }
  else if (action === 'status') {
    const registry = new Registry(config.stateDir);
    try {
      const job = registry.job(options.job);
      console.log(JSON.stringify({ id: job.id, status: job.status, code: job.code, checkpoint_id: job.checkpoint_id }));
    }
    finally {
      registry.close();
    }
  }
  else if (action === 'recover') {
    if (!/^job_[a-f0-9]{64}$/.test(options.job || '') || Object.keys(options).some(key => key !== 'job'))
      throw Error('INVALID_ARGUMENTS');
    await loadSdk();
    const job = requeuePersistedJob(options.job, config);
    const registry = new Registry(config.stateDir);
    try {
      await launchWorker(job, config, registry);
      console.log(JSON.stringify({ accepted: true, recovered: true, job_id: job.id, status: job.status }));
    } finally { registry.close(); }
  }
  else if (action === 'request') {
    if (Object.keys(options).some(k => !['token', 'workflow', 'stage', 'next', 'status'].includes(k)))
      throw Error('INVALID_ARGUMENTS');
    validateSummaryConfig(config.summarizer);
    const input = parseInput({ workflow_id: options.workflow, stage_id: options.stage, status: options.status || 'completed',
      ...(options.next ? { next_stage: options.next } : {}), reason: 'stage_boundary' });
    const stages = config.workflows[input.workflow_id];
    const index = stages?.indexOf(input.stage_id) ?? -1;
    if (index < 0 || (input.status === 'completed' && stages[index + 1] !== input.next_stage))
      throw Error('INVALID_TRANSITION');
    await loadSdk();
    const registry = new Registry(config.stateDir);
    try {
      const job = registry.enqueue(options.token, input);
      await launchWorker(job, config, registry);
      console.log(JSON.stringify({ accepted: job.status === 'queued' || job.status === 'working' || job.status === 'done',
        job_id: job.id, duplicate: job.duplicate, status: job.status,
        instruction: 'End this run now. Do not execute the next stage or poll status from this run.' }));
    }
    finally {
      registry.close();
    }
  }
  else
    throw Error('USE_REQUEST_STATUS_RECOVER_OR_WORK');
}
catch (error) {
  console.log(JSON.stringify({ accepted: false, code: /^[A-Z][A-Z0-9_]+$/.test(error.message) ? error.message : 'CHECKPOINT_REQUEST_FAILED' }));
  process.exitCode = 1;
}
