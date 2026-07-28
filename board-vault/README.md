# 单板金样前端

单板金样查询、录入和审批界面。本仓库只包含前端展示与接口调用适配，不包含数据库、文件解析、密钥认证或审批入库等后端实现。

## 本地运行

要求 Node.js 22.13 或更高版本。

```powershell
npm install
npm run dev
```

## 接入后端

复制 `.env.example` 为 `.env.local`，填写后端基础地址：

```text
NEXT_PUBLIC_API_BASE_URL=https://your-api.example.com
```

如果前后端使用相同域名，可以留空。全部接口请求集中在 `frontend/api.ts`，接口格式见 `docs/文件功能说明书.md`。

## 常用命令

```powershell
npm run dev
npm run build
npm test
npm run lint
```

## 目录

```text
frontend/   页面、样式、接口适配层
app/        页面框架入口
public/     网站静态资源
worker/     页面运行入口
build/      构建期配置
tests/      前端结构测试
docs/       接口与文件说明
```
