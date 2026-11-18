#!/usr/bin/env python3
"""Create the required ``Review gate`` check run for a pull request.

Security notes
--------------
* This workflow is triggered by ``pull_request_target`` / ``pull_request_review`` /
  ``issue_comment``. It must check out only the base branch, never the PR head.
* The script only reads PR metadata, reviews, comments and file names. It never
  executes code from the pull request.
* It fails closed when the roster is not configured or the token cannot create
  the required check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # package import for tests
    from .approval_policy import Decision, evaluate, load_team
    from .detect_changes import PROTECTED_PATTERNS
except ImportError:  # direct execution from scripts/
    from approval_policy import Decision, evaluate, load_team  # type: ignore
    from detect_changes import PROTECTED_PATTERNS  # type: ignore

CHECK_NAME = "Review gate"
COMMENT_MARKER = "<!-- orchard-review-gate -->"
USER_AGENT = "orchard-review-gate/1.0"
API_VERSION = "2022-11-28"


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str, url: str = ""):
        self.status = status
        self.url = url
        super().__init__(f"GitHub API {status} for {url}: {message}")


class GitHubClient:
    def __init__(self, token: str, repository: str, api_url: str = "https://api.github.com"):
        self.token = token
        self.repository = repository
        self.api_url = api_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else self.api_url + path
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", "Bearer " + self.token)
        request.add_header("X-GitHub-Api-Version", API_VERSION)
        request.add_header("User-Agent", USER_AGENT)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                if not body:
                    return None
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                message = json.loads(raw).get("message", raw)
            except json.JSONDecodeError:
                message = raw
            raise GitHubError(exc.code, message, url) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(0, str(exc.reason), url) from exc

    def paginate(self, path: str, limit: int = 50) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        results: list[dict[str, Any]] = []
        for page in range(1, limit + 1):
            chunk = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(chunk, list):
                raise GitHubError(0, f"expected a list from {path}", path)
            results.extend(chunk)
            if len(chunk) < 100:
                break
        return results

    def pull_request(self, number: int) -> dict[str, Any]:
        return self.request("GET", f"/repos/{self.repository}/pulls/{number}")

    def reviews(self, number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{self.repository}/pulls/{number}/reviews")

    def comments(self, number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{self.repository}/issues/{number}/comments")

    def files(self, number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{self.repository}/pulls/{number}/files")

    def upsert_comment(self, number: int, body: str) -> None:
        comments = self.paginate(f"/repos/{self.repository}/issues/{number}/comments")
        existing = None
        for comment in comments:
            if COMMENT_MARKER in str(comment.get("body") or ""):
                existing = comment
                break
        if existing is not None:
            self.request("PATCH", f"/repos/{self.repository}/issues/comments/{existing['id']}", {"body": body})
        else:
            self.request("POST", f"/repos/{self.repository}/issues/{number}/comments", {"body": body})

    def create_check(self, head_sha: str, conclusion: str, title: str, summary: str, text: str) -> None:
        payload = {
            "name": CHECK_NAME,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "output": {
                "title": title[:255],
                "summary": summary[:65535],
                "text": text[:65535],
            },
        }
        self.request("POST", f"/repos/{self.repository}/check-runs", payload)


def read_event(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def should_run(event_name: str, event: dict[str, Any]) -> bool:
    if event_name == "issue_comment":
        issue = event.get("issue") or {}
        return issue.get("pull_request") is not None
    if event_name in {"pull_request_target", "pull_request_review", "pull_request"}:
        return "pull_request" in event
    return False


def resolve_pr_number(event_name: str, event: dict[str, Any], explicit: int | None = None) -> int | None:
    if explicit:
        return explicit
    if event_name == "issue_comment":
        issue = event.get("issue") or {}
        if issue.get("pull_request") is not None:
            return int(issue.get("number") or 0) or None
        return None
    pull = event.get("pull_request") or {}
    if pull:
        return int(pull.get("number") or 0) or int(event.get("number") or 0) or None
    return int(event.get("number") or 0) or None


def read_team(path: str | Path) -> tuple[dict[str, Any], str | None]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"Team roster file not found: {path}"
    except OSError as exc:
        return {}, f"Could not read team roster: {exc}"
    except json.JSONDecodeError as exc:
        return {}, f"Team roster is not valid JSON: {exc}"
    try:
        load_team(raw)
    except Exception:
        return raw, None
    return raw, None


def comment_body(decision: Decision, head_sha: str) -> str:
    return (
        f"{COMMENT_MARKER}\n"
        f"## Orchard review gate\n\n"
        f"Head commit: `{head_sha}`\n\n"
        f"{decision.markdown()}\n"
        f"---\n"
        f"Required checks: `Required checks` and `Review gate`. "
        f"Approvals and command comments are invalidated by a new push.\n"
    )


def run(args: argparse.Namespace) -> int:
    event = read_event(args.event_path)
    event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    if not should_run(event_name, event) and not args.pr:
        print(f"not a pull request event ({event_name}); nothing to do")
        return 0

    number = resolve_pr_number(event_name, event, args.pr)
    if not number:
        print("error: could not resolve the pull request number", file=sys.stderr)
        return 2

    repository = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        print("error: --repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 2
    token = args.token or os.environ.get("GITHUB_TOKEN", "")

    team, team_error = read_team(args.team_file)
    if team_error:
        decision = Decision(ok=False, reasons=[team_error], team_configured=False)
        head_sha = args.head_sha or ""
    else:
        if not token:
            print("error: --token or GITHUB_TOKEN is required", file=sys.stderr)
            return 2
        client = GitHubClient(token, repository, args.api_url)
        try:
            pull = client.pull_request(number)
            head_sha = args.head_sha or str((pull.get("head") or {}).get("sha") or "")
            if not head_sha:
                print("error: pull request has no head SHA", file=sys.stderr)
                return 2
            decision = evaluate(
                pull,
                client.reviews(number),
                client.comments(number),
                client.files(number),
                team,
                head_sha,
                PROTECTED_PATTERNS,
                require_at_head=not args.allow_stale_approvals,
            )
        except GitHubError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    output = {
        "pr": number,
        "headSha": head_sha,
        "checkName": CHECK_NAME,
        **decision.to_dict(),
    }
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    markdown = decision.markdown()
    print(json.dumps(output, indent=2))
    print(markdown)
    if args.github_summary:
        with open(args.github_summary, "a", encoding="utf-8") as summary:
            summary.write(f"## {CHECK_NAME}\n\n{markdown}\n")

    if args.dry_run or not token:
        return 0 if decision.ok or args.allow_blocked else 1

    conclusion = "success" if decision.ok else "failure"
    client = GitHubClient(token, repository, args.api_url)
    try:
        client.create_check(
            head_sha,
            conclusion,
            f"{CHECK_NAME}: {'PASS' if decision.ok else 'BLOCKED'}",
            decision.summary(),
            markdown,
        )
    except GitHubError as exc:
        print(f"error: could not create the required check run: {exc}", file=sys.stderr)
        return 2

    if args.comment:
        try:
            client.upsert_comment(number, comment_body(decision, head_sha))
        except GitHubError as exc:
            # The check run is authoritative; a comment failure must not hide it.
            print(f"warning: could not update the pull request comment: {exc}", file=sys.stderr)

    return 0 if decision.ok or args.allow_blocked else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--pr", type=int)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--head-sha")
    parser.add_argument("--team-file", default=".github/team.json")
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"))
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--output")
    parser.add_argument("--github-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--allow-stale-approvals", action="store_true",
                        help="Do not require reviews to be on the current head commit (not recommended).")
    parser.add_argument("--allow-blocked", action="store_true",
                        help="Exit 0 even when the policy blocks; the check run still reports failure.")
    parser.add_argument("--no-comment", dest="comment", action="store_false", default=True)
    parser.add_argument("--dry-run", action="store_true", help="Evaluate and print, but do not write to GitHub.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
