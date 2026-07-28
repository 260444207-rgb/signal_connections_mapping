"use client";

import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import {
  ComparisonResult,
  decidePendingSubmission,
  listPendingSubmissions,
  RecordRow,
  searchRecords,
  Submission,
  submitGoldenSample,
  verifyApprovalFile,
} from "./api";

type Tab = "entry" | "query" | "approval";

function FileField({
  label,
  note,
  accept,
  file,
  onFile,
}: {
  label: string;
  note: string;
  accept: string;
  file: File | null;
  onFile: (file: File) => void;
}) {
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0];
    if (next) onFile(next);
  };
  const drop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    const next = event.dataTransfer.files?.[0];
    if (next) onFile(next);
  };

  return (
    <label
      className={`file-field ${file ? "selected" : ""}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={drop}
    >
      <input type="file" accept={accept} onChange={choose} />
      <span className="document-mark">{file ? "✓" : "＋"}</span>
      <span className="file-text">
        <strong>{file ? file.name : label}</strong>
        <small>
          {file
            ? `${(file.size / 1024).toFixed(1)} KB · 点击可替换`
            : note}
        </small>
      </span>
      <span className="file-action">{file ? "已选择" : "选择文件"}</span>
    </label>
  );
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("entry");
  const [componentName, setComponentName] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [featureTag, setFeatureTag] = useState("");
  const [tssch, setTssch] = useState<File | null>(null);
  const [sheet, setSheet] = useState<File | null>(null);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [recordsBusy, setRecordsBusy] = useState(false);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [approvalKey, setApprovalKey] = useState<File | null>(null);
  const [keyBusy, setKeyBusy] = useState(false);

  const showMessage = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(""), 3200);
  };

  const openFeature = (next: Tab) => {
    setTab(next);
    window.setTimeout(() => {
      if (next === "entry") {
        document
          .getElementById("entry-form")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }, 0);
  };

  const resetEntry = () => {
    setComponentName("");
    setManufacturer("");
    setFeatureTag("");
    setTssch(null);
    setSheet(null);
    setResult(null);
  };

  const submit = async () => {
    if (!componentName.trim() || !tssch || !sheet) {
      showMessage("请填写金样名称，并上传两个必需文件。");
      return;
    }
    setBusy(true);
    try {
      const payload = await submitGoldenSample({
        componentName: componentName.trim(),
        manufacturer: manufacturer.trim(),
        featureTag: featureTag.trim(),
        tssch,
        sheet,
      });
      setResult(payload);
      if (payload.kind === "pending") await loadSubmissions();
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "无法连接后端服务。");
    } finally {
      setBusy(false);
    }
  };

  const loadRecords = useCallback(async (search = "") => {
    setRecordsBusy(true);
    try {
      setRecords(await searchRecords(search));
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "查询失败。");
    } finally {
      setRecordsBusy(false);
    }
  }, []);

  const loadSubmissions = useCallback(async () => {
    try {
      setSubmissions(await listPendingSubmissions());
    } catch (error) {
      showMessage(
        error instanceof Error ? error.message : "无法读取审批队列。",
      );
    }
  }, []);

  useEffect(() => {
    if (tab === "query") {
      const timer = window.setTimeout(() => loadRecords(query), 250);
      return () => window.clearTimeout(timer);
    }
    if (tab === "approval") void loadSubmissions();
  }, [tab, query, loadRecords, loadSubmissions]);

  const verifyKey = async (file: File) => {
    setKeyBusy(true);
    try {
      await verifyApprovalFile(file);
      setApprovalKey(file);
      showMessage("密钥已认证，本次会话可以审批。");
    } catch (error) {
      setApprovalKey(null);
      showMessage(error instanceof Error ? error.message : "密钥认证失败。");
    } finally {
      setKeyBusy(false);
    }
  };

  const decide = async (
    submissionId: string,
    decision: "approve" | "reject",
  ) => {
    if (!approvalKey) {
      showMessage("请先完成密钥认证。");
      return;
    }
    try {
      const payload = await decidePendingSubmission(
        submissionId,
        decision,
        approvalKey,
      );
      showMessage(
        decision === "approve"
          ? `已批准并写入 ${payload.affected ?? 0} 条数据。`
          : "已驳回该记录。",
      );
      await loadSubmissions();
    } catch (error) {
      showMessage(error instanceof Error ? error.message : "审批失败。");
    }
  };

  return (
    <main>
      <header className="topbar">
        <button className="wordmark" onClick={() => setTab("entry")}>
          <span className="wordmark-symbol">B</span>
          <span>单板金样</span>
        </button>
        <nav aria-label="主导航">
          <button
            className={tab === "entry" ? "active" : ""}
            onClick={() => setTab("entry")}
          >
            数据录入
          </button>
          <button
            className={tab === "query" ? "active" : ""}
            onClick={() => setTab("query")}
          >
            数据查询
          </button>
          <button
            className={tab === "approval" ? "active" : ""}
            onClick={() => setTab("approval")}
          >
            审批
            {submissions.length > 0 && <sup>{submissions.length}</sup>}
          </button>
        </nav>
        <span className="system-state">
          <i />
          服务正常
        </span>
      </header>

      {tab === "entry" && (
        <>
          <section className="hero">
            <p className="overline">BOARD GOLDEN SAMPLE MANAGEMENT</p>
            <h1>
              让每一份金样
              <br />
              始终可信
            </h1>
            <p className="hero-copy">
              上传单板金样设计文件与数据表格。后端会检索同名金样、核对全部 ID，
              <br />
              并将新数据或冲突数据安全地送入审批流程。
            </p>
          </section>

          <section className="feature-nav" aria-label="功能入口">
            <button
              className="feature-card query-card"
              onClick={() => openFeature("query")}
            >
              <span className="feature-number">01</span>
              <div>
                <small>GOLDEN SAMPLE SEARCH</small>
                <h2>查询</h2>
                <p>按金样名称、ID 或生产厂家快速检索正式数据</p>
              </div>
              <span className="feature-link">进入查询</span>
            </button>
            <button
              className="feature-card entry-card"
              onClick={() => openFeature("entry")}
            >
              <span className="feature-number">02</span>
              <div>
                <small>NEW GOLDEN SAMPLE</small>
                <h2>录入</h2>
                <p>上传 TSSCH 与表格，由后端完成解析和数据比对</p>
              </div>
              <span className="feature-link">开始录入</span>
            </button>
            <button
              className="feature-card approval-card"
              onClick={() => openFeature("approval")}
            >
              <span className="feature-number">03</span>
              <div>
                <small>SECURE APPROVAL</small>
                <h2>审批</h2>
                <p>使用密钥确认待处理金样，并决定是否正式入库</p>
              </div>
              <span className="feature-link">进入审批</span>
            </button>
          </section>

          <section className="entry-section" id="entry-form">
            <div className="section-intro">
              <p className="overline">NEW GOLDEN SAMPLE</p>
              <h2>录入单板金样</h2>
              <p>金样数据不会未经审批直接写入正式库。</p>
            </div>

            <div className="entry-form">
              <div className="form-row">
                <label>
                  <span>金样名称 <b>*</b></span>
                  <input
                    value={componentName}
                    onChange={(event) => {
                      setComponentName(event.target.value);
                      setResult(null);
                    }}
                    placeholder="例如 HSCB-01 金样"
                  />
                </label>
                <label>
                  <span>生产厂家</span>
                  <input
                    value={manufacturer}
                    onChange={(event) => setManufacturer(event.target.value)}
                    placeholder="选填"
                  />
                </label>
              </div>

              <div className="file-row">
                <FileField
                  label="上传 TSSCH 文件"
                  note="点击选择或拖拽至此"
                  accept=".tssch"
                  file={tssch}
                  onFile={(file) => {
                    setTssch(file);
                    setResult(null);
                  }}
                />
                <FileField
                  label="上传数据表格"
                  note="支持 XLSX、XLS 与 CSV"
                  accept=".xlsx,.xls,.csv"
                  file={sheet}
                  onFile={(file) => {
                    setSheet(file);
                    setResult(null);
                  }}
                />
              </div>

              {result?.kind === "conflict" && (
                <div className="feature-panel">
                  <div>
                    <span>需要补充信息</span>
                    <strong>相同 ID 的数据存在差异</strong>
                    <p>
                      冲突 ID：{result.conflictIds.slice(0, 8).join("、")}
                    </p>
                  </div>
                  <label>
                    <span>特征标识</span>
                    <input
                      value={featureTag}
                      onChange={(event) => setFeatureTag(event.target.value)}
                      placeholder="例如 2026-Q3 / 替代料版本 A"
                    />
                  </label>
                </div>
              )}

              <div className="form-footer">
                <p>单文件最大 50 MB。上传内容由后端处理并暂存。</p>
                <button
                  className="primary"
                  onClick={submit}
                  disabled={
                    busy ||
                    (result?.kind === "conflict" && !featureTag.trim())
                  }
                >
                  {busy
                    ? "正在比对…"
                    : result?.kind === "conflict"
                      ? "补充并提交审批"
                      : "开始比对"}
                </button>
              </div>

              {result && result.kind !== "conflict" && (
                <ResultView result={result} reset={resetEntry} />
              )}
            </div>
          </section>
        </>
      )}

      {tab === "query" && (
        <section className="content-page">
          <div className="page-heading">
            <p className="overline">GOLDEN SAMPLE DATABASE</p>
            <h1>正式金样</h1>
            <p>查询已经通过审批并写入数据库的单板金样记录。</p>
          </div>
          <div className="search-line">
            <span>⌕</span>
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索金样名称、ID 或生产厂家"
            />
            <small>{recordsBusy ? "查询中" : `${records.length} 条结果`}</small>
          </div>
          <div className="data-list">
            <div className="data-head">
              <span>器件</span>
              <span>ID</span>
              <span>生产厂家</span>
              <span>特征标识</span>
              <span>入库时间</span>
            </div>
            {records.map((record) => (
              <div
                className="data-row"
                key={`${record.component_name}-${record.item_id}-${record.created_at}`}
              >
                <strong>{record.component_name}</strong>
                <code>{record.item_id}</code>
                <span>{record.manufacturer || "—"}</span>
                <span>{record.feature_tag || "—"}</span>
                <time>{formatDate(record.created_at)}</time>
              </div>
            ))}
            {!recordsBusy && records.length === 0 && (
              <div className="empty-state">
                <strong>尚无匹配数据</strong>
                <p>尝试使用其他名称或 ID 进行搜索。</p>
              </div>
            )}
          </div>
        </section>
      )}

      {tab === "approval" && (
        <section className="content-page">
          <div className="page-heading approval-heading">
            <div>
              <p className="overline">APPROVAL</p>
              <h1>待审批金样</h1>
              <p>只有通过密钥认证的当前会话可以批准或驳回金样入库。</p>
            </div>
            <label className={`key-control ${approvalKey ? "verified" : ""}`}>
              <input
                type="file"
                accept=".key"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void verifyKey(file);
                }}
              />
              <span>{approvalKey ? "✓" : "⌁"}</span>
              <div>
                <strong>
                  {keyBusy
                    ? "正在认证"
                    : approvalKey
                      ? "审批密钥已认证"
                      : "上传审批密钥"}
                </strong>
                <small>
                  {approvalKey ? "仅在本次会话有效" : "选择 approval.key"}
                </small>
              </div>
            </label>
          </div>

          <div className="approval-list">
            {submissions.map((item) => {
              const conflicts = JSON.parse(item.conflict_ids_json) as string[];
              return (
                <article className="approval-row" key={item.submission_id}>
                  <div className="approval-main">
                    <span className="status-label">
                      {item.comparison_result === "conflict"
                        ? "数据冲突"
                        : "新增数据"}
                    </span>
                    <h2>{item.component_name}</h2>
                    <p>
                      {item.manufacturer || "未填写厂家"} ·{" "}
                      {item.feature_tag || "无特征标识"}
                    </p>
                  </div>
                  <div className="approval-meta">
                    <span>审批编号</span>
                    <code>{item.submission_id}</code>
                    <small>
                      {item.tssch_filename} · {item.sheet_filename}
                    </small>
                    {conflicts.length > 0 && (
                      <small>冲突 ID：{conflicts.slice(0, 6).join("、")}</small>
                    )}
                  </div>
                  <div className="approval-actions">
                    <button
                      onClick={() => void decide(item.submission_id, "reject")}
                      disabled={!approvalKey}
                    >
                      驳回
                    </button>
                    <button
                      className="primary"
                      onClick={() => void decide(item.submission_id, "approve")}
                      disabled={!approvalKey}
                    >
                      批准入库
                    </button>
                  </div>
                </article>
              );
            })}
            {submissions.length === 0 && (
              <div className="empty-state">
                <strong>没有等待处理的数据</strong>
                <p>新的提交会显示在这里。</p>
              </div>
            )}
          </div>
        </section>
      )}

      <footer>
        <span>单板金样</span>
        <p>前端交互与后端数据服务分离 · 文件密钥审批</p>
      </footer>
      {message && <div className="toast">{message}</div>}
    </main>
  );
}

function ResultView({
  result,
  reset,
}: {
  result: Exclude<Result, { kind: "conflict" }>;
  reset: () => void;
}) {
  const duplicate = result.kind === "duplicate";
  return (
    <div className={`result ${duplicate ? "duplicate" : "pending"}`}>
      <span className="result-symbol">{duplicate ? "✓" : "→"}</span>
      <div>
        <small>{duplicate ? "COMPARISON COMPLETE" : "READY FOR APPROVAL"}</small>
        <h3>
          {duplicate
            ? "数据库中已有完全一致的数据"
            : "数据已安全进入临时审批区"}
        </h3>
        <p>
          {duplicate
            ? `上传的 ${result.recordCount} 条金样数据与正式库完全一致，无需重复录入。`
            : `审批编号 ${result.submissionId}。通过密钥审批后才会写入正式金样库。`}
        </p>
      </div>
      <button onClick={reset}>继续录入</button>
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(date);
}
