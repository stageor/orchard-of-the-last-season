# CI/CD

The repository uses GitHub Actions for every validation, build and release. The
aim is simple: a green `Required checks` means the exact Unity project compiled,
the real EditMode and PlayMode tests passed, and both players were built and
verified. A red or skipped mandatory job must block the merge.

## Workflow map

| Workflow | Triggers | Purpose |
| --- | --- | --- |
| [`ci.yml`](../.github/workflows/ci.yml) | `pull_request` to `main`, `push` to `main`, manual | Classifies the diff, runs repository health, C# analysis, EditMode, PlayMode, Windows x64, WebGL, and the final `Required checks` gate. |
| [`unity-tests.yml`](../.github/workflows/unity-tests.yml) | `workflow_call` | Reusable EditMode/PlayMode runner with real NUnit XML parsing. |
| [`unity-build.yml`](../.github/workflows/unity-build.yml) | `workflow_call` | Reusable Windows x64/WebGL builder with artifact verification. |
| [`review-gate.yml`](../.github/workflows/review-gate.yml) | `pull_request_target`, `pull_request_review`, `issue_comment` | Creates the required `Review gate` check for the three-person approval policy. |
| [`security.yml`](../.github/workflows/security.yml) | PR, push to `main`, weekly schedule, manual | Dependency review, CodeQL for Python and Actions, and gitleaks. |
| [`release.yml`](../.github/workflows/release.yml) | `v*` tags | Rebuilds, re-verifies, packages and publishes a GitHub Release. |
| [`nightly-regression.yml`](../.github/workflows/nightly-regression.yml) | Daily schedule, manual | Expanded deterministic seed sweep, PlayMode smoke and WebGL contract build. |

## Required checks

Branch protection must require exactly these two check names:

1. **`Required checks`**
2. **`Review gate`**

`Required checks` depends on every mandatory job and fails closed when a job:

- failed,
- was cancelled,
- was skipped for any reason other than a documentation-only pull request,
- is missing from the dependency graph,
- or reported an unexpected result.

The reusable Unity jobs also produce their own check runs, but they are not the
branch-protection contract. Requiring only the aggregate avoids a long list of
names that can drift when a job is renamed.

### Documentation-only pull requests

`ci.yml` deliberately has no `paths` or `paths-ignore` filter. A path filter
that misses a new extension, a deleted test or a renamed workflow silently
bypasses Unity validation. Instead, `scripts/detect_changes.py` uses an
allow-list:

- `*.md`, `docs/**`, `LICENSE`, `NOTICE`, issue templates and the PR template
  are documentation.
- Everything else, including unknown extensions, deletions, `Assets/**`,
  `ProjectSettings/**`, `Packages/**`, `.github/**`, `scripts/**` and
  `tests/ci/**`, forces the full Unity path.

A documentation-only pull request still runs repository health and C# contract
analysis. It may skip the four licensed Unity jobs. Changes under protected CI
paths still need `/approve-ci` from a non-author roster member.

### Fork pull requests

GitHub does not expose repository secrets to `pull_request` runs from forks.
The licensed EditMode, PlayMode and build jobs are skipped, and `Required
checks` fails with explicit instructions. This is intentional: a fork build
without a licence would either fail confusingly or, worse, tempt a maintainer to
disable validation. Use the validation-branch process in
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Job details

### `changes`

Fetches full history, compares the base and head commits, and writes
`docs_only`, `unity`, `build`, `protected` and `fork` outputs. If the base SHA is
missing or all zeroes, it forces full validation instead of guessing.

### `repository-health`

Installs the pinned CI dependencies, compiles all Python tooling, runs the CI
tooling tests with `unittest`, and runs `scripts/validate_repository.py`. The
validator checks:

- required files and workflow structure,
- full-SHA action pins and job permissions,
- no `paths` filter on `ci.yml`,
- the `Required checks` name, `if: always()` and dependency list,
- safe review-gate checkout and `persist-credentials: false`,
- reusable workflows expose `workflow_call`,
- security and nightly/release triggers,
- Unity `.meta` coverage, orphaned metas and duplicate GUIDs,
- the bootstrap scene and `EditorBuildSettings` GUID,
- package pins and lock entries,
- WebGL compression is Disabled,
- team.json/CODEOWNERS consistency,
- Dependabot ecosystems,
- `.gitignore`/`.gitattributes`,
- broken local Markdown links,
- tracked `.DS_Store`, binary and generated files.

### `csharp-analysis`

Runs `scripts/csharp_analysis.py`. It is not a C# compiler; Unity compiles the
project for real in the EditMode and PlayMode jobs. This job enforces rules a
compiler cannot:

- runtime namespace `Orchard`, editor namespace `Orchard`/`Orchard.CI`/`Orchard.Editor`,
- editor code lives under `Assets/Orchard/Editor` and is wrapped in
  `#if UNITY_EDITOR`,
- no mouse, controller, function-key or number-key input,
- no `Resources.Load`,
- no native `DllImport`,
- a real `[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]`
  bootstrap exists,
- balanced brackets and basic style warnings.

Pre-existing deviations are suppressed with reasons in
`.github/csharp-baseline.json`. New violations fail. A suppression that no
longer matches any code is reported as stale.

### `unity-editmode` and `unity-playmode`

Both call `unity-tests.yml`. The workflow:

1. Reads the exact editor version from `ProjectSettings/ProjectVersion.txt`.
2. Builds the exact GameCI image name from `scripts/unity_version.py`.
3. Restores the Unity `Library` cache.
4. Runs the real Unity Test Runner in Docker.
5. Parses the NUnit XML with `scripts/test_summary.py`.
6. Fails on failed tests, skipped/inconclusive tests, empty discovery, too few
   tests or the wrong namespace.
7. Uploads the XML, JSON and Markdown reports even when the tests fail.

EditMode requires at least 120 discovered tests; PlayMode requires at least one
real end-to-end smoke test.

### `build-windows` and `build-webgl`

Both call `unity-build.yml`, which:

1. Resolves the exact editor image and target paths.
2. Runs `Orchard.CI.OrchardBuild.BuildWindows` or `BuildWebGL`.
3. Writes `BUILD_INFO.txt` with the Unity version, commit, target, size and
   WebGL compression mode.
4. Runs `scripts/verify_build.py` before anything is uploaded.
5. Uploads only the verified build plus a verification report.

Windows verification checks the PE header, `UnityPlayer.dll`, the data directory,
`globalgamemanagers`, scene data, the exact Unity version and the commit. WebGL
verification checks `index.html`, the `Build/` payload, the WebAssembly magic,
the `.data` file, disabled compression, the absence of `.gz`/`.br`/`.unityweb`/
`.zip` payloads, the exact version and the commit.

## Artifacts and downloads

Every successful PR run keeps its builds for 14 days. Nightly WebGL builds are
kept for 7 days and nightly test reports for 30 days. Release builds are kept for
30 days and are also attached to the GitHub Release permanently.

To download a CI build:

1. Open the repository's **Actions** tab.
2. Select the **CI** workflow and the run for your commit.
3. Scroll to **Artifacts**.
4. Download `orchard-windows-x64` or `orchard-webgl`.
5. Verify the build against `BUILD_INFO.txt` and the run's verification report.

Release downloads and checksums are described in
[`BUILD_AND_RELEASE.md`](BUILD_AND_RELEASE.md).

## Concurrency and cost

- `ci.yml` uses `ci-<workflow>-<PR number or ref>` with
  `cancel-in-progress: true`, so superseded pushes stop consuming runners.
- Security runs cancel superseded runs on the same ref.
- Nightly and release runs do not cancel an in-progress run.
- The Unity `Library` cache is keyed by the exact editor version and
  `Packages/packages-lock.json`, with a version-only restore key.
- A single Unity licence seat is enough for this repository because CI
  concurrency is cancelled per pull request. Do not run the same PR and a
  release build simultaneously on a one-seat licence.

## Pinned actions

Every action is pinned to a full commit SHA. These are the reviewed versions:

| Action | Version | Commit |
| --- | --- | --- |
| `actions/checkout` | 7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | 7.1.0 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| `actions/upload-artifact` | 7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/download-artifact` | 8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `actions/cache` | 6.1.0 | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| `actions/dependency-review-action` | 5.0.0 | `a1d282b36b6f3519aa1f3fc636f609c47dddb294` |
| `github/codeql-action` | 4.39.3 | `33d7b85da1a04171e211befe2c739303b9a4c066` |
| `game-ci/unity-test-runner` | 4.4.0 | `32e57712352b500e17974b245a6dce9e11a73213` |
| `game-ci/unity-builder` | 6.0.0 | `eb1b9fba120c6e62c9fb7a7a81d6c107ce004c45` |
| `gitleaks/gitleaks-action` | 3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` |
| `softprops/action-gh-release` | 3.0.4 | `8a0cd651e5b2365bd640854a3fa5dfc70e4875f3` |

Dependabot updates these through pull requests. The repository validator rejects
tag or branch references.

## Security

- Workflows default to `contents: read`.
- The review gate has `checks: write` and `issues: write` only because it creates
  the required check and updates one comment.
- The release job has `contents: write` only to create the release.
- No workflow checks out pull-request head code with a write token.
- CodeQL covers Python and GitHub Actions. C# requires a Unity-generated
  solution and a licensed editor, so it is covered by the real Unity compile and
  the contract analyser.
- gitleaks runs with `.gitleaks.toml`; the only allowlist entries are public
  documentation and test fixtures.

See [`SECURITY.md`](../SECURITY.md) for reporting and secret rotation.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Required checks` fails but jobs look green | A mandatory job was skipped or cancelled. Open the job summary; the gate lists the exact job and result. |
| Unity licence error | `UNITY_LICENSE` is missing/expired or the licence seat is already in use. Re-activate and update the secret. |
| GameCI image not found | Confirm the exact editor version in `ProjectVersion.txt` has a corresponding `unityci/editor` image. Do not silently upgrade the editor. |
| PlayMode test times out | Inspect the uploaded XML and the Unity log artifact. The smoke test waits for real frames. |
| WebGL verification fails | Compression is enabled, the build is incomplete, or the commit/editor version in `BUILD_INFO.txt` is wrong. |
| `Review gate` is blocked | Read the sticky PR comment. It lists missing approvals, stale approvals, changes requested, signoff and protected-path approvals. |
| Everything is blocked with `REPLACE_ME_` | The roster is not configured. Follow [`GITHUB_SETUP.md`](GITHUB_SETUP.md). |
| A docs-only PR still runs Unity | The diff contains a non-documentation path, a deletion, or an unknown extension. This is deliberate. |

## Local equivalents

```bash
python3 -m py_compile scripts/*.py tests/ci/*.py
python3 -m unittest discover -s tests/ci -t . -v
python3 scripts/validate_repository.py
python3 scripts/csharp_analysis.py
python3 scripts/unity_version.py --json
```

For Unity test and build commands, see [`TESTING.md`](TESTING.md) and
[`BUILD_AND_RELEASE.md`](BUILD_AND_RELEASE.md).
