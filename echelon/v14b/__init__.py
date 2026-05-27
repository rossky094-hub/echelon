"""
Echelon V14-B 演化树 Pilot 模块

包含完整的 9-step 演化树分析流程:
  Step 1: OpenAlex enrich
  Step 2: SPC Main Path
  Step 3: V14 调权 KeystoneScore
  Step 4: 子图构建
  Step 5a: SciBERT 引用功能分类
  Step 5b: VGAE 训练 + Link Prediction
  Step 5c: Limitation Tracking
  Step 6: 三路融合
  Step 7: 三色突变标记
  Step 8: UMAP-3D 布局
  Step 9: 报告生成

环境要求: macOS Apple Silicon (M1/M2/M3) + Python 3.11+
"""

__version__ = "14.2.0"
__all__ = [
    "config",
    "llm_client",
    "db_schema",
    "utils",
]
