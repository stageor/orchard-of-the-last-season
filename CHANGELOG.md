# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic version tags (`vMAJOR.MINOR.PATCH`).

## [Unreleased]

### Added

- Real Unity EditMode coverage for A* pathfinding, Shambler utility AI, Pip's
  behaviour tree, Thistle's finite-state machine, procedural map generation,
  gameplay rules and deterministic regression sweeps.
- A real PlayMode bootstrap smoke test that starts the game from an empty scene,
  builds the map and cameras, starts night one and spawns the first wave.
- Reusable GameCI EditMode, PlayMode, Windows x64 and WebGL workflows that derive
  the exact editor version from `ProjectSettings/ProjectVersion.txt`.
- Repository-health, C# contract, dependency-review, CodeQL, gitleaks and nightly
  regression workflows.
- A three-person `Review gate` check with `/signoff` and `/approve-ci` commands.
- A single `Required checks` gate that fails on failed, cancelled or unexpectedly
  skipped mandatory jobs.
- Build verification for real PE/WebAssembly payloads, the exact commit, the
  exact Unity version and disabled WebGL compression.
- Release automation for `v*` tags with re-verification, packaged downloads and
  SHA-256 checksums.
- Contributor, security, CI, testing, approval, release and GitHub-setup guides.
- A dependency-free CI tooling suite under `tests/ci/`.

### Changed

- Added a minimal empty `Bootstrap.unity` scene and registered it in
  `EditorBuildSettings.asset` so a player build has a valid entry scene. The
  runtime still self-bootstraps; no scene wiring is required.
- Added assembly definitions for runtime, editor, EditMode and PlayMode code.
- Added `U.SetSeed` / `U.ResetRandom` for deterministic tests and regression
  runs. The shipped game keeps its unseeded default.
- Pinned `com.unity.test-framework` 1.4.6 and `com.unity.ext.nunit` 2.0.3.
- Set WebGL compression to Disabled and decompression fallback off, matching the
  static-hosting contract.
- Replaced the minimal `.gitignore`, added `.gitattributes`, and removed tracked
  `.DS_Store` files.

### Fixed

- `OrchardBuild` now writes `BUILD_INFO.txt` into the build directory instead of
  inside the Windows executable path.

### Security

- Added Dependabot, dependency review, CodeQL, gitleaks, least-privilege tokens,
  SHA-pinned actions and a secret-scanning configuration.

### Notes

- No gameplay, balance, control, rendering or asset behaviour was changed.
- Pre-existing contract deviations are documented in
  `.github/csharp-baseline.json`; new violations fail CI.
- No tagged release has been published from this branch yet.

## [1.0] - 2026-11-17

Initial playable project state before the CI and test work. This entry records
the existing baseline; it is not a published GitHub Release.
