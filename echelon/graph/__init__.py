"""Echelon graph module - L1 citation graph construction and analysis."""
# AUDIT-008: bridging_centrality monthly full computation + sb_count proxy
# AUDIT-009/010: entity_overlap with TF-IDF truncation + Jaccard
# AUDIT-011: NetworkX vs GDS routing
# AUDIT-049: bridging_centrality absolute threshold 5e-5
# AUDIT-050: Isolation Forest + kNN-distance dual anomaly detection
# AUDIT-052: Cypher path limit *1..2, 5s timeout
# AUDIT-076: local PageRank with virtual sink node
# AUDIT-077: semantic_bridge pre_filter_cross_topic
# V13-CE: fused_edge (4-type fusion) + overlay_builder (graph overlay)

# Import only from files we own (avoid importing pre-existing files that may have issues)
from .centrality import (
    compute_bridging_centrality_monthly,
    compute_sb_count_proxy,
    BC_ABSOLUTE_THRESHOLD,
    is_bridging_node,
    filter_bridging_nodes,
)
from .bib_couple import entity_overlap_jaccard, build_bib_coupling_edges
from .build_l1 import compute_centrality_networkx, compute_centrality_neo4j_gds
from .path_query import build_cross_domain_cypher, CYPHER_TIMEOUT_S
from .anomaly_detection import detect_outliers, whitening_transform
from .local_pagerank import compute_local_pagerank_with_sink, EXTERNAL_SINK_ID
from .semantic_bridge import pre_filter_cross_topic, count_semantic_bridges
# V13-CE
from .fused_edge import fused_edge_weight, normalize_log, build_fused_edge_table, compute_time_decay
from .overlay_builder import build_overlay, load_overlay_inputs_from_files

__all__ = [
    # AUDIT-008 / AUDIT-049
    "compute_bridging_centrality_monthly",
    "compute_sb_count_proxy",
    "BC_ABSOLUTE_THRESHOLD",
    "is_bridging_node",
    "filter_bridging_nodes",
    # bib coupling
    "entity_overlap_jaccard",
    "build_bib_coupling_edges",
    # L1 build
    "compute_centrality_networkx",
    "compute_centrality_neo4j_gds",
    # path query
    "build_cross_domain_cypher",
    "CYPHER_TIMEOUT_S",
    # AUDIT-050
    "detect_outliers",
    "whitening_transform",
    # AUDIT-076
    "compute_local_pagerank_with_sink",
    "EXTERNAL_SINK_ID",
    # AUDIT-077
    "pre_filter_cross_topic",
    "count_semantic_bridges",
    # V13-CE: fused_edge
    "fused_edge_weight",
    "normalize_log",
    "build_fused_edge_table",
    "compute_time_decay",
    # V13-CE: overlay_builder
    "build_overlay",
    "load_overlay_inputs_from_files",
]
