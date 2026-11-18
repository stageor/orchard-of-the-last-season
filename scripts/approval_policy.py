#!/usr/bin/env python3
"""Pure approval policy for the Orchard three-person review gate.

No network calls live in this module. ``check_approvals.py`` fetches GitHub data and
passes plain dictionaries here, which keeps the policy deterministic and unit-testable.

Policy
------
* The roster is exactly three people, configured in ``.github/team.json``.
* A PR authored by a roster member needs the other two members' approvals and an
  authenticated ``/signoff <head-sha>`` comment from the author.
* Any other PR needs all three members' approvals.
* A member can never count their own approval, even if the API returns one.
* Approvals must be on the current head commit; a push invalidates them.
* Changes to protected CI paths also need ``/approve-ci <head-sha>`` from a roster
  member who is not the PR author.
* Placeholder logins fail closed until a repository administrator replaces them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
PLACEHOLDER_PREFIX = "REPLACE_ME_"
REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


class TeamConfigError(ValueError):
    pass


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _login(user: dict[str, Any] | str | None) -> str:
    if isinstance(user, str):
        return user
    if isinstance(user, dict):
        return str(user.get("login") or "")
    return ""


def is_placeholder(login: str) -> bool:
    return login.startswith(PLACEHOLDER_PREFIX)


def load_team(team: dict[str, Any]) -> dict[str, Any]:
    """Validate the roster and return a normalised copy."""
    if not isinstance(team, dict):
        raise TeamConfigError("team.json must be an object")
    raw_members = team.get("members")
    if not isinstance(raw_members, list) or len(raw_members) != 3:
        raise TeamConfigError("team.json must list exactly three members")
    members: list[dict[str, str]] = []
    seen_logins: set[str] = set()
    seen_names: set[str] = set()
    for index, member in enumerate(raw_members):
        if not isinstance(member, dict):
            raise TeamConfigError(f"member {index} must be an object")
        name = str(member.get("name") or "").strip()
        login = str(member.get("login") or "").strip()
        if not name:
            raise TeamConfigError(f"member {index} has no name")
        if not login:
            raise TeamConfigError(f"member {index} has no login")
        if not (LOGIN_RE.match(login) or is_placeholder(login)):
            raise TeamConfigError(f"member {index} has an invalid GitHub login: {login!r}")
        key = login.lower()
        if key in seen_logins:
            raise TeamConfigError(f"duplicate GitHub login: {login}")
        if name.lower() in seen_names:
            raise TeamConfigError(f"duplicate member name: {name}")
        seen_logins.add(key)
        seen_names.add(name.lower())
        members.append({"name": name, "login": login})

    required = team.get("requiredApprovals") or {}
    member_required = required.get("memberAuthored", 2)
    external_required = required.get("externalAuthored", 3)
    if member_required != 2 or external_required != 3:
        raise TeamConfigError("requiredApprovals must be memberAuthored=2 and externalAuthored=3")

    commands = team.get("commands") or {}
    signoff = str(commands.get("signoff") or "/signoff")
    protected_ci = str(commands.get("protectedCi") or "/approve-ci")

    return {
        "members": members,
        "logins": [m["login"] for m in members],
        "memberLoginsLower": {m["login"].lower() for m in members},
        "requiredApprovals": {"memberAuthored": 2, "externalAuthored": 3},
        "commands": {"signoff": signoff, "protectedCi": protected_ci},
        "configured": not any(is_placeholder(m["login"]) for m in members),
    }


def parse_command(body: str | None, command: str) -> str | None:
    """Return the token from a strict single-line command comment.

    The command must be the first non-empty line and the only content on it. This
    avoids counting quoted policy text or prose that merely mentions the command.
    """
    if not body:
        return None
    lines = [line.strip() for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    first = next((line for line in lines if line), "")
    if not first.startswith(command):
        return None
    rest = first[len(command):]
    if not rest.startswith(" ") and not rest.startswith("\t"):
        return None
    token = rest.strip()
    if not token or " " in token or "\t" in token or "`" in token:
        return None
    return token


def sha_matches(token: str, head_sha: str) -> bool:
    if not token or not HEX_RE.match(token):
        return False
    return head_sha.lower().startswith(token.lower())


def _latest_comment(
    comments: Iterable[dict[str, Any]],
    command: str,
    allowed_logins: set[str] | None = None,
    author: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for comment in comments:
        if comment.get("deleted_at"):
            continue
        login = _login(comment.get("user"))
        if author is not None and login.lower() != author.lower():
            continue
        if allowed_logins is not None and login.lower() not in allowed_logins:
            ignored.append(comment)
            continue
        if parse_command(comment.get("body"), command) is not None:
            candidates.append(comment)
    candidates.sort(key=lambda c: (_parse_time(c.get("updated_at") or c.get("created_at")), int(c.get("id") or 0)))
    return (candidates[-1] if candidates else None), ignored


def latest_reviews(reviews: Iterable[dict[str, Any]], head_sha: str, require_at_head: bool = True) -> dict[str, dict[str, Any]]:
    """Return the latest submitted review state per login.

    COMMENTED reviews do not erase an earlier approval or change request, matching
    GitHub's own review-state handling. PENDING reviews are not submitted.
    """
    latest: dict[str, dict[str, Any]] = {}
    for review in reviews:
        state = str(review.get("state") or "").upper()
        if state not in REVIEW_STATES:
            continue
        login = _login(review.get("user"))
        if not login:
            continue
        previous = latest.get(login.lower())
        if previous is None or _parse_time(review.get("submitted_at")) >= _parse_time(previous.get("submitted_at")):
            latest[login.lower()] = review
    return latest


def pr_author(pr: dict[str, Any]) -> str:
    return _login(pr.get("user"))


def is_fork(pr: dict[str, Any]) -> bool:
    head_repo = (pr.get("head") or {}).get("repo") or {}
    base_repo = (pr.get("base") or {}).get("repo") or {}
    if head_repo.get("fork") is True:
        return True
    head_name = str(head_repo.get("full_name") or "")
    base_name = str(base_repo.get("full_name") or "")
    return bool(head_name and base_name and head_name.lower() != base_name.lower())


def changed_paths(files: Iterable[Any]) -> list[str]:
    paths: list[str] = []
    for item in files:
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, dict) and item.get("filename"):
            paths.append(str(item["filename"]))
    return paths


def is_protected(path: str, patterns: Iterable[str]) -> bool:
    import fnmatch

    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return True
        if pattern.endswith("/**") and normalized.startswith(pattern[:-2] + "/"):
            return True
    return False


@dataclass
class Decision:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    author: str = ""
    author_is_member: bool = False
    fork: bool = False
    draft: bool = False
    merged: bool = False
    closed: bool = False
    team_configured: bool = True
    required_approvals: int = 0
    required_reviewers: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    changes_requested: list[str] = field(default_factory=list)
    stale_approvals: list[str] = field(default_factory=list)
    unauthorized_approvals: list[str] = field(default_factory=list)
    signoff_ok: bool = False
    signoff_author: str = ""
    signoff_sha: str = ""
    protected_files: list[str] = field(default_factory=list)
    ci_approval_ok: bool = False
    ci_approval_author: str = ""
    ci_approval_sha: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "author": self.author,
            "authorIsMember": self.author_is_member,
            "fork": self.fork,
            "draft": self.draft,
            "merged": self.merged,
            "closed": self.closed,
            "teamConfigured": self.team_configured,
            "requiredApprovals": self.required_approvals,
            "requiredReviewers": self.required_reviewers,
            "approvals": self.approvals,
            "missing": self.missing,
            "changesRequested": self.changes_requested,
            "staleApprovals": self.stale_approvals,
            "unauthorizedApprovals": self.unauthorized_approvals,
            "signoffOk": self.signoff_ok,
            "signoffAuthor": self.signoff_author,
            "signoffSha": self.signoff_sha,
            "protectedFiles": self.protected_files,
            "ciApprovalOk": self.ci_approval_ok,
            "ciApprovalAuthor": self.ci_approval_author,
            "ciApprovalSha": self.ci_approval_sha,
        }

    def summary(self) -> str:
        if self.ok:
            return "All approval requirements are satisfied."
        return "; ".join(self.reasons) if self.reasons else "Approval requirements are not satisfied."

    def markdown(self) -> str:
        status = "PASS" if self.ok else "BLOCKED"
        lines = [f"### Review gate: {status}", ""]
        if self.merged:
            lines.append("This pull request is already merged; the gate is informational.")
        elif self.closed:
            lines.append("This pull request is closed without merging; the gate is informational.")
        if self.draft:
            lines.append("- Draft pull request: mark it ready for review before merging.")
        if not self.team_configured:
            lines.append("- **Team roster is not configured.** Replace every `REPLACE_ME_` login in `.github/team.json` and `.github/CODEOWNERS`.")
        lines.append(f"- Author: `{self.author or 'unknown'}` ({'roster member' if self.author_is_member else 'external contributor'})")
        lines.append(f"- Fork PR: {'yes' if self.fork else 'no'}")
        lines.append(f"- Required approvals: {self.required_approvals}")
        if self.required_reviewers:
            lines.append("- Required reviewers: " + ", ".join(f"`{x}`" for x in self.required_reviewers))
        if self.approvals:
            lines.append("- Current approvals: " + ", ".join(f"`{x}`" for x in self.approvals))
        if self.missing:
            lines.append("- Missing approvals: " + ", ".join(f"`{x}`" for x in self.missing))
        if self.changes_requested:
            lines.append("- Changes requested by: " + ", ".join(f"`{x}`" for x in self.changes_requested))
        if self.stale_approvals:
            lines.append("- Approvals on older commits (must be re-submitted): " + ", ".join(f"`{x}`" for x in self.stale_approvals))
        if self.unauthorized_approvals:
            lines.append("- Approvals outside the roster (ignored): " + ", ".join(f"`{x}`" for x in self.unauthorized_approvals))
        if self.author_is_member:
            signoff = "present" if self.signoff_ok else "missing"
            lines.append(f"- Author signoff: {signoff}" + (f" by `{self.signoff_author}` for `{self.signoff_sha[:12]}`" if self.signoff_ok else ""))
        if self.protected_files:
            ci = "present" if self.ci_approval_ok else "missing"
            lines.append(f"- Protected CI-path approval: {ci}" + (f" by `{self.ci_approval_author}`" if self.ci_approval_ok else ""))
            lines.append("- Protected files: " + ", ".join(f"`{x}`" for x in self.protected_files[:10]))
            if len(self.protected_files) > 10:
                lines.append(f"- ...and {len(self.protected_files) - 10} more protected files")
        if self.reasons:
            lines.extend(["", "**Blocking reasons**", ""])
            lines.extend(f"- {reason}" for reason in self.reasons)
        if self.warnings:
            lines.extend(["", "**Warnings**", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.append("")
        lines.append("Commands must be posted by the authenticated GitHub account and repeated after every push.")
        return "\n".join(lines)


def evaluate(
    pr: dict[str, Any],
    reviews: Iterable[dict[str, Any]],
    comments: Iterable[dict[str, Any]],
    files: Iterable[Any],
    team: dict[str, Any],
    head_sha: str,
    protected_patterns: Iterable[str] = (),
    require_at_head: bool = True,
) -> Decision:
    try:
        config = load_team(team)
    except TeamConfigError as exc:
        return Decision(ok=False, reasons=[f"team.json is invalid: {exc}"], team_configured=False)

    author = pr_author(pr)
    members = config["members"]
    member_logins = {m["login"].lower() for m in members}
    author_is_member = author.lower() in member_logins
    fork = is_fork(pr)
    draft = bool(pr.get("draft"))
    merged = bool(pr.get("merged"))
    closed = str(pr.get("state") or "open").lower() == "closed"
    paths = changed_paths(files)
    protected_files = sorted({p for p in paths if is_protected(p, protected_patterns)})

    decision = Decision(
        ok=True,
        author=author,
        author_is_member=author_is_member,
        fork=fork,
        draft=draft,
        merged=merged,
        closed=closed,
        team_configured=config["configured"],
        protected_files=protected_files,
    )

    if merged:
        decision.warnings.append("Pull request is already merged.")
        return decision
    if closed:
        decision.warnings.append("Pull request is closed without merging.")
        return decision

    if not config["configured"]:
        decision.ok = False
        decision.reasons.append(
            "Team roster is not configured. Replace REPLACE_ME_ logins in .github/team.json and .github/CODEOWNERS."
        )
        return decision

    if draft:
        decision.ok = False
        decision.reasons.append("Pull request is a draft; mark it ready for review.")

    if str(pr.get("mergeable_state") or "").lower() == "dirty":
        decision.ok = False
        decision.reasons.append("Pull request has merge conflicts with the base branch.")

    required_logins = [m["login"] for m in members if not (author_is_member and m["login"].lower() == author.lower())]
    decision.required_approvals = len(required_logins)
    decision.required_reviewers = required_logins

    latest = latest_reviews(reviews, head_sha, require_at_head)
    approved: list[str] = []
    stale: list[str] = []
    changes_requested: list[str] = []
    unauthorized: list[str] = []
    for key, review in latest.items():
        login = _login(review.get("user"))
        state = str(review.get("state") or "").upper()
        if key not in member_logins:
            if state == "APPROVED":
                unauthorized.append(login)
            continue
        if author_is_member and key == author.lower():
            decision.warnings.append(f"Ignoring self-review by the author `{login}`.")
            continue
        if state == "APPROVED":
            if require_at_head and str(review.get("commit_id") or "").lower() != head_sha.lower():
                stale.append(login)
            else:
                approved.append(login)
        elif state == "CHANGES_REQUESTED":
            changes_requested.append(login)

    approved.sort(key=str.lower)
    decision.approvals = approved
    decision.missing = [login for login in required_logins if login.lower() not in {a.lower() for a in approved}]
    decision.changes_requested = changes_requested
    decision.stale_approvals = sorted(stale, key=str.lower)
    decision.unauthorized_approvals = sorted(unauthorized, key=str.lower)

    if decision.missing:
        decision.ok = False
        decision.reasons.append("Missing required approvals from: " + ", ".join(decision.missing))
    if changes_requested:
        decision.ok = False
        decision.reasons.append("Changes requested by: " + ", ".join(changes_requested))
    if stale:
        decision.ok = False
        decision.reasons.append(
            "Approvals for an older commit by: " + ", ".join(decision.stale_approvals) +
            ". Re-approve the current head commit."
        )

    signoff_command = config["commands"]["signoff"]
    if author_is_member:
        signoff_comment, _ = _latest_comment(comments, signoff_command, author=author)
        if signoff_comment is None:
            decision.ok = False
            decision.reasons.append(f"Author signoff `{signoff_command} {head_sha}` is missing.")
        else:
            token = parse_command(signoff_comment.get("body"), signoff_command) or ""
            decision.signoff_author = _login(signoff_comment.get("user"))
            decision.signoff_sha = token
            if not sha_matches(token, head_sha):
                decision.ok = False
                decision.reasons.append(
                    f"Author signoff is for `{token}`, but the current head commit is `{head_sha}`. "
                    f"Post `{signoff_command} {head_sha}` again."
                )
            else:
                decision.signoff_ok = True

    if protected_files:
        ci_command = config["commands"]["protectedCi"]
        allowed = member_logins - ({author.lower()} if author_is_member else set())
        ci_comment, _ = _latest_comment(comments, ci_command, allowed_logins=allowed)
        if ci_comment is None:
            decision.ok = False
            decision.reasons.append(
                f"Protected CI paths changed. A non-author roster member must post `{ci_command} {head_sha}`."
            )
        else:
            token = parse_command(ci_comment.get("body"), ci_command) or ""
            decision.ci_approval_author = _login(ci_comment.get("user"))
            decision.ci_approval_sha = token
            if not sha_matches(token, head_sha):
                decision.ok = False
                decision.reasons.append(
                    f"Protected CI approval is for `{token}`, but the current head commit is `{head_sha}`. "
                    f"Post `{ci_command} {head_sha}` again."
                )
            else:
                decision.ci_approval_ok = True

    if fork:
        decision.warnings.append(
            "Fork PR: licensed Unity jobs cannot run with repository secrets. A maintainer must copy the commits "
            "to a same-repository branch and open a validation PR before this can merge."
        )

    return decision
