# Approval policy

The repository has exactly three reviewers: **Stanley**, **Zian** and **Manu**.
Their GitHub logins live in [`.github/team.json`](../.github/team.json). The
checked-in values are placeholders (`REPLACE_ME_...`) until an administrator
replaces them. While any placeholder remains, the `Review gate` fails closed.

This policy is enforced by the required **`Review gate`** check, not by
CODEOWNERS. CODEOWNERS only routes review requests; it cannot express "the other
two of exactly three people" or an author signoff.

## The matrix

| Pull request author | Required approvals | Author command | Extra command for protected CI paths |
| --- | --- | --- | --- |
| Stanley | Zian **and** Manu | `/signoff <head-sha>` from Stanley | `/approve-ci <head-sha>` from Zian or Manu |
| Zian | Stanley **and** Manu | `/signoff <head-sha>` from Zian | `/approve-ci <head-sha>` from Stanley or Manu |
| Manu | Stanley **and** Zian | `/signoff <head-sha>` from Manu | `/approve-ci <head-sha>` from Stanley or Zian |
| Anyone outside the roster | Stanley **and** Zian **and** Manu | Not required | `/approve-ci <head-sha>` from any roster member |

Additional rules:

- An author can never count their own approval. GitHub also blocks self-approval
  through the UI/API; do not use a second account or a bot to work around it.
- Approvals must be on the **current head commit**. A push invalidates them.
- A `CHANGES_REQUESTED` review from any roster member blocks the merge until that
  member submits a new approval or dismisses the review.
- A later `COMMENTED` review does not erase an earlier approval, matching
  GitHub's own review-state handling.
- Draft pull requests and merge conflicts block the gate.
- Approvals from outside the roster are ignored and listed in the PR comment.
- The gate reads the roster from the repository's default branch. Changing the
  roster requires merging that change first.

## Commands are strict

A command must be the **first non-empty line** of the comment and the **only
content on that line**. Backticks, trailing words and prose before the command
are ignored.

Valid:

```text
/signoff 4f9c2a7d1e8b6c3a5f0d9e2b7c4a1f8d6e3b0c5a
```

```text
/approve-ci 4f9c2a7d1e8b6c3a5f0d9e2b7c4a1f8d6e3b0c5a
```

Invalid:

```text
I approve this, /signoff 4f9c2a7d...
```

```text
`/signoff 4f9c2a7d...`
```

The token must be at least 7 hex characters and must match the beginning of the
current head SHA. The full 40-character SHA is safest. The **latest** valid
command from the correct account wins, so a corrected comment supersedes an
earlier one. Deleting or editing a command is picked up on the next gate run.

The head SHA is shown in the pull request's **Commits** area or from:

```bash
git rev-parse HEAD
```

## Exact steps

### When Stanley authors a pull request

1. Stanley pushes the final commit and copies the head SHA.
2. Zian opens **Files changed > Review changes > Approve > Submit review**.
3. Manu does the same.
4. Stanley posts a new PR comment containing exactly:

   ```text
   /signoff <head-sha>
   ```

5. If the diff touches a protected path, Zian **or** Manu also posts:

   ```text
   /approve-ci <head-sha>
   ```

6. Confirm `Review gate` is green and `Required checks` is green.
7. Squash-merge.

### When Zian authors a pull request

1. Zian pushes the final commit and copies the head SHA.
2. Stanley approves.
3. Manu approves.
4. Zian posts exactly `/signoff <head-sha>`.
5. If the diff touches a protected path, Stanley **or** Manu posts exactly
   `/approve-ci <head-sha>`.
6. Confirm both required checks are green, then squash-merge.

### When Manu authors a pull request

1. Manu pushes the final commit and copies the head SHA.
2. Stanley approves.
3. Zian approves.
4. Manu posts exactly `/signoff <head-sha>`.
5. If the diff touches a protected path, Stanley **or** Zian posts exactly
   `/approve-ci <head-sha>`.
6. Confirm both required checks are green, then squash-merge.

### When someone outside the roster authors a pull request

1. Stanley, Zian and Manu each approve the current head commit.
2. If the diff touches a protected path, any roster member posts exactly
   `/approve-ci <head-sha>`.
3. If the pull request is from a fork, `Required checks` will fail because the
   licensed Unity jobs cannot receive secrets. Do **not** merge it directly.
   Follow the validation-branch process in
   [`CONTRIBUTING.md`](../CONTRIBUTING.md).
4. An external author does not post `/signoff`; all three approvals are the
   stronger requirement.

## Protected paths

A change to any of these paths needs the extra `/approve-ci` command:

- `.github/**`
- `scripts/**`
- `tests/ci/**`
- `Assets/Orchard/Editor/**`
- `Assets/Orchard/Tests/**`
- `ProjectSettings/**`
- `Packages/**`

The command must come from a roster member who is **not** the author. For an
external author, any roster member qualifies. This is the guard against a pull
request that weakens CI and then approves itself.

## What the gate checks

`scripts/check_approvals.py` calls the GitHub REST API for the pull request,
reviews, issue comments and changed files, then `scripts/approval_policy.py`
makes a pure decision. It verifies:

- the roster is exactly three unique logins and is fully configured,
- the author is a roster member or external,
- the required reviewer set excludes the author,
- the latest review state per reviewer,
- the review commit matches the head SHA,
- changes requested, drafts and merge conflicts,
- the author's `/signoff` and its SHA,
- the `/approve-ci` command and its SHA when protected paths changed,
- fork status and the resulting validation instructions.

The gate writes the required `Review gate` check run and updates one sticky PR
comment. A blocked decision creates a **failure** check, not a neutral one.

## Bootstrap and roster changes

There is a deliberate chicken-and-egg problem: the gate reads the roster from
the default branch, so the first pull request that adds the real logins cannot
pass a gate that still sees placeholders. The repository administrator must:

1. Have all three people manually review the bootstrap pull request.
2. Temporarily disable the `Review gate` required check (or use the ruleset's
   admin bypass) for that one merge.
3. Merge the bootstrap pull request.
4. Immediately re-enable `Review gate` and verify it runs on the next pull
   request.
5. Open a harmless test pull request and confirm that a missing approval blocks
   it, then approve it and confirm it passes.

Never leave the bypass enabled. The admin bypass is for bootstrap only.

## Branch protection settings

Recommended `main` ruleset:

- Require a pull request before merging.
- Require at least **2** approvals as a GitHub-level backstop. This is not the
  three-person policy; the gate is.
- Dismiss stale approvals when new commits are pushed.
- Require review from Code Owners (routing backstop only).
- Require conversation resolution.
- Require status checks: **`Required checks`** and **`Review gate`**.
- Require branches to be up to date before merging.
- Block force pushes and deletions.
- Restrict bypass to repository administrators.

GitHub's "Require approvals" count cannot distinguish roster members from
drive-by reviewers, cannot exclude the author from a three-person roster in the
required way, and cannot require an author signoff. That is why the custom check
is mandatory.
