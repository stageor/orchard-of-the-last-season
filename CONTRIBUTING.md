# Contributing to Orchard of the Last Season

This repository is a zero-asset Unity project with a strict gameplay and CI
contract. Read `AGENTS.md` before changing anything. The short version:

- No prefabs, scenes, materials, animators or imported sprites. Visuals are
  generated at runtime from `Texture2D` and `Sprite.Create`.
- The game boots from any empty scene through
  `[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]`.
- Keyboard-only input, a fixed straight-down orthographic board camera, and
  WebGL compression **Disabled**.
- All runtime scripts live under `Assets/Scripts/` (in this repository the
  actual folder is `Assets/Orchard/Scripts/`) and compile with zero errors.
- Do not change gameplay, balance, controls, rendering or assets in a CI-only
  change. Keep those pull requests separate.

## Local requirements

| Tool | Version |
| --- | --- |
| Unity editor | Exactly the version in `ProjectSettings/ProjectVersion.txt` for CI work. A newer Unity 6 editor may open the project locally, but CI validates the pinned editor. |
| Python | 3.11 or newer (CI uses 3.12) |
| Git | Any current version |

Install the Python CI dependencies:

```bash
python3 -m pip install -r scripts/requirements-ci.txt
```

Do not install or use Kestra. The review workflow is modelled on GitHub pull
request practice, not on Kestra itself.

## Before opening a pull request

Run the same checks CI runs:

```bash
python3 -m py_compile scripts/*.py tests/ci/*.py
python3 -m unittest discover -s tests/ci -t . -v
python3 scripts/validate_repository.py
python3 scripts/csharp_analysis.py
```

Run the Unity tests from **Window > General > Test Runner**:

- EditMode: at least 120 discovered tests must pass.
- PlayMode: the bootstrap smoke test must pass.

Build both players from **Orchard > CI** or with the batch commands in
[`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md).

Do not commit `Library/`, `Temp/`, `Logs/`, `Build/`, `TestResults/`,
`artifacts/`, `.DS_Store`, `.csproj`, `.sln`, Unity licence files, build output
or secrets. `.gitignore` already covers them.

## Branch and commit style

- Branch from `main`: `feat/<short-name>`, `fix/<short-name>`,
  `test/<short-name>` or `docs/<short-name>`.
- Keep commits phase-by-phase and readable, for example
  `test(ai): add deterministic A* and utility coverage`.
- Do not rewrite or force-push `main`.
- Do not push directly to `main`. Every change goes through a pull request.

## Pull request process

1. Open the pull request against `main` and fill in the template.
2. Wait for `Required checks` to finish. It aggregates repository health, C#
   contract analysis, EditMode, PlayMode, Windows x64 and WebGL.
3. Ask the other roster members to review. The exact policy is in
   [`docs/APPROVAL_POLICY.md`](docs/APPROVAL_POLICY.md).
4. If you authored the pull request, post your signoff on its own line using the
   **current head commit SHA**:

   ```text
   /signoff <head-sha>
   ```

5. If the pull request changes a protected CI path, a non-author roster member
   must also post:

   ```text
   /approve-ci <head-sha>
   ```

6. Every push creates a new head SHA and invalidates both approvals and command
   comments. Repeat the approvals and commands after the final push.
7. Squash-merge only when `Required checks` and `Review gate` are green. Never
   bypass a failing required check, and never fake an approval.

Protected paths are `.github/**`, `scripts/**`, `tests/ci/**`,
`Assets/Orchard/Editor/**`, `Assets/Orchard/Tests/**`, `ProjectSettings/**` and
`Packages/**`.

## Fork and external contributions

GitHub does not give fork pull requests the repository's Unity licence secrets.
The licensed EditMode, PlayMode and build jobs are therefore skipped, and
`Required checks` fails with instructions. A maintainer must:

1. Record all three roster approvals on the external pull request.
2. Copy the exact commits to a same-repository branch without editing them.
3. Open a validation pull request from that branch and run the full CI.
4. Confirm the tree hash matches the external contribution.
5. Merge the validated pull request and close the external one with credit.

Never paste a Unity licence, token or password into an issue, pull request,
commit or log.

## Documentation and generated files

- Update `CHANGELOG.md` for user-visible or engineering changes.
- Update the relevant guide under `docs/` when a workflow, secret, approval rule
  or build command changes.
- Unity `.meta` files are required for every asset and folder. Do not delete or
  hand-edit a GUID unless you are intentionally replacing the asset.
- The repository validator checks `.meta` coverage, duplicate GUIDs, scene
  wiring, package pins, WebGL compression, workflow pins, docs links and
  tracked-file hygiene.

## Current known deviations

The project predates this contract and keeps the following behaviour to avoid
changing gameplay:

- `KeyCode.F` is the existing catch key and `KeyCode.KeypadEnter` is accepted.
- `OnGUI` still forwards mouse events to the legacy UI.
- Runtime sprite bytes live under `Assets/Resources/OrchardSprites/`.
- The production namespace is `Orchard`, while `AGENTS.md` says
  `OrchardOfTheLastSeason`.

These are recorded with reasons in `.github/csharp-baseline.json`. New
violations fail CI. Do not remove a baseline entry without fixing the code, and
do not add a new entry to silence a new violation.
