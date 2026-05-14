# Release Process

## Versioning

PentAGI follows [Semantic Versioning](https://semver.org/):

- **MAJOR** — incompatible API or breaking architectural changes
- **MINOR** — new features, no breaking changes
- **PATCH** — bug fixes, documentation, internal refactoring

Current release cycle: **monthly** (or sooner for critical fixes).

## Preparing a Release

1. **Create a release branch**
   ```bash
   git checkout -b release/vX.Y.Z main
   ```

2. **Update version** in `frontend/package.json` if needed

3. **Finalize [CHANGELOG.md](CHANGELOG.md)**
   - Group by: `Added`, `Changed`, `Fixed`, `Removed`, `Security`
   - Link each entry to its PR or issue

4. **Run final checks**
   ```bash
   make ci-check      # lint + test
   make docker-build  # verify Docker build
   ```

5. **Tag and push**
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

## CI Pipeline

The [CI workflow](.github/workflows/ci.yml) handles:

| Trigger | Action |
|---------|--------|
| Push to `main` | Build + test, Docker build (latest tag) |
| Push tag `v*` | Build + test, Docker build (versioned tags) |

Docker images are published to Docker Hub as `vxcontrol/pentagi`:
- `:latest` — latest commit on `main`
- `:X`, `:X.Y`, `:X.Y.Z` — versioned releases

## Post-Release

1. **Create a GitHub Release** — copy changelog entry as description
2. **Announce** in [Discord](https://discord.gg/2xrMh7qX6m) and [Telegram](https://t.me/+Ka9i6CNwe71hMWQy)
3. **Close the milestone** in GitHub Issues
