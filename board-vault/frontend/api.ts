export type ComparisonResult =
  | { kind: "duplicate"; recordCount: number; existingCount: number }
  | {
      kind: "conflict";
      conflictIds: string[];
      recordCount: number;
      existingCount: number;
    }
  | {
      kind: "pending";
      sourceKind: "new" | "conflict";
      submissionId: string;
      recordCount: number;
      existingCount: number;
    };

export type RecordRow = {
  component_name: string;
  item_id: string;
  manufacturer: string;
  feature_tag: string;
  payload_json: string;
  created_at: string;
};

export type Submission = {
  submission_id: string;
  component_name: string;
  manufacturer: string;
  feature_tag: string;
  comparison_result: "new" | "conflict";
  conflict_ids_json: string;
  tssch_filename: string;
  sheet_filename: string;
  created_at: string;
};

type ErrorPayload = { error?: string };

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "") ?? "";

function endpoint(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function readPayload<T>(response: Response): Promise<T & ErrorPayload> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      "后端接口尚未接入，请配置 NEXT_PUBLIC_API_BASE_URL 后再试。",
    );
  }
  return (await response.json()) as T & ErrorPayload;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(endpoint(path), init);
  const payload = await readPayload<T>(response);
  if (!response.ok) {
    throw new Error(payload.error || `接口请求失败（${response.status}）。`);
  }
  return payload;
}

export async function submitGoldenSample(input: {
  componentName: string;
  manufacturer: string;
  featureTag: string;
  tssch: File;
  sheet: File;
}): Promise<ComparisonResult> {
  const form = new FormData();
  form.append("componentName", input.componentName);
  form.append("manufacturer", input.manufacturer);
  form.append("featureTag", input.featureTag);
  form.append("tssch", input.tssch);
  form.append("sheet", input.sheet);

  const response = await fetch(endpoint("/api/submissions"), {
    method: "POST",
    body: form,
  });
  const payload = await readPayload<ComparisonResult>(response);
  if (!response.ok && payload.kind !== "conflict") {
    throw new Error(payload.error || "数据处理失败。");
  }
  return payload;
}

export async function searchRecords(query: string): Promise<RecordRow[]> {
  const payload = await request<{ records?: RecordRow[] }>(
    `/api/records?q=${encodeURIComponent(query)}`,
  );
  return payload.records ?? [];
}

export async function listPendingSubmissions(): Promise<Submission[]> {
  const payload = await request<{ submissions?: Submission[] }>(
    "/api/submissions?status=pending",
  );
  return payload.submissions ?? [];
}

export async function verifyApprovalFile(file: File): Promise<void> {
  const form = new FormData();
  form.append("key", file);
  await request("/api/approval/verify", { method: "POST", body: form });
}

export async function decidePendingSubmission(
  submissionId: string,
  decision: "approve" | "reject",
  approvalKey: File,
): Promise<{ affected?: number }> {
  const form = new FormData();
  form.append("key", approvalKey);
  form.append("decision", decision);
  return request(
    `/api/submissions/${encodeURIComponent(submissionId)}/decision`,
    { method: "POST", body: form },
  );
}
