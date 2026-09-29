import { join } from 'node:path';
import { Registry } from './registry.mjs';
import { Store } from './store.mjs';

// Recovery is an explicit operator action. A saved "working" label is not proof
// that the process stopped, and an expired timer is never permission to reset.
export function requeuePersistedJob(id, config) {
  const registry = new Registry(config.stateDir);
  let store;
  try {
    registry.db.exec('BEGIN IMMEDIATE');
    const job = registry.job(id);
    if (!['queued', 'working', 'held'].includes(job.status)) throw Error('RECOVERY_JOB_NOT_ELIGIBLE');
    if (!Number.isInteger(job.worker_pid) || job.worker_pid <= 0) throw Error('RECOVERY_WORKER_ID_UNAVAILABLE');
    let absent = false;
    try { process.kill(job.worker_pid, 0); }
    catch (error) { absent = error.code === 'ESRCH'; }
    if (!absent) throw Error('RECOVERY_WORKER_STILL_PRESENT');
    const binding = registry.binding(job.token);
    if (binding.run_status !== 'ended') throw Error('RECOVERY_SOURCE_NOT_CONFIRMED_ENDED');
    const newer = registry.db.prepare('SELECT 1 FROM runs WHERE scope=? AND id<>? AND updated>=(SELECT updated FROM runs WHERE id=?)')
      .get(binding.scope, binding.run_id, binding.run_id);
    if (newer) throw Error('RECOVERY_NEWER_RUN_EXISTS');
    store = new Store(join(config.stateDir, 'state.sqlite'));
    const delivery = store.list(binding.identity).find(item => item.checkpoint.source_run_id === binding.run_id &&
      item.checkpoint.workflow.id === job.input.workflow_id && item.checkpoint.transition.from === job.input.stage_id);
    if (!delivery) throw Error('RECOVERY_CHECKPOINT_NOT_PERSISTED');
    // dispatching/held/submitted may already have reset or sent. Never replay them.
    if (delivery.status !== 'pending' && !(delivery.status === 'completed' && delivery.checkpoint.workflow.status !== 'running'))
      throw Error('RECOVERY_DELIVERY_AMBIGUOUS');
    registry.db.prepare("UPDATE jobs SET status='queued',code=NULL,checkpoint_id=? WHERE id=?")
      .run(delivery.checkpoint.checkpoint_id, id);
    registry.db.exec('COMMIT');
    return { id, status: 'queued', duplicate: true, recovered: true };
  } catch (error) {
    try { registry.db.exec('ROLLBACK'); } catch { /* No open transaction. */ }
    throw error;
  } finally { store?.close(); registry.close(); }
}
