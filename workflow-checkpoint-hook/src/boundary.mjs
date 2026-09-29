export function sessionBoundary(entry) {
  return entry?.lifecycleRevision || entry?.sessionId;
}
