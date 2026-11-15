"""Information-gain disambiguator for competing spaceflight medical hypotheses."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from .causal_graph import DisambiguationQuestion, HypothesisPosterior, question_p_yes


@dataclass(frozen=True)
class DisambiguationChoice:
    question: DisambiguationQuestion
    information_gain: float


def shannon_entropy(probs: Sequence[float]) -> float:
    """Compute Shannon entropy H(P) in bits."""
    return -sum(p * math.log2(p) for p in probs if p > 1e-12)


class Disambiguator:
    """Selects the disambiguation question with maximum expected information gain."""

    def __init__(
        self,
        *,
        ambiguity_top_prob_cutoff: float = 0.78,
        ambiguity_gap_cutoff: float = 0.30,
        min_ig_bits: float = 0.02,
    ) -> None:
        self.ambiguity_top_prob_cutoff = ambiguity_top_prob_cutoff
        self.ambiguity_gap_cutoff = ambiguity_gap_cutoff
        self.min_ig_bits = min_ig_bits

    def select_question(
        self,
        hypotheses: Sequence[HypothesisPosterior],
        *,
        answered_topics: Sequence[str] = (),
        observed_concepts: Sequence[str] = (),
        top_k: int = 4,
    ) -> Optional[DisambiguationChoice]:
        """Return the question maximizing expected entropy reduction IG(Q)."""
        if len(hypotheses) < 2:
            return None

        top1 = hypotheses[0].posterior
        top2 = hypotheses[1].posterior
        top2_ids = {hypotheses[0].condition.id, hypotheses[1].condition.id}
        ambiguous = not (
            top1 >= self.ambiguity_top_prob_cutoff and (top1 - top2) >= self.ambiguity_gap_cutoff
        )

        candidates_h = list(hypotheses[: max(2, top_k)])
        total_mass = sum(h.posterior for h in candidates_h) or 1.0
        base_probs = [h.posterior / total_mass for h in candidates_h]
        base_entropy = shannon_entropy(base_probs)

        answered_set = set(answered_topics)
        observed_set = set(observed_concepts)
        seen_q_ids: set[str] = set()
        best_choice: Optional[DisambiguationChoice] = None
        best_rank: tuple[int, int, float] = (-1, -1, -1.0)

        for h in candidates_h:
            for q in h.condition.disambiguation_questions:
                if not q.id or q.id in seen_q_ids or q.id in answered_set:
                    continue
                seen_q_ids.add(q.id)

                ig = self._information_gain(q, candidates_h, base_probs, base_entropy)
                if ig < self.min_ig_bits:
                    continue
                targets = set(q.target_differential_ids)
                both_top2 = 1 if (
                    top2_ids.issubset(targets)
                    or (q.owner_condition_id in top2_ids and bool(targets & (top2_ids - {q.owner_condition_id})))
                ) else 0
                in_top2 = 1 if q.owner_condition_id in top2_ids else 0
                rank = (both_top2, in_top2, ig)
                if best_choice is None or rank > best_rank:
                    best_choice = DisambiguationChoice(question=q, information_gain=ig)
                    best_rank = rank

        if ambiguous:
            return best_choice

        # Even when top hypothesis leads strongly, still surface an unanswered clinical
        # confirmation question on the winning hypothesis (prioritizing ones targeting #2)
        # if key distinguishing signs were not yet reported.
        top_cond = hypotheses[0].condition
        second_id = hypotheses[1].condition.id
        ordered_qs = sorted(
            top_cond.disambiguation_questions,
            key=lambda q: (1 if second_id in q.target_differential_ids else 0),
            reverse=True,
        )
        for q in ordered_qs:
            if q.id and q.id not in answered_set:
                if not any(c in observed_set for c in q.positive_concepts):
                    ig = self._information_gain(q, candidates_h, base_probs, base_entropy)
                    return DisambiguationChoice(question=q, information_gain=ig)
        return None

    @staticmethod
    def _information_gain(
        question: DisambiguationQuestion,
        hypotheses: Sequence[HypothesisPosterior],
        base_probs: Sequence[float],
        base_entropy: float,
    ) -> float:
        # Same P(yes | condition) table used by CausalGraph.evaluate, so question selection
        # and the posterior update are consistent (expected information gain is exact).
        p_yes_given_h: list[float] = [question_p_yes(question, h.condition) for h in hypotheses]

        p_yes_total = sum(p * py for p, py in zip(base_probs, p_yes_given_h))
        p_no_total = max(1e-9, 1.0 - p_yes_total)
        p_yes_total = max(1e-9, p_yes_total)

        post_yes = [(p * py) / p_yes_total for p, py in zip(base_probs, p_yes_given_h)]
        post_no = [(p * (1.0 - py)) / p_no_total for p, py in zip(base_probs, p_yes_given_h)]

        cond_entropy = p_yes_total * shannon_entropy(post_yes) + p_no_total * shannon_entropy(post_no)
        return max(0.0, base_entropy - cond_entropy)
