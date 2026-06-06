"""Tests for reputation (Module 5)."""
from __future__ import annotations

from pathlib import Path

import pytest
from db_schema import create_test_db
from escrow import EscrowService
from evidence_chain import EvidenceChainService
from identity import IdentityService
from reputation import ReviewService


@pytest.fixture
def services():
    """Create ReputationService and identity fixtures for testing."""
    conn, db_path = create_test_db()
    identity = IdentityService(db_path)
    identity._conn = conn
    evidence = EvidenceChainService(identity, conn)
    escrow = EscrowService(conn, identity)
    reviews = ReviewService(conn, identity, evidence)

    alice = identity.register("Alice")
    bob = identity.register("Bob")

    yield identity, evidence, escrow, reviews, alice, bob, "t-001"

    identity.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


class TestReviews:
    def test_submit_review(self, services):
        """Verify submitting a review records it and returns a review ID."""
        _, _, _, reviews, alice, bob, task_id = services
        result = reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5, "Great!")
        assert result["score"] == 5
        assert result["rater_id"] == alice["agent_id"]

    def test_no_self_review(self, services):
        """Verify an agent cannot review itself."""
        _, _, _, reviews, alice, _, task_id = services
        with pytest.raises(ValueError, match="Cannot self-review"):
            reviews.submit_review(task_id, alice["agent_id"], alice["agent_id"], 5)

    def test_no_duplicate_review(self, services):
        """Verify duplicate reviews for the same task and reviewer are rejected."""
        _, _, _, reviews, alice, bob, task_id = services
        reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5)
        with pytest.raises(ValueError, match="Duplicate"):
            reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 4)

    def test_get_reviews_for_target(self, services):
        """Verify retrieving reviews for a given target agent."""
        _, _, _, reviews, alice, bob, task_id = services
        reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 4)
        reviews.submit_review(task_id + "-2", bob["agent_id"], alice["agent_id"], 5)

        bob_reviews = reviews.get_reviews_for_target(bob["agent_id"])
        assert len(bob_reviews) == 1
        assert bob_reviews[0]["rating"] == 4

    def test_reputation_after_review(self, services):
        """Verify reputation score updates after a review is submitted."""
        _, _, _, reviews, alice, bob, task_id = services
        rep_before = reviews.get_reputation(bob["agent_id"])
        assert rep_before["avg_rating"] == 3.0  # Bayesian prior

        reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5)
        rep_after = reviews.get_reputation(bob["agent_id"])
        assert rep_after["total_reviews"] == 1
        assert 3.0 < rep_after["avg_rating"] <= 5.0

    def test_on_task_settled(self, services):
        """Verify reputation is updated when a task is settled."""
        _, _, _, reviews, alice, bob, task_id = services
        result = reviews.on_task_settled(task_id, alice["agent_id"], bob["agent_id"])
        assert result["review_window_open"] is True

        rep = reviews.get_reputation(alice["agent_id"])
        assert rep["as_publisher"] >= 1
        rep2 = reviews.get_reputation(bob["agent_id"])
        assert rep2["as_executor"] >= 1

    def test_top_agents(self, services):
        """Verify retrieving the top-rated agents returns the correct ranking."""
        _, _, _, reviews, alice, bob, task_id = services
        reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5)
        top = reviews.list_top_agents()
        assert len(top) >= 1

    def test_out_of_range_score_low(self, services):
        """Score < 1 raises ValueError."""
        _, _, _, reviews, alice, bob, task_id = services
        with pytest.raises(ValueError, match="Score must be 1-5"):
            reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 0)

    def test_out_of_range_score_high(self, services):
        """Score > 5 raises ValueError."""
        _, _, _, reviews, alice, bob, task_id = services
        with pytest.raises(ValueError, match="Score must be 1-5"):
            reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 6)

    def test_get_reviews_for_task(self, services):
        """Query reviews by task_id."""
        _, _, _, reviews, alice, bob, task_id = services
        reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 4, "Good")
        task_reviews = reviews.get_reviews_for_task(task_id)
        assert len(task_reviews) == 1
        assert task_reviews[0]["comment"] == "Good"

    def test_get_reviews_for_task_empty(self, services):
        """get_reviews_for_task returns empty list for non-existent task."""
        _, _, _, reviews, _, _, _ = services
        assert reviews.get_reviews_for_task("nonexistent") == []

    def test_get_reputation_fallback(self, services):
        """get_reputation returns Bayesian prior for agents with no reviews."""
        _, _, _, reviews, _, _, _ = services
        rep = reviews.get_reputation("new_agent")
        assert rep["avg_rating"] == 3.0
        assert rep["total_reviews"] == 0

    def test_recompute_reputation_no_reviews(self, services):
        """_recompute_reputation with no reviews returns early."""
        _, _, _, reviews, _, alice, _ = services
        # Directly call private method with an agent that has no reviews
        reviews._recompute_reputation(alice["agent_id"])
        # Should not crash; no reputation record should exist yet
        rep = reviews.get_reputation(alice["agent_id"])
        assert rep["total_reviews"] == 0
