# Security Policy

## Supported versions

Security and CI fixes are applied to the `main` branch and to the latest tagged
release. Older tags are not maintained.

## Reporting a vulnerability

Do **not** open a public issue, pull request or discussion for a vulnerability.

Use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Choose **Advisories** and **Report a vulnerability**.
3. Include the affected commit, reproduction steps and impact.

If private reporting is not enabled, contact a repository administrator
privately and ask them to enable it. Do not send secrets, Unity licence files or
personal data through a public channel.

You should receive an acknowledgement within a few days. Please allow time for a
fix and a coordinated disclosure before publishing details.

## Secrets used by this repository

| Secret | Required | Purpose |
| --- | --- | --- |
| `UNITY_LICENSE` | Yes for licensed jobs | Contents of the Unity `.ulf` licence file. Never commit it. |
| `UNITY_EMAIL` | Optional | Unity account email for licence activation. |
| `UNITY_PASSWORD` | Optional | Unity account password for licence activation. |
| `GITLEAKS_LICENSE` | Only for organization-owned repositories | gitleaks-action licence key. Personal repositories do not need it. |
| `GITHUB_TOKEN` | Automatic | Scoped per job by the workflow `permissions` block. |

Rules:

- Store secrets only in **Settings > Secrets and variables > Actions**.
- Never print a secret, echo it into a log, or write it to an artifact.
- Never commit a `.ulf`, `.pem`, `.key`, `.p12`, `.pfx`, `.env` or keystore file.
- Rotate a secret immediately if it is exposed. Removing a commit does not
  remove the secret from Git history or from forks.
- Fork pull requests never receive these secrets. Do not weaken that boundary
  to make a fork build run; use the validation-branch process in
  `CONTRIBUTING.md`.

## Workflow security

- Every third-party action is pinned to a full 40-character commit SHA.
- Workflows default to `contents: read`; write permissions are granted only to
  the job that needs them.
- `review-gate.yml` runs on `pull_request_target` and checks out **only** the
  trusted default branch. It must never check out the pull request head.
- Pull request code is never run with repository secrets. The licensed Unity
  jobs use the normal `pull_request` event for same-repository branches only.
- `GITHUB_TOKEN` is not persisted by `actions/checkout`.
- Release builds re-verify the exact commit and publish checksums.
- CodeQL analyses Python and GitHub Actions. C# is covered by the real Unity
  compile and `scripts/csharp_analysis.py`.
- Dependabot proposes pinned updates for GitHub Actions and Python packages.
- gitleaks scans the full history on pushes, pull requests and a weekly schedule.

## If a secret is exposed

1. Revoke and rotate the credential at its source.
2. Remove the secret from the repository settings and add the replacement.
3. Open a private security advisory.
4. If a Unity licence was exposed, request a new licence from Unity and
   deactivate the old one.
5. Audit workflow runs and release assets for misuse.

Do not attempt to rewrite public Git history without coordinating with the
repository administrators and all contributors.
