import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { CheckpointError } from './types.mjs';
export const digest = (text) => createHash('sha256').update(text).digest('hex');
export function durableWrite(path, text) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = path + '.' + randomUUID() + '.tmp';
  const fd = openSync(temporary, 'wx', 0o600);
  try {
    writeFileSync(fd, text, 'utf8');
    fsyncSync(fd);
  }
  finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
  const hash = digest(text);
  if (digest(readFileSync(path, 'utf8')) !== hash)
    throw new CheckpointError('ARCHIVE_VERIFY_FAILED');
  return hash;
}
export function userInputs(messages) {
  return messages.filter(message => {
    if (!message || typeof message !== 'object')
      return false;
    const m = message;
    if (m.role !== 'user')
      return false;
    const text = typeof m.content === 'string' ? m.content : Array.isArray(m.content)
      ? m.content.map(p => p && typeof p === 'object' && 'text' in p ? p.text : '').join('') : '';
    return !text.startsWith('[workflow-checkpoint:');
  });
}
export function mergeUserInputs(previous, current) {
  if (current.length >= previous.length && previous.every((m, i) => JSON.stringify(m) === JSON.stringify(current[i])))
    return current;
  return [...previous, ...current];
}
