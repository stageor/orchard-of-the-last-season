## Summary

<!-- What changed, and why? Keep gameplay changes and CI changes separate. -->

## Phase / AI subsystem

<!-- e.g. Phase 6 — Behaviour tree, or "CI only". -->

## Validation

- [ ] `python3 -m unittest discover -s tests/ci -t .` passes locally.
- [ ] `python3 scripts/validate_repository.py` passes locally.
- [ ] `python3 scripts/csharp_analysis.py` passes locally.
- [ ] Unity EditMode tests pass (or this is a documentation-only change).
- [ ] Unity PlayMode tests pass (or this is a documentation-only change).
- [ ] Windows x64 build succeeds (or this is a documentation-only change).
- [ ] WebGL build succeeds with compression **Disabled** (or this is a documentation-only change).

Paste the failed test names or build errors, if any:

```text

```

## Contract review

- [ ] No prefabs, scenes, materials, animators or imported sprites were added.
- [ ] No new mouse, controller, function-key or number-key input was added.
- [ ] Camera lock and WebGL compression settings are unchanged.
- [ ] No binaries, credentials, licence files or build output are committed.

## Review checklist

The three-person policy is enforced by the required **Review gate** check, not by this template.

- Member-authored PR: the other two roster members approve **and** the author posts
  `/signoff <head-sha>`.
- External or fork-authored PR: all three roster members approve.
- Protected CI paths (`.github/`, `scripts/`, `tests/ci/`, `ProjectSettings/`,
  `Packages/`, `Assets/Orchard/Editor/`, `Assets/Orchard/Tests/`) also need
  `/approve-ci <head-sha>` from a non-author roster member.
- Every push invalidates approvals and command comments; repeat them on the new head commit.

Commands must be posted by the authenticated GitHub account, on their own line:

```text
/signoff <head-sha>
/approve-ci <head-sha>
```
