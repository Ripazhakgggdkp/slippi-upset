# AGENTS.md

## Commits must follow Conventional Commits

Releases are fully automated. Every push to `main` runs
[go-semantic-release](https://github.com/go-semantic-release/semantic-release),
which reads the commit messages since the last tag to decide the next version,
then [GoReleaser](https://goreleaser.com) builds Windows, Linux and macOS
binaries and attaches them to the GitHub release (`.github/workflows/release.yml`,
`.goreleaser.yaml`).

**A commit that doesn't follow the format is invisible to the release builder:**
it ships no release and is left out of the release notes. So every commit on
`main` must look like:

```
<type>(<optional scope>): <short summary, lowercase, no period>
```

| Type | Release | Use for |
|---|---|---|
| `feat` | minor (1.**2**.0) | new user-facing behavior |
| `fix` | patch (1.2.**1**) | bug fixes |
| any type with `!` (`feat!:`), or a `BREAKING CHANGE:` footer | major (**2**.0.0) | changes that break config, CLI flags or saved files |
| `perf`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `style` | none | everything else |

Examples:

```
feat: play a sound when a friendly opponent joins
fix(replay): read placements from older replays
feat!: rename --test to --check

BREAKING CHANGE: --test was removed.
```

Pull requests merged with **squash** use the PR title as the commit message, so
the PR title must follow the same format.

## Before committing

- `gofmt -l .` prints nothing.
- `go vet ./...` passes, and also with `GOOS=windows` and `GOOS=darwin`: each
  platform has its own `platform_<os>.go` file.
- `go test ./...` passes.
- Use only the standard library plus `golang.org/x/sys`. Build with cgo off
  (`CGO_ENABLED=0`) so cross-compiling needs no C toolchain.
