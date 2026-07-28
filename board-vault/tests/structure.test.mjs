import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("纯前端核心文件齐全", async () => {
  const requiredFiles = [
    "frontend/GoldenSampleApp.tsx",
    "frontend/api.ts",
    "frontend/styles.css",
  ];

  await Promise.all(requiredFiles.map((file) => access(new URL(file, root))));
});

test("页面入口保持轻量", async () => {
  const page = await readFile(new URL("app/page.tsx", root), "utf8");
  const layout = await readFile(new URL("app/layout.tsx", root), "utf8");

  assert.match(page, /frontend\/GoldenSampleApp/);
  assert.match(layout, /frontend\/styles\.css/);
});

test("接口调用集中在前端适配层", async () => {
  const page = await readFile(
    new URL("frontend/GoldenSampleApp.tsx", root),
    "utf8",
  );
  const api = await readFile(new URL("frontend/api.ts", root), "utf8");

  assert.doesNotMatch(page, /\bfetch\s*\(/);
  assert.match(api, /NEXT_PUBLIC_API_BASE_URL/);
});
