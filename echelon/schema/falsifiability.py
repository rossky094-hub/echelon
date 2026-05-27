"""
[修订自 AUDIT-036] schema 层包装,re-export from echelon.physics.falsifiability

V11.2 设计中,Falsifiability schema 实际属于 physics 层(因为按 validation_type 分支,
仿真用 convergence_criterion,实验才用 alpha/power)。本文件作为 schema 层的别名入口,
保证 `from echelon.schema.falsifiability import ...` 也能工作。

这是 V11.2 → V11.3 期间的过渡兼容层。V11.3 会把 schema 层完全收敛到 echelon.schema.*。
"""
from echelon.physics.falsifiability import (  # noqa: F401
    ValidationType,
    VALIDATION_REQUIREMENTS,
    ExperimentValidation,
)

# 显式 re-export,便于静态分析
__all__ = [
    "ValidationType",
    "VALIDATION_REQUIREMENTS",
    "ExperimentValidation",
]
