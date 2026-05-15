# PentAGI 开发与自动化工作流

## 分支策略

```
main (生产发布)
  └── develop (开发主分支)
       ├── feature/* (新功能)
       ├── fix/* (Bug修复)
       └── docs/* (文档)
```

**核心规则：**
- ❌ 禁止直接推送到 `main`
- ❌ 禁止跳过 PR 流程
- ✅ 所有开发从 `develop` 创建分支
- ✅ 所有 PR 合并到 `develop`
- ✅ `main` 只从 `develop` 合入

## Git 流程

```bash
# 1. 从 develop 创建功能分支
git checkout develop
git pull origin develop
git checkout -b feature/my-feature

# 2. 开发 + 提交
git add -A
git commit -m "feat: describe your change"

# 3. 推送并创建 PR
git push origin feature/my-feature
# GitHub 上创建 PR → develop
```

## Commit 规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/):

| 类型 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `refactor` | 重构 |
| `test` | 测试相关 |
| `chore` | 构建/工具/依赖 |

## CI/CD 管线

Push 到 `develop` 自动触发：

```
Run Go Tests → Run Frontend Tests → Build Docker → Security Scan
      ↓              ↓                   ↓               ↓
Code Review ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ←
      ↓
Create PR to main → Deploy to Staging → Notify Team
```

### GitHub Actions

`.github/workflows/ci.yml` 覆盖：
- Go 测试（`go test ./...`）
- 前端测试（`npm test`）
- Docker 构建（`docker compose build`）
- 安全检查（`gosec` / `npm audit`）

## 开发环境

```bash
# 安装依赖
make deps

# 运行测试
make test

# 本地开发
make dev

# Docker 环境
make quickstart
```

## 代码审查清单

提交 PR 前检查：
- [ ] 测试通过（`make test`）
- [ ] lint 通过（`make lint`）
- [ ] 类型检查通过（`make typecheck` 若有）
- [ ] 无硬编码密钥
- [ ] 文档已更新
- [ ] CHANGELOG 已更新

## n8n 集成

CI/CD 工作流也可以用 n8n 来编排：

1. 导入 `.gstack/ci-workflow.json` 到 n8n
2. 配置 GitHub Webhook 触发
3. 自动执行测试 → 审查 → 部署

## 技术栈

- **后端**: Go 1.24
- **前端**: React 19 + TypeScript + Vite
- **数据库**: PostgreSQL + pgvector
- **容器**: Docker + docker-compose
