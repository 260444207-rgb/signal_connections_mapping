import { spawn } from 'node:child_process';
import { openSync, closeSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { hookDirectory } from './config.mjs';

export async function launchWorker(job, config, registry) {
  if (job.status !== 'queued') return;
  mkdirSync(join(config.stateDir, 'logs'), { recursive: true, mode: 0o700 });
  const log = openSync(join(config.stateDir, 'logs', job.id + '.log'), 'a', 0o600);
  try {
    const child = spawn(process.execPath, [join(hookDirectory, 'checkpoint.mjs'), 'work', '--job', job.id],
      { detached: true, windowsHide: true, stdio: ['ignore', log, log], env: process.env });
    await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
    child.unref();
  } catch {
    registry.finish(job.id, 'held', 'WORKER_START_FAILED');
    throw Error('WORKER_START_FAILED');
  } finally { closeSync(log); }
}
