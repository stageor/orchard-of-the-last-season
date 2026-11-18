import unittest

from scripts.approval_policy import (
    Decision,
    TeamConfigError,
    evaluate,
    is_fork,
    load_team,
    parse_command,
    sha_matches,
)

HEAD = "a" * 40
OLD = "b" * 40
TEAM = {
    "members": [
        {"name": "Stanley", "login": "stanley-dev"},
        {"name": "Zian", "login": "zian-dev"},
        {"name": "Manu", "login": "manu-dev"},
    ],
    "requiredApprovals": {"memberAuthored": 2, "externalAuthored": 3},
    "commands": {"signoff": "/signoff", "protectedCi": "/approve-ci"},
}


def pr(author="stanley-dev", fork=False, draft=False, merged=False, state="open", mergeable_state="clean"):
    return {
        "user": {"login": author},
        "state": state,
        "draft": draft,
        "merged": merged,
        "mergeable_state": mergeable_state,
        "head": {"sha": HEAD, "repo": {"full_name": "org/repo" if not fork else "fork/repo", "fork": fork}},
        "base": {"repo": {"full_name": "org/repo"}},
    }


def review(login, state="APPROVED", sha=HEAD, submitted="2026-11-17T10:00:00Z"):
    return {"user": {"login": login}, "state": state, "commit_id": sha, "submitted_at": submitted}


def comment(login, body, updated="2026-11-17T10:00:00Z", cid=1):
    return {"user": {"login": login}, "body": body, "updated_at": updated, "created_at": updated, "id": cid}


def signoff(login="stanley-dev", sha=HEAD):
    return comment(login, f"/signoff {sha}")


class ApprovalPolicyTests(unittest.TestCase):
    def test_member_author_needs_other_two_and_signoff(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff("stanley-dev")],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok, decision.reasons)
        self.assertEqual(2, decision.required_approvals)
        self.assertTrue(decision.signoff_ok)
        self.assertFalse(decision.author_is_member is False)

    def test_member_author_missing_approval_blocks(self):
        decision = evaluate(pr("stanley-dev"), [review("zian-dev")], [signoff()], [], TEAM, HEAD)
        self.assertFalse(decision.ok)
        self.assertEqual(["manu-dev"], decision.missing)

    def test_member_author_missing_signoff_blocks(self):
        decision = evaluate(pr("stanley-dev"), [review("zian-dev"), review("manu-dev")], [], [], TEAM, HEAD)
        self.assertFalse(decision.ok)
        self.assertTrue(any("signoff" in reason.lower() for reason in decision.reasons))

    def test_author_approval_is_never_counted(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("stanley-dev"), review("zian-dev"), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok)
        self.assertNotIn("stanley-dev", decision.approvals)
        self.assertTrue(any("self-review" in warning for warning in decision.warnings))

    def test_external_author_needs_all_three(self):
        decision = evaluate(
            pr("outside-person", fork=True),
            [review("stanley-dev"), review("zian-dev")],
            [],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)
        self.assertEqual(["manu-dev"], decision.missing)
        self.assertEqual(3, decision.required_approvals)
        self.assertTrue(decision.fork)

    def test_external_author_with_all_three_passes_without_signoff(self):
        decision = evaluate(
            pr("outside-person", fork=True),
            [review("stanley-dev"), review("zian-dev"), review("manu-dev")],
            [],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok, decision.reasons)

    def test_approval_on_older_commit_is_stale(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev", sha=OLD), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)
        self.assertEqual(["zian-dev"], decision.stale_approvals)
        self.assertIn("zian-dev", decision.missing)

    def test_changes_requested_blocks(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev", state="CHANGES_REQUESTED"), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)
        self.assertEqual(["zian-dev"], decision.changes_requested)

    def test_comment_after_approval_does_not_erase_it(self):
        decision = evaluate(
            pr("stanley-dev"),
            [
                review("zian-dev", "APPROVED", submitted="2026-11-17T10:00:00Z"),
                review("zian-dev", "COMMENTED", submitted="2026-11-17T11:00:00Z"),
                review("manu-dev"),
            ],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok, decision.reasons)

    def test_latest_changes_requested_after_approval_blocks(self):
        decision = evaluate(
            pr("stanley-dev"),
            [
                review("zian-dev", "APPROVED", submitted="2026-11-17T10:00:00Z"),
                review("zian-dev", "CHANGES_REQUESTED", submitted="2026-11-17T11:00:00Z"),
                review("manu-dev"),
            ],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)

    def test_unauthorized_approvals_are_ignored(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("random-user"), review("zian-dev"), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok)
        self.assertEqual(["random-user"], decision.unauthorized_approvals)

    def test_signoff_for_old_sha_blocks(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff(sha=OLD)],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)
        self.assertFalse(decision.signoff_ok)

    def test_signoff_by_non_author_does_not_count(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [comment("manu-dev", f"/signoff {HEAD}")],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)

    def test_latest_signoff_wins(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [
                comment("stanley-dev", f"/signoff {OLD}", updated="2026-11-17T10:00:00Z"),
                comment("stanley-dev", f"/signoff {HEAD}", updated="2026-11-17T11:00:00Z", cid=2),
            ],
            [],
            TEAM,
            HEAD,
        )
        self.assertTrue(decision.ok, decision.reasons)

    def test_protected_paths_need_non_author_ci_approval(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff()],
            [{"filename": ".github/workflows/ci.yml"}],
            TEAM,
            HEAD,
            protected_patterns=(".github/**",),
        )
        self.assertFalse(decision.ok)
        self.assertTrue(decision.protected_files)
        self.assertFalse(decision.ci_approval_ok)

    def test_protected_paths_pass_with_non_author_member_approval(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff(), comment("zian-dev", f"/approve-ci {HEAD}", cid=2)],
            [{"filename": ".github/workflows/ci.yml"}],
            TEAM,
            HEAD,
            protected_patterns=(".github/**",),
        )
        self.assertTrue(decision.ok, decision.reasons)
        self.assertTrue(decision.ci_approval_ok)

    def test_protected_paths_reject_author_ci_approval(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff(), comment("stanley-dev", f"/approve-ci {HEAD}", cid=2)],
            [{"filename": ".github/workflows/ci.yml"}],
            TEAM,
            HEAD,
            protected_patterns=(".github/**",),
        )
        self.assertFalse(decision.ok)

    def test_protected_paths_reject_non_member_ci_approval(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff(), comment("random-user", f"/approve-ci {HEAD}", cid=2)],
            [{"filename": ".github/workflows/ci.yml"}],
            TEAM,
            HEAD,
            protected_patterns=(".github/**",),
        )
        self.assertFalse(decision.ok)

    def test_protected_ci_approval_for_old_sha_blocks(self):
        decision = evaluate(
            pr("stanley-dev"),
            [review("zian-dev"), review("manu-dev")],
            [signoff(), comment("zian-dev", f"/approve-ci {OLD}", cid=2)],
            [{"filename": ".github/workflows/ci.yml"}],
            TEAM,
            HEAD,
            protected_patterns=(".github/**",),
        )
        self.assertFalse(decision.ok)

    def test_placeholder_team_fails_closed(self):
        team = {
            "members": [
                {"name": "Stanley", "login": "REPLACE_ME_stanley"},
                {"name": "Zian", "login": "REPLACE_ME_zian"},
                {"name": "Manu", "login": "REPLACE_ME_manu"},
            ]
        }
        decision = evaluate(pr("stanley-dev"), [], [], [], team, HEAD)
        self.assertFalse(decision.ok)
        self.assertFalse(decision.team_configured)

    def test_draft_blocks(self):
        decision = evaluate(
            pr("stanley-dev", draft=True),
            [review("zian-dev"), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)

    def test_merge_conflict_blocks(self):
        decision = evaluate(
            pr("stanley-dev", mergeable_state="dirty"),
            [review("zian-dev"), review("manu-dev")],
            [signoff()],
            [],
            TEAM,
            HEAD,
        )
        self.assertFalse(decision.ok)

    def test_merged_pr_is_informational(self):
        decision = evaluate(pr("stanley-dev", merged=True, state="closed"), [], [], [], TEAM, HEAD)
        self.assertTrue(decision.ok)
        self.assertTrue(decision.merged)

    def test_closed_unmerged_pr_is_informational(self):
        decision = evaluate(pr("stanley-dev", state="closed"), [], [], [], TEAM, HEAD)
        self.assertTrue(decision.ok)
        self.assertTrue(decision.closed)

    def test_fork_detection(self):
        self.assertTrue(is_fork(pr("x", fork=True)))
        self.assertFalse(is_fork(pr("x", fork=False)))

    def test_parse_command_is_strict(self):
        self.assertEqual(HEAD, parse_command(f"/signoff {HEAD}", "/signoff"))
        self.assertEqual(HEAD, parse_command(f"\n  /signoff {HEAD}  \n", "/signoff"))
        self.assertIsNone(parse_command(f"please /signoff {HEAD}", "/signoff"))
        self.assertIsNone(parse_command(f"/signoff {HEAD} extra", "/signoff"))
        self.assertIsNone(parse_command(f"`/signoff {HEAD}`", "/signoff"))
        self.assertIsNone(parse_command(f"/signoff\n{HEAD}", "/signoff"))
        self.assertIsNone(parse_command("", "/signoff"))

    def test_sha_matches_prefix_and_rejects_invalid(self):
        self.assertTrue(sha_matches("a" * 7, HEAD))
        self.assertTrue(sha_matches(HEAD.upper(), HEAD))
        self.assertFalse(sha_matches("c" * 7, HEAD))
        self.assertFalse(sha_matches("xyz", HEAD))

    def test_load_team_rejects_wrong_roster_size(self):
        with self.assertRaises(TeamConfigError):
            load_team({"members": TEAM["members"][:2]})

    def test_load_team_rejects_duplicate_logins(self):
        team = {
            "members": [
                {"name": "A", "login": "same"},
                {"name": "B", "login": "same"},
                {"name": "C", "login": "third"},
            ]
        }
        with self.assertRaises(TeamConfigError):
            load_team(team)

    def test_markdown_contains_status_and_blockers(self):
        decision = evaluate(pr("stanley-dev"), [], [], [], TEAM, HEAD)
        text = decision.markdown()
        self.assertIn("BLOCKED", text)
        self.assertIn("Missing required approvals", text)

    def test_decision_serialises(self):
        decision = Decision(ok=True)
        self.assertEqual(True, decision.to_dict()["ok"])


if __name__ == "__main__":
    unittest.main()
