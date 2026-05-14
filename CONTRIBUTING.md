# Contributing

Thanks for your interest in PentAGI! Contributions are welcome — whether it's bug fixes, features, docs, or just asking questions.

## Quick Links

- [README](README.md) — project overview and setup
- [Architecture docs](backend/docs/architecture/) — design decisions
- [Discord](https://discord.gg/2xrMh7qX6m) — community chat
- [Telegram](https://t.me/+Ka9i6CNwe71hMWQy) — team chat
- [Issues](https://github.com/vxcontrol/pentagi/issues) — bug reports and feature requests

## Getting Started

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/pentagi.git
cd pentagi

# Set up pre-commit hooks
make pre-commit-install

# Start development environment
make dev
```

## Pull Request Process

1. **Open an issue first** — discuss your change before writing code (unless it's a trivial fix)
2. **Create a feature branch** — `git checkout -b feat/my-change`
3. **Write tests** — new features must include tests; bug fixes should add a regression test
4. **Run lint and tests** locally:
   ```bash
   make lint
   make test
   ```
5. **Keep commits clean** — use [conventional commits](https://www.conventionalcommits.org/):
   - `feat:` — new feature
   - `fix:` — bug fix
   - `docs:` — documentation
   - `test:` — test additions/changes
   - `refactor:` — code restructuring
   - `chore:` — tooling, dependencies, CI
6. **Open a PR** against the `main` branch with:
   - Clear title and description
   - Link to the related issue
   - Screenshots for UI changes

## Code Standards

### Go (Backend)
- Follow [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- Run `golangci-lint` — committed in CI
- Use `logrus` for structured logging (not `fmt.Print*`)
- Tests must not depend on external services (mock or use testcontainers)

### TypeScript / React (Frontend)
- Follow the existing [Radix UI](https://www.radix-ui.com/) + Tailwind CSS patterns
- Run `npm run lint` and `npm run prettier` before committing
- GraphQL types are auto-generated: edit schema, then `npm run graphql:generate`
- Use `vitest` for unit tests

### Docker
- Multi-stage builds with cache mounts for faster iterations
- Keep the runtime image (alpine) as small as possible
- All new services must get a healthcheck

## Commit Messages

```
<type>(<scope>): <description>

[optional body explaining WHY, not what]
```

Examples:
- `feat(agent): add nmap version detection module`
- `fix(docker): correct pgvector healthcheck timeout`
- `docs(readme): simplify quickstart instructions`

## Review Process

PRs need at least one approval from a maintainer. We aim for:
- First review within 48 hours
- Merge within 1 week of approval
- Stale PRs are closed after 30 days of inactivity

## Code of Conduct

Be respectful. We're building security tools — not burning each other out. Harassment, trolling, and dismissive behavior will not be tolerated.
