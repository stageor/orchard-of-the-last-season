# GitHub setup

This guide is for a repository administrator. The workflows and policy files are
in the repository, but the GitHub-side settings, secrets and branch rules cannot
be committed. They must be applied in the repository settings.

The three reviewers are **Stanley**, **Zian** and **Manu**. Their real GitHub
logins are not guessed anywhere in this repository. Replace the
`REPLACE_ME_...` placeholders first.

## 1. Replace the roster placeholders

Edit both files and use the same three logins:

- `.github/team.json`
- `.github/CODEOWNERS`

`team.json` must contain exactly three members. `approval_policy.py` rejects a
fourth member, duplicate logins, duplicate names and missing names.

Do not add a bot or a shared account. An approval must come from a real,
authenticated roster member.

## 2. Add the Actions secrets

Open **Settings > Secrets and variables > Actions > New repository secret**.

| Secret | Value |
| --- | --- |
| `UNITY_LICENSE` | The full contents of the Unity `.ulf` licence file for the pinned editor. Paste the XML, not a path. |
| `UNITY_EMAIL` | The Unity account email used for activation. Optional with a personal `.ulf`, but recommended. |
| `UNITY_PASSWORD` | The Unity account password. Optional with a personal `.ulf`, but recommended. |
| `GITLEAKS_LICENSE` | A gitleaks-action licence key, only for organization-owned repositories. Personal repositories do not need it. |

Never commit the `.ulf`, print it in a workflow, or upload it as an artifact.
The local file `/Library/Application Support/Unity/Unity_lic.ulf` on a Mac is a
licence file and must stay outside Git.

If the Unity licence is a personal licence, one seat is enough for this
repository because CI cancels superseded pull request runs. Do not run a pull
request build and a release build at the same time on a one-seat licence.

## 3. Configure Actions

Open **Settings > Actions > General**.

- **Actions permissions:** allow GitHub Actions and reusable workflows. The
  repository pins every third-party action to a full commit SHA, so "Allow all
  actions" is acceptable. If your organization requires an allow-list, add the
  owners `actions`, `github`, `game-ci`, `gitleaks` and `softprops`.
- **Workflow permissions:** select **Read repository contents and packages
  permissions**. The workflows request `checks: write`, `issues: write`,
  `security-events: write` or `contents: write` only in the jobs that need them.
- **Allow GitHub Actions to create and approve pull requests:** leave **off**.
  Nothing in this repository needs it.
- **Fork pull request workflows from outside collaborators:** require approval
  for first-time contributors. Approving a `pull_request_target` run is safe
  because that workflow only checks out the trusted default branch. Never
  approve a fork `pull_request` run that expects repository secrets.
- **Artifact and log retention:** 14 days is the workflow default; 30 days is
  useful for release debugging. Release assets are retained permanently.

## 4. Enable security features

Open **Settings > Code security and analysis**.

- Enable **Dependabot alerts**.
- Enable **Dependabot security updates**.
- Enable **Secret scanning** and **Push protection**.
- Enable **Private vulnerability reporting** so `SECURITY.md` has a working
  channel.
- Use **CodeQL advanced setup** (the committed `security.yml` workflow), not
  default setup. Do not enable both: they can conflict over the same language.
- CodeQL for private repositories requires GitHub Code Security. If the
  repository is private and that feature is unavailable, either make the
  repository public, enable the feature, or remove the `codeql` job from
  `security.yml`. Do not mark CodeQL as a required check.

## 5. Create the `main` ruleset

Open **Settings > Rules > Rulesets > New branch ruleset**.

- **Name:** `main protection`
- **Enforcement status:** Active
- **Target branches:** add `main`
- **Bypass list:** repository administrators only. This is for the one-time
  bootstrap; remove it after the gate is live.

Enable:

- Require a pull request before merging.
- Required approvals: **2**. This is a GitHub-level backstop, not the full
  three-person policy.
- Dismiss stale pull request approvals when new commits are pushed.
- Require review from Code Owners. All three reviewers are owners; this only
  routes review, it does not enforce the roster.
- Require conversation resolution before merging.
- Require status checks to pass before merging.
  - Add **`Required checks`**.
  - Add **`Review gate`**.
  - Require branches to be up to date before merging.
- Block force pushes.
- Block deletions.

Do **not** require the individual Unity job names. The aggregate `Required
checks` is the stable contract and already fails when any mandatory job fails,
is cancelled or is skipped unexpectedly.

### Status checks do not exist until the first run

GitHub only offers check names that have run at least once. If the names are not
listed yet:

1. Push this branch and open a draft pull request.
2. Let `CI` and `Review gate` run once.
3. Return to the ruleset and add the two checks.

The `Review gate` will be red while the roster is still a placeholder. That is
the intended fail-closed behaviour.

## 6. Bootstrap the approval gate

The gate reads `.github/team.json` from the default branch. A pull request that
introduces the real logins therefore cannot pass a gate that still sees the old
placeholders. Use this one-time sequence:

1. In the bootstrap pull request, replace all three placeholders with the real
   logins and update `CODEOWNERS` in the same commit.
2. Have Stanley, Zian and Manu manually review the bootstrap pull request.
3. Temporarily disable the `Review gate` required check, or use the ruleset's
   administrator bypass, for this one merge.
4. Merge the bootstrap pull request.
5. Immediately re-enable `Review gate` and remove the bypass.
6. Open a harmless test pull request and verify:
   - with no approvals, `Review gate` is **BLOCKED**;
   - with only one approval, it is still blocked;
   - with the other two approvals and the author's `/signoff <head-sha>`, it
     passes;
   - a new push turns it red again and requires fresh approvals and a new
     signoff;
   - a protected-path change without `/approve-ci` is blocked.
7. Close the test pull request without merging.

Never leave the bypass or the disabled check in place.

## 7. Verify the required checks

On a real pull request, the **Checks** area should show:

- `Required checks`
- `Review gate`
- `Repository health`
- `C# contract analysis`
- `Unity EditMode tests`
- `Unity PlayMode tests`
- `Build Windows x64`
- `Build WebGL`

The reusable Unity jobs may appear under a combined reusable-workflow heading.
Only `Required checks` and `Review gate` are required by the ruleset.

A documentation-only pull request should show repository health and C# analysis
as successful, the four Unity jobs as skipped, and `Required checks` as
successful with an "allowed (docs-only)" note.

A non-documentation pull request must show real Unity and build jobs. A
cancelled, failed or unexpectedly skipped job must leave `Required checks` red.

## 8. Release environment (recommended)

For an extra release control, create **Settings > Environments > New
environment** named `release`:

- Add Stanley, Zian and Manu as required reviewers.
- Restrict deployment branches and tags to `v*` tags.
- Do not allow administrators to bypass without an audit trail.

If you want the workflow to wait for that environment, add
`environment: release` to the `publish` job in
`.github/workflows/release.yml`. The committed workflow does not require this,
so releases work without the environment; enabling it adds a human approval
before publishing.

## 9. What is already enforced by the repository

These do not require GitHub settings:

- Action pins are full commit SHAs.
- Workflows use least-privilege permissions.
- The review gate never checks out PR head code.
- The gate ignores self-approvals and non-roster approvals.
- Approvals and commands are tied to the head SHA.
- Protected CI paths need a non-author `/approve-ci`.
- `Required checks` fails on failed, cancelled or unexpected skipped jobs.
- WebGL compression is Disabled in project settings and re-checked in the
  artifact.
- Builds record the exact editor version and commit, and releases publish
  SHA-256 checksums.
- Dependabot, dependency review, CodeQL and gitleaks are configured.

## 10. Current application status

The repository-side files are in place on the `test/ci-engineering-standards`
branch. The GitHub-side settings above have **not** been applied from this
machine: there is no authenticated `gh` CLI session and no repository
administrator access in this environment. An administrator must apply them
before the gate can block real merges.
