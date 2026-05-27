"""
AUDIT-039 P1: EPKB 18 月过期 "诈尸" → 自动 refresh + legacy_known + 衰减

问题: EPKB (Emergent Physical Knowledge Base) 条目在 last_seen_date 距今
      超过 18 月后, 若没有新证据支撑, 依然以原始权重参与评分 → "诈尸"幽灵知识。

修复:
  - EPKBEntry Pydantic 模型含 last_seen_date / legacy_known / decay_factor
  - refresh_epkb_entries():
      • 扫描近 3 月是否有新证据 (由 recent_evidence_count 字段承载)
      • 无新证据且距今 ≥ 18 月 → legacy_known=True, decay_factor=0.5
      • 有新证据 → last_seen_date 更新为 today, decay_factor 保持
  - effective_weight(entry) = entry.weight * entry.decay_factor
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

LEGACY_THRESHOLD_MONTHS: int = 18   # 超过此月数视为过期
RECENT_EVIDENCE_WINDOW_DAYS: int = 90  # "近 3 月"新证据扫描窗口
LEGACY_DECAY_FACTOR: float = 0.5    # 过期衰减系数


# ---------------------------------------------------------------------------
# EPKBEntry 模型
# ---------------------------------------------------------------------------

class EPKBEntry(BaseModel):
    """
    [AUDIT-039] EPKB 条目模型.

    Attributes:
        entry_id:             唯一标识.
        claim_text:           知识声明文本.
        source_paper_id:      来源论文 ID.
        weight:               原始权重 (0-1).
        last_seen_date:       最近一次被证据支持的日期.
        legacy_known:         True = 已标记为过期诈尸, 进入衰减状态.
        decay_factor:         衰减系数, 正常为 1.0, 过期为 0.5.
        recent_evidence_count: 近 3 月内的新证据数量 (由 refresh 更新).
    """

    entry_id: str
    claim_text: str
    source_paper_id: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    last_seen_date: date
    legacy_known: bool = False
    decay_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    recent_evidence_count: int = Field(default=0, ge=0)

    def effective_weight(self) -> float:
        """返回衰减后的有效权重."""
        return self.weight * self.decay_factor

    def age_months(self, today: Optional[date] = None) -> float:
        """距 last_seen_date 的月数."""
        if today is None:
            today = date.today()
        delta_days = (today - self.last_seen_date).days
        return delta_days / 30.4


# ---------------------------------------------------------------------------
# Refresh 逻辑
# ---------------------------------------------------------------------------

def refresh_epkb_entries(
    entries: List[EPKBEntry],
    today: Optional[date] = None,
    legacy_threshold_months: int = LEGACY_THRESHOLD_MONTHS,
    decay_factor_on_expire: float = LEGACY_DECAY_FACTOR,
) -> List[EPKBEntry]:
    """
    [AUDIT-039] 扫描 EPKB 条目并自动处理过期/更新.

    逻辑:
      - 对每条 entry:
        1. 计算距 last_seen_date 的月数 (age_months)
        2. 若 recent_evidence_count > 0 (近 3 月有新证据):
             → last_seen_date = today, decay_factor 保持原值 (不降)
             → legacy_known = False (若之前已标记, 重置)
        3. 若 recent_evidence_count == 0 且 age_months ≥ legacy_threshold_months:
             → legacy_known = True
             → decay_factor = decay_factor_on_expire (默认 0.5)
        4. 其余 (近期无新证据但未到 18 月): 不变

    Args:
        entries:                   EPKB 条目列表.
        today:                     参考日期 (默认 date.today()).
        legacy_threshold_months:   过期阈值 (默认 18 月).
        decay_factor_on_expire:    过期衰减系数 (默认 0.5).

    Returns:
        更新后的 EPKBEntry 列表 (原地修改副本).

    Examples:
        >>> from datetime import date
        >>> e = EPKBEntry(entry_id="x", claim_text="...", source_paper_id="p1",
        ...               last_seen_date=date(2022, 1, 1), recent_evidence_count=0)
        >>> [r.legacy_known for r in refresh_epkb_entries([e], today=date(2024, 1, 1))]
        [True]
    """
    if today is None:
        today = date.today()

    refreshed: List[EPKBEntry] = []

    for entry in entries:
        # 复制避免原地修改
        e = entry.model_copy(deep=True)
        age = e.age_months(today)

        if e.recent_evidence_count > 0:
            # 有新证据 → 更新 last_seen_date, 取消 legacy 标记
            e.last_seen_date = today
            e.legacy_known = False
            # decay_factor 恢复为 1.0 (若之前降过)
            if e.decay_factor < 1.0:
                e.decay_factor = 1.0
        elif age >= legacy_threshold_months:
            # 无新证据且超过 18 月 → 标记过期并衰减
            e.legacy_known = True
            e.decay_factor = decay_factor_on_expire
        # 其余: 无变化

        refreshed.append(e)

    return refreshed


# ---------------------------------------------------------------------------
# 汇总辅助
# ---------------------------------------------------------------------------

def summarize_epkb(entries: List[EPKBEntry], today: Optional[date] = None) -> dict:
    """返回 EPKB 库的健康度统计."""
    if today is None:
        today = date.today()

    total = len(entries)
    legacy_count = sum(1 for e in entries if e.legacy_known)
    avg_effective_weight = (
        sum(e.effective_weight() for e in entries) / total if total > 0 else 0.0
    )
    return {
        "total": total,
        "legacy_count": legacy_count,
        "legacy_ratio": legacy_count / total if total > 0 else 0.0,
        "avg_effective_weight": avg_effective_weight,
    }
