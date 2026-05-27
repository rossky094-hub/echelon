"""
AUDIT-071 P1: MiniCheck token 路由

问题: MiniCheck-FlanT5 context window 512 token, 超过则截断导致验证失误.
      长 claim+evidence 需要路由到 HHEM-2.1-Open (7B, 8K context).

修复:
  - route_verifier(claim, evidence) → str:
    • tiktoken 估计 total tokens
    • > 480 → "HHEM-2.1-Open"  (7B, 8K context, 留 32 token buffer)
    • ≤ 480 → "MiniCheck-FlanT5"  (512 context)
  - verify_claim(claim, evidence): 按路由结果调用验证器 (HHEM 为 mock)

设计:
  - 阈值 480 (非 512): 保留 32 token 用于 prompt 模板前缀 overhead
  - HHEM mock 在测试中验证路由逻辑, 生产中替换为真实模型 API
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MINICHECK_MAX_TOKENS: int = 480          # 有效 window (512 - 32 overhead)
MINICHECK_MODEL_NAME: str = "MiniCheck-FlanT5(512 context)"
HHEM_MODEL_NAME: str = "HHEM-2.1-Open(7B,8K context)"

VerifierName = Literal["MiniCheck-FlanT5(512 context)", "HHEM-2.1-Open(7B,8K context)"]


# ---------------------------------------------------------------------------
# token 估计 (tiktoken)
# ---------------------------------------------------------------------------

def _count_tokens_tiktoken(text: str, model: str = "gpt-4") -> int:
    """
    用 tiktoken cl100k_base 编码估计 token 数.

    使用 cl100k_base (OpenAI 标准, 适用于 GPT-3.5/4/FlanT5 近似估计).
    注意: FlanT5 用 SentencePiece, 但 cl100k_base 是最通用的近似.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception as exc:
        logger.warning(f"tiktoken failed ({exc}), falling back to split-based estimate")
        return len(text.split())


# ---------------------------------------------------------------------------
# 路由函数
# ---------------------------------------------------------------------------

def route_verifier(
    claim: str,
    evidence: str,
    threshold: int = MINICHECK_MAX_TOKENS,
) -> VerifierName:
    """
    [AUDIT-071] 根据 claim + evidence 的总 token 数路由到合适的验证器.

    路由规则:
      total_tokens = tiktoken_count(claim + " " + evidence)
      > threshold (默认 480) → HHEM-2.1-Open (7B, 8K context)
      ≤ threshold             → MiniCheck-FlanT5 (512 context)

    Args:
        claim:     待验证声明文本.
        evidence:  证据文本.
        threshold: token 数阈值 (默认 480).

    Returns:
        验证器名称字符串.

    Examples:
        >>> short = "X is fast."
        >>> route_verifier(short, short)
        'MiniCheck-FlanT5(512 context)'
    """
    combined = claim + " " + evidence
    n_tokens = _count_tokens_tiktoken(combined)

    if n_tokens > threshold:
        logger.debug(f"route_verifier: {n_tokens} tokens > {threshold} → {HHEM_MODEL_NAME}")
        return HHEM_MODEL_NAME
    else:
        logger.debug(f"route_verifier: {n_tokens} tokens ≤ {threshold} → {MINICHECK_MODEL_NAME}")
        return MINICHECK_MODEL_NAME


# ---------------------------------------------------------------------------
# 验证函数 (HHEM 为 mock, 测试路由逻辑用)
# ---------------------------------------------------------------------------

def _minicheck_flant5_verify(claim: str, evidence: str) -> float:
    """
    MiniCheck-FlanT5 验证器 (stub).

    生产中调用真实 FlanT5 API.
    返回 factual consistency 分数 ∈ [0, 1].
    """
    # Stub: 返回 0.8 (正常中位值)
    logger.debug("MiniCheck-FlanT5: stub returning 0.8")
    return 0.8


def _hhem_verify(claim: str, evidence: str) -> float:
    """
    HHEM-2.1-Open 验证器 (mock for testing routing logic).

    生产中替换为真实 HHEM-2.1-Open 7B 模型推理.
    返回 factual consistency 分数 ∈ [0, 1].
    """
    # Mock: 返回 0.75 (长文本验证通常稍低)
    logger.debug("HHEM-2.1-Open: mock returning 0.75")
    return 0.75


def verify_claim(
    claim: str,
    evidence: str,
    threshold: int = MINICHECK_MAX_TOKENS,
) -> dict:
    """
    [AUDIT-071] 完整验证流程: 路由 + 调用验证器.

    Args:
        claim:     待验证声明.
        evidence:  支撑证据.
        threshold: token 阈值 (默认 480).

    Returns:
        dict: {
            "verifier": str,       # 使用的验证器名称
            "score": float,        # factual consistency ∈ [0, 1]
            "token_count": int,    # 估计 token 数
        }
    """
    combined = claim + " " + evidence
    n_tokens = _count_tokens_tiktoken(combined)
    verifier = route_verifier(claim, evidence, threshold=threshold)

    if verifier == HHEM_MODEL_NAME:
        score = _hhem_verify(claim, evidence)
    else:
        score = _minicheck_flant5_verify(claim, evidence)

    return {
        "verifier": verifier,
        "score": score,
        "token_count": n_tokens,
    }
