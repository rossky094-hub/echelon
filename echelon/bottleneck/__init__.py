"""Echelon bottleneck module — L3 bottleneck convergence."""
from .debate_critic import (
    CriticResult,
    build_critic_prompt,
    run_debate_critic,
    validate_critic_result,
)
from .label_generator import (
    ClusterLabel,
    check_no_praise_words,
    generate_cluster_label,
)
from .prior_art_search import (
    PriorArtCandidate,
    reciprocal_rank_fusion,
    search_prior_art_rrf,
)

__all__ = [
    # debate_critic
    "CriticResult",
    "build_critic_prompt",
    "run_debate_critic",
    "validate_critic_result",
    # label_generator
    "ClusterLabel",
    "check_no_praise_words",
    "generate_cluster_label",
    # prior_art_search
    "PriorArtCandidate",
    "reciprocal_rank_fusion",
    "search_prior_art_rrf",
]
