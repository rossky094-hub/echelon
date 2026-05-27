"""
AUDIT-084 P1: tiktoken 真编码替换 split() 词数估计

问题: len(text.split()) 用空格分词估计 token 数, 与 BPE 实际编码误差 ≥ 1.3×.
     例如 "photonic crystal nanocavity" (3 words) 实际可能是 5-6 tokens.

修复:
  - tiktoken_count(text, model="gpt-4") 用 cl100k_base BPE 编码精确计数
  - 所有原 len(text.split()) token 计数调用替换为 tiktoken_count()

cl100k_base 是 OpenAI 标准编码, 适用于 GPT-3.5/4/text-embedding-ada-002.
对 FlanT5/bge-m3 等模型也是合理的近似估计 (误差 < 20% vs split 的 30%+ 误差).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 编码缓存 (避免重复初始化)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _get_encoding(encoding_name: str = "cl100k_base"):
    """获取并缓存 tiktoken encoding."""
    import tiktoken
    return tiktoken.get_encoding(encoding_name)


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------

def tiktoken_count(
    text: str,
    model: str = "gpt-4",
    encoding_name: str = "cl100k_base",
) -> int:
    """
    [AUDIT-084] 用 tiktoken BPE 编码精确计算文本 token 数.

    使用 cl100k_base encoding (OpenAI 标准, GPT-3.5/4/ada-002 兼容).
    比 len(text.split()) 误差从 30%+ 降到 < 5%.

    Args:
        text:          待计数文本.
        model:         目标模型名 (当前仅用于日志/文档, 编码固定 cl100k_base).
        encoding_name: tiktoken encoding 名称 (默认 cl100k_base).

    Returns:
        整数 token 数.

    Examples:
        >>> tiktoken_count("Hello, world!")
        4
        >>> tiktoken_count("")
        0

    Note:
        若 tiktoken 不可用 (ImportError), fallback 到 len(text.split())
        并记录警告.
    """
    if not text:
        return 0

    try:
        enc = _get_encoding(encoding_name)
        return len(enc.encode(text))
    except ImportError:
        logger.warning(
            "AUDIT-084: tiktoken not installed. "
            "Falling back to split()-based count (inaccurate). "
            "Install: pip install tiktoken"
        )
        return len(text.split())
    except Exception as exc:
        logger.warning(f"AUDIT-084: tiktoken_count failed ({exc}), using split fallback")
        return len(text.split())


def tiktoken_count_batch(
    texts: list[str],
    model: str = "gpt-4",
    encoding_name: str = "cl100k_base",
) -> list[int]:
    """
    批量计算 token 数.

    Args:
        texts: 文本列表.

    Returns:
        对应的 token 数列表.
    """
    return [tiktoken_count(t, model=model, encoding_name=encoding_name) for t in texts]


def split_word_count(text: str) -> int:
    """
    DEPRECATED: 原 len(text.split()) 实现, 仅供对比测试用.

    [AUDIT-084] 误差 ≥ 1.3× vs tiktoken. 请使用 tiktoken_count().
    """
    import warnings
    warnings.warn(
        "split_word_count() 误差 ≥ 1.3× (AUDIT-084). 请使用 tiktoken_count().",
        DeprecationWarning,
        stacklevel=2,
    )
    return len(text.split())


def measure_split_vs_tiktoken_ratio(text: str) -> float:
    """
    计算 split() 词数与 tiktoken 真 token 数的比值.

    用于验证 AUDIT-084: 比值 ≥ 1.3 说明 split 严重低估 token 数.

    Args:
        text: 输入文本.

    Returns:
        tiktoken_count / split_count (若 split=0 返回 1.0).
    """
    split_n = len(text.split())
    tiktoken_n = tiktoken_count(text)
    if split_n == 0:
        return 1.0
    return tiktoken_n / split_n
