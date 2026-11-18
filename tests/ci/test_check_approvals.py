import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_approvals as ca
from scripts.approval_policy import Decision


class EventTests(unittest.TestCase):
    def test_issue_comment_requires_pull_request(self):
        self.assertTrue(ca.should_run("issue_comment", {"issue": {"pull_request": {"url": "x"}}}))
        self.assertFalse(ca.should_run("issue_comment", {"issue": {}}))

    def test_pull_request_events(self):
        self.assertTrue(ca.should_run("pull_request_target", {"pull_request": {}}))
        self.assertTrue(ca.should_run("pull_request_review", {"pull_request": {}}))
        self.assertFalse(ca.should_run("push", {}))

    def test_resolve_pr_number(self):
        self.assertEqual(7, ca.resolve_pr_number("pull_request_target", {"pull_request": {"number": 7}}))
        self.assertEqual(8, ca.resolve_pr_number("issue_comment", {"issue": {"number": 8, "pull_request": {}}}))
        self.assertIsNone(ca.resolve_pr_number("issue_comment", {"issue": {"number": 8}}))
        self.assertEqual(9, ca.resolve_pr_number("pull_request_target", {}, explicit=9))

    def test_read_event_missing_file_is_empty(self):
        self.assertEqual({}, ca.read_event("/definitely/missing/event.json"))

    def test_read_team_missing_and_invalid(self):
        team, error = ca.read_team("/definitely/missing/team.json")
        self.assertEqual({}, team)
        self.assertIn("not found", error)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "team.json"
            path.write_text("{not json", encoding="utf-8")
            team, error = ca.read_team(path)
            self.assertEqual({}, team)
            self.assertIn("not valid JSON", error)


class GitHubClientTests(unittest.TestCase):
    def response(self, payload, status=200):
        raw = json.dumps(payload).encode()
        handle = mock.MagicMock()
        handle.read.return_value = raw
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        return handle

    def test_paginates_until_short_page(self):
        client = ca.GitHubClient("token", "org/repo")
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": 100}]
        with mock.patch("urllib.request.urlopen", side_effect=[self.response(page1), self.response(page2)]) as opener:
            result = client.paginate("/repos/org/repo/pulls/1/reviews")
        self.assertEqual(101, len(result))
        self.assertEqual(2, opener.call_count)

    def test_create_check_payload(self):
        client = ca.GitHubClient("token", "org/repo")
        with mock.patch.object(client, "request") as request:
            client.create_check("a" * 40, "failure", "Review gate: BLOCKED", "blocked", "details")
        method, path, payload = request.call_args.args
        self.assertEqual("POST", method)
        self.assertEqual("/repos/org/repo/check-runs", path)
        self.assertEqual(ca.CHECK_NAME, payload["name"])
        self.assertEqual("failure", payload["conclusion"])
        self.assertEqual("a" * 40, payload["head_sha"])

    def test_upsert_comment_updates_marker(self):
        client = ca.GitHubClient("token", "org/repo")
        with mock.patch.object(client, "paginate", return_value=[{"id": 5, "body": ca.COMMENT_MARKER + " old"}]), \
                mock.patch.object(client, "request") as request:
            client.upsert_comment(3, "new body")
        method, path, payload = request.call_args.args
        self.assertEqual("PATCH", method)
        self.assertEqual("/repos/org/repo/issues/comments/5", path)
        self.assertEqual("new body", payload["body"])

    def test_upsert_comment_creates_when_missing(self):
        client = ca.GitHubClient("token", "org/repo")
        with mock.patch.object(client, "paginate", return_value=[]), mock.patch.object(client, "request") as request:
            client.upsert_comment(3, "new body")
        method, path, payload = request.call_args.args
        self.assertEqual("POST", method)
        self.assertEqual("/repos/org/repo/issues/3/comments", path)


class CommentTests(unittest.TestCase):
    def test_comment_body_has_marker_and_head(self):
        text = ca.comment_body(Decision(ok=True), "a" * 40)
        self.assertIn(ca.COMMENT_MARKER, text)
        self.assertIn("a" * 40, text)
        self.assertIn("Required checks", text)


class RunTests(unittest.TestCase):
    def make_args(self, tmp, **overrides):
        team = Path(tmp) / "team.json"
        team.write_text(json.dumps({
            "members": [
                {"name": "Stanley", "login": "stanley-dev"},
                {"name": "Zian", "login": "zian-dev"},
                {"name": "Manu", "login": "manu-dev"},
            ]
        }), encoding="utf-8")
        base = dict(
            repo="org/repo",
            pr=4,
            token="token",
            head_sha="a" * 40,
            team_file=str(team),
            event_path=None,
            event_name="pull_request_target",
            api_url="https://api.github.com",
            output=None,
            github_summary=None,
            allow_stale_approvals=False,
            allow_blocked=False,
            comment=False,
            dry_run=False,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_run_posts_failure_check_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_args(tmp)
            fake = mock.MagicMock()
            fake.pull_request.return_value = {
                "user": {"login": "stanley-dev"},
                "state": "open",
                "head": {"sha": args.head_sha, "repo": {"full_name": "org/repo"}},
                "base": {"repo": {"full_name": "org/repo"}},
            }
            fake.reviews.return_value = []
            fake.comments.return_value = []
            fake.files.return_value = []
            with mock.patch.object(ca, "GitHubClient", return_value=fake):
                code = ca.run(args)
        self.assertEqual(1, code)
        fake.create_check.assert_called_once()
        self.assertEqual("failure", fake.create_check.call_args.args[1])

    def test_run_posts_success_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_args(tmp)
            fake = mock.MagicMock()
            fake.pull_request.return_value = {
                "user": {"login": "outside"},
                "state": "open",
                "head": {"sha": args.head_sha, "repo": {"full_name": "org/repo"}},
                "base": {"repo": {"full_name": "org/repo"}},
            }
            fake.reviews.return_value = [
                {"user": {"login": "stanley-dev"}, "state": "APPROVED", "commit_id": args.head_sha, "submitted_at": "2026-11-17T10:00:00Z"},
                {"user": {"login": "zian-dev"}, "state": "APPROVED", "commit_id": args.head_sha, "submitted_at": "2026-11-17T10:00:00Z"},
                {"user": {"login": "manu-dev"}, "state": "APPROVED", "commit_id": args.head_sha, "submitted_at": "2026-11-17T10:00:00Z"},
            ]
            fake.comments.return_value = []
            fake.files.return_value = []
            with mock.patch.object(ca, "GitHubClient", return_value=fake):
                code = ca.run(args)
        self.assertEqual(0, code)
        self.assertEqual("success", fake.create_check.call_args.args[1])

    def test_dry_run_does_not_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_args(tmp, dry_run=True)
            fake = mock.MagicMock()
            fake.pull_request.return_value = {
                "user": {"login": "outside"},
                "state": "open",
                "head": {"sha": args.head_sha, "repo": {"full_name": "org/repo"}},
                "base": {"repo": {"full_name": "org/repo"}},
            }
            fake.reviews.return_value = []
            fake.comments.return_value = []
            fake.files.return_value = []
            with mock.patch.object(ca, "GitHubClient", return_value=fake):
                code = ca.run(args)
        self.assertEqual(1, code)
        fake.create_check.assert_not_called()
        fake.upsert_comment.assert_not_called()

    def test_allow_blocked_still_posts_failure_but_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_args(tmp, allow_blocked=True)
            fake = mock.MagicMock()
            fake.pull_request.return_value = {
                "user": {"login": "outside"},
                "state": "open",
                "head": {"sha": args.head_sha, "repo": {"full_name": "org/repo"}},
                "base": {"repo": {"full_name": "org/repo"}},
            }
            fake.reviews.return_value = []
            fake.comments.return_value = []
            fake.files.return_value = []
            with mock.patch.object(ca, "GitHubClient", return_value=fake):
                code = ca.run(args)
        self.assertEqual(0, code)
        self.assertEqual("failure", fake.create_check.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
