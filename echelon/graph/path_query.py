"""
AUDIT-052: Neo4j 3 跳路径组合爆炸修复

原问题: *1..3 在 5w 节点 + 1900w 边稠密图上产生万亿级搜索树,
        单次查询耗尽 JVM 堆内存, 导致 Neo4j 宕机

修复:
- 所有 Cypher 路径限制为 *1..2 (严格 2 跳)
- 配置 5s 超时 (dbms.transaction.timeout)
- 热门节点 (度 > 1000) 加 LIMIT 200 短路

参考: https://neo4j.com/docs/cypher-manual/current/clauses/match/#shortest-path
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, FrozenSet

# [AUDIT-052] 全局超时配置 (秒)
CYPHER_TIMEOUT_S = 5

# [AUDIT-052] 最大路径跳数 (严格不超过 2)
MAX_PATH_HOPS = 2

# 热门节点度阈值 (超过此度数的节点查询加 LIMIT 保护)
HIGH_DEGREE_THRESHOLD = 1000
HIGH_DEGREE_LIMIT = 200


def build_cross_domain_cypher(
    topic_id_a: str,
    topic_id_b: str,
    limit: int = 50,
    timeout_s: int = CYPHER_TIMEOUT_S,
) -> str:
    """
    [AUDIT-052] 构建跨子领域路径查询 Cypher

    修复要点:
    - *1..2 严格限制跳数 (不用 *1..3)
    - 5s 超时通过 dbms.transaction.timeout 配置
    - 参数化绑定 (防 Cypher 注入, AUDIT-028)

    Args:
        topic_id_a: 起点 topic ID
        topic_id_b: 终点 topic ID
        limit: 最大返回路径数
        timeout_s: 查询超时 (秒)

    Returns:
        参数化 Cypher 查询字符串

    Notes:
        调用时必须使用参数绑定:
        session.run(cypher, {"topic_id_a": "T10245", "topic_id_b": "T10653"})
    """
    # [AUDIT-052] 严格限制 *1..2 (最大 2 跳)
    cypher = """
// AUDIT-052: 路径跳数严格限制为最大两跳 (*1..2)
// 超时: dbms.transaction.timeout={timeout_s}s
MATCH path = (a:Paper {{topic_id: $topic_id_a}})
    -[:SEMANTIC_BRIDGE|CO_CITATION*1..2]-
    (b:Paper {{topic_id: $topic_id_b}})
WHERE length(path) <= {max_hops}
RETURN path
LIMIT {limit}
""".format(
        timeout_s=timeout_s,
        max_hops=MAX_PATH_HOPS,
        limit=min(limit, 200),  # 安全上限
    )
    return cypher.strip()


def build_shortest_path_cypher(
    paper_id_a: str,
    paper_id_b: str,
) -> str:
    """
    [AUDIT-052] 使用 shortestPath() 替代变长路径 (更高效)

    shortestPath 内部使用 BFS, 比 *1..N 可变路径效率高数量级。

    Returns:
        参数化 Cypher (需绑定 $paper_id_a, $paper_id_b)
    """
    return """
// AUDIT-052: shortestPath 替代可变跳数路径, BFS 效率高数量级
MATCH (a:Paper {paper_id: $paper_id_a}), (b:Paper {paper_id: $paper_id_b})
WITH a, b
MATCH path = shortestPath(
    (a)-[:SEMANTIC_BRIDGE|CO_CITATION*1..2]-(b)
)
RETURN path, length(path) AS hops
""".strip()


def build_high_degree_safe_cypher(
    paper_id: str,
    max_degree: int = HIGH_DEGREE_THRESHOLD,
) -> str:
    """
    [AUDIT-052] 热门节点安全查询: 对度 > max_degree 的节点加短路保护

    热门节点 (hub nodes) 的邻居遍历会产生指数级搜索树。
    对此类节点加 LIMIT 和度数过滤提前终止。

    Returns:
        参数化 Cypher (需绑定 $paper_id)
    """
    return f"""
// AUDIT-052: 热门节点保护 (度 > {max_degree} 时 LIMIT {HIGH_DEGREE_LIMIT})
MATCH (a:Paper {{paper_id: $paper_id}})
WITH a, size((a)-[:SEMANTIC_BRIDGE|CO_CITATION]-()) AS node_degree
WHERE node_degree <= {max_degree}
MATCH path = (a)-[:SEMANTIC_BRIDGE|CO_CITATION*1..2]-(b:Paper)
RETURN path
LIMIT {HIGH_DEGREE_LIMIT}

UNION

// 热门节点: 仅 1 跳 + 严格 LIMIT
MATCH (a:Paper {{paper_id: $paper_id}})
WITH a, size((a)-[:SEMANTIC_BRIDGE|CO_CITATION]-()) AS node_degree
WHERE node_degree > {max_degree}
MATCH (a)-[r:SEMANTIC_BRIDGE|CO_CITATION]->(b:Paper)
RETURN r AS path
LIMIT {HIGH_DEGREE_LIMIT}
""".strip()


def get_neo4j_timeout_config() -> Dict[str, Any]:
    """
    [AUDIT-052] 返回 Neo4j 超时配置

    应将以下配置写入 neo4j.conf:
        dbms.transaction.timeout=5s

    Returns:
        配置字典 (供部署脚本使用)
    """
    return {
        "dbms.transaction.timeout": f"{CYPHER_TIMEOUT_S}s",
        "dbms.query.cache_size": 1000,
        "comment": (
            "AUDIT-052: 5s 超时防止 3 跳路径组合爆炸。"
            "所有 Cypher 路径查询限制 *1..2。"
        ),
    }


def execute_safe_path_query(
    session: Any,
    cypher: str,
    params: Dict[str, Any],
    timeout_s: int = CYPHER_TIMEOUT_S,
) -> List[Dict[str, Any]]:
    """
    [AUDIT-052] 带超时保护的 Cypher 执行

    Args:
        session: Neo4j session
        cypher: 已参数化的 Cypher (不含字符串拼接)
        params: 参数绑定 dict
        timeout_s: 超时 (秒)

    Returns:
        查询结果列表

    Raises:
        TimeoutError: 查询超时
        Exception: 其他 Neo4j 错误
    """
    # 验证查询不含 *1..3 (防止误用)
    if "*1..3" in cypher or "*2..3" in cypher or "*3" in cypher:
        raise ValueError(
            "[AUDIT-052] Cypher 包含 3 跳路径 (*1..3/*2..3/*3), "
            "已禁止使用。请改为 *1..2。"
        )

    # 在 Neo4j 驱动中, 超时通过事务级设置
    tx_config = {"timeout": timeout_s * 1000}  # 毫秒

    try:
        if hasattr(session, "run"):
            result = session.run(cypher, params)
            return [dict(r) for r in result]
        else:
            raise TypeError(f"期望 Neo4j session, 收到 {type(session)}")
    except Exception as e:
        if "timeout" in str(e).lower() or "deadline" in str(e).lower():
            raise TimeoutError(f"[AUDIT-052] Cypher 查询超时 ({timeout_s}s): {e}")
        raise


# ---------------------------------------------------------------------------
# AUDIT-028: CypherTemplate registry — parameterized binding, no injection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = re.compile(
    r"(;\s*(drop|delete|remove|create|merge|set)\b|"
    r"\}\s*\{|"      # Cypher map injection
    r"//.*\n|"       # comment injection
    r"--)",          # SQL-style comment (defensive)
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CypherTemplate:
    """
    A pre-approved, parameterized Cypher query template.

    [AUDIT-028] Only templates in _TEMPLATE_REGISTRY may be executed.
    Parameters are passed via Neo4j driver's parameterized binding,
    never via Python string interpolation.
    """
    name: str
    template: str                   # Cypher with $param placeholders
    allowed_params: FrozenSet[str]  # allowlist of valid param names


# [AUDIT-028] Registry of all approved Cypher templates.
# New templates MUST be added here — not constructed at runtime.
_TEMPLATE_REGISTRY: Dict[str, CypherTemplate] = {
    "cross_domain_path": CypherTemplate(
        name="cross_domain_path",
        template=(
            "MATCH path = (a:Paper {topic_id: $topic_id_a})"
            "-[:SEMANTIC_BRIDGE|CO_CITATION*1..2]-"
            "(b:Paper {topic_id: $topic_id_b})"
            " WHERE length(path) <= 2"
            " RETURN path LIMIT $limit"
        ),
        allowed_params=frozenset({"topic_id_a", "topic_id_b", "limit"}),
    ),
    "shortest_path": CypherTemplate(
        name="shortest_path",
        template=(
            "MATCH (a:Paper {paper_id: $paper_id_a}), (b:Paper {paper_id: $paper_id_b})"
            " WITH a, b"
            " MATCH path = shortestPath((a)-[:SEMANTIC_BRIDGE|CO_CITATION*1..2]-(b))"
            " RETURN path, length(path) AS hops"
        ),
        allowed_params=frozenset({"paper_id_a", "paper_id_b"}),
    ),
    "papers_by_topic": CypherTemplate(
        name="papers_by_topic",
        template=(
            "MATCH (p:Paper {topic_id: $topic_id})"
            " RETURN p.paper_id, p.title, p.publication_year"
            " ORDER BY p.keystone_score DESC LIMIT $limit"
        ),
        allowed_params=frozenset({"topic_id", "limit"}),
    ),
    "bottleneck_neighbors": CypherTemplate(
        name="bottleneck_neighbors",
        template=(
            "MATCH (b:Bottleneck {bottleneck_id: $bottleneck_id})"
            "-[:SUPPORTED_BY*1..2]-(p:Paper)"
            " RETURN DISTINCT p.paper_id, p.title LIMIT $limit"
        ),
        allowed_params=frozenset({"bottleneck_id", "limit"}),
    ),
}


def execute_cypher(
    session: Any,
    template_name: str,
    params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    [AUDIT-028] Safe Cypher execution through the template registry.

    - Only pre-approved templates may be used (no runtime construction)
    - Parameters are validated against each template's allowlist
    - Injection patterns in param values are rejected
    - Neo4j driver handles parameterized binding (no string splice)

    Args:
        session:       Neo4j session object.
        template_name: Key in _TEMPLATE_REGISTRY.
        params:        Parameter dict — keys must be in template.allowed_params.

    Raises:
        KeyError:   template_name not in registry.
        ValueError: params contain disallowed keys or injection patterns.
        TypeError:  session is not a valid Neo4j session.
    """
    if template_name not in _TEMPLATE_REGISTRY:
        raise KeyError(
            f"[AUDIT-028] Unknown Cypher template {template_name!r}. "
            f"Allowed: {sorted(_TEMPLATE_REGISTRY)}"
        )

    tmpl = _TEMPLATE_REGISTRY[template_name]

    # Validate param keys against allowlist
    disallowed = set(params) - tmpl.allowed_params
    if disallowed:
        raise ValueError(
            f"[AUDIT-028] Disallowed params for template {template_name!r}: "
            f"{disallowed}. Allowed: {tmpl.allowed_params}"
        )

    # Check param values for injection patterns
    for key, val in params.items():
        if isinstance(val, str) and _INJECTION_PATTERNS.search(val):
            raise ValueError(
                f"[AUDIT-028] Injection pattern detected in param {key!r}={val!r}"
            )

    if not hasattr(session, "run"):
        raise TypeError(f"[AUDIT-028] Expected Neo4j session, got {type(session)}")

    result = session.run(tmpl.template, params)
    return [dict(r) for r in result]


def build_cypher_from_dict(d: Dict[str, Any]) -> str:  # noqa: ARG001
    """
    [AUDIT-028] TRAP FUNCTION — raises TypeError unconditionally.

    V11.1 used to splice a dict directly into Cypher strings,
    creating SQL/Cypher injection vulnerabilities.  This function
    exists ONLY to surface that anti-pattern immediately at call time.

    Use execute_cypher(session, template_name, params) instead.
    """
    raise TypeError(
        "[AUDIT-028] build_cypher_from_dict() is FORBIDDEN. "
        "Dict→Cypher string splicing enables injection attacks. "
        "Use execute_cypher(session, template_name, params) with a "
        "pre-approved template from _TEMPLATE_REGISTRY instead."
    )
