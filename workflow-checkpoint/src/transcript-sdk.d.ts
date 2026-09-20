// 2026.9.2 publishes this JS export without a .d.ts. This narrow declaration
// reflects the public implementation, not a private SDK import.
declare module 'openclaw/plugin-sdk/session-transcript-runtime' {
  export function readSessionTranscriptEvents(params: { sessionKey: string; sessionId: string; agentId?: string }): Promise<unknown[]>;
  export function readVisibleSessionTranscriptMessageEntries(params: {
    sessionKey: string; sessionId: string; agentId?: string;
  }): Promise<Array<{ entryId: string; message: unknown }>>;
}
