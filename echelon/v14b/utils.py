"""
V14-B 公共工具

包含:
  - Checkpoint 管理 (读/写/检测)
  - 进度条封装
  - 日志初始化
  - 环境检查
  - 通用 CLI 参数解析
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from tqdm import tqdm


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def ensure_library_schema_compat(conn: sqlite3.Connection) -> None:
    """将 V14-A library DB 补齐 V14-B step 所需列."""
    cols = table_columns(conn, "papers")
    if "publication_year" not in cols:
        try:
            conn.execute("ALTER TABLE papers ADD COLUMN publication_year INTEGER")
        except Exception:
            pass
    conn.execute("""
        UPDATE papers
        SET publication_year = CAST(substr(publication_date, 1, 4) AS INTEGER)
        WHERE publication_date IS NOT NULL
          AND (publication_year IS NULL OR publication_year = 0)
    """)
    conn.commit()

# ---------------------------------------------------------------------------
# 日志初始化
# ---------------------------------------------------------------------------

def setup_logging(
    step_name: str,
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
) -> logging.Logger:
    """
    初始化 step 日志:同时写文件和 stderr。

    Args:
        step_name: 例如 "step1_enrich"
        level:     日志级别
        log_dir:   日志目录,默认 config.LOG_DIR

    Returns:
        Logger 实例
    """
    from echelon.v14b.config import LOG_DIR

    if log_dir is None:
        log_dir = LOG_DIR
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{step_name}_{date_str}.log"

    logger = logging.getLogger(f"echelon.v14b.{step_name}")
    logger.setLevel(level)

    # 防止重复 handler
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(level)
    logger.addHandler(fh)

    # stderr handler
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(level)
    logger.addHandler(sh)

    logger.info("日志文件: %s", log_file)
    return logger


# ---------------------------------------------------------------------------
# Checkpoint 管理
# ---------------------------------------------------------------------------

class Checkpoint:
    """
    Step checkpoint 管理器。

    用法:
        ck = Checkpoint("step2_mainpath")
        if ck.done():
            print("已完成,跳过")
        else:
            # 执行任务...
            ck.mark_done(records_n=13606)
    """

    def __init__(
        self,
        step_name: str,
        checkpoint_dir: Optional[Path] = None,
    ) -> None:
        from echelon.v14b.config import CHECKPOINT_DIR

        if checkpoint_dir is None:
            checkpoint_dir = CHECKPOINT_DIR
        self.path = Path(checkpoint_dir) / f"{step_name}.done.json"
        self.step_name = step_name
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def done(self) -> bool:
        """检查 checkpoint 是否存在"""
        return self.path.exists()

    def mark_done(self, records_n: int = 0, meta: dict | None = None) -> None:
        """写 checkpoint 文件"""
        data = {
            "step": self.step_name,
            "finished_at": datetime.utcnow().isoformat(),
            "records_n": records_n,
            **(meta or {}),
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> dict:
        """读取 checkpoint 数据"""
        if not self.done():
            return {}
        return json.loads(self.path.read_text())

    def clear(self) -> None:
        """删除 checkpoint(允许重跑)"""
        if self.path.exists():
            self.path.unlink()


def check_resume(step_name: str, force: bool = False) -> bool:
    """
    检查是否可以跳过 step(已有 checkpoint 且不强制重跑)。

    Returns:
        True = 可跳过, False = 需要重跑
    """
    ck = Checkpoint(step_name)
    if force:
        ck.clear()
        return False
    if ck.done():
        data = ck.load()
        logging.getLogger(f"echelon.v14b.{step_name}").info(
            "Step %s 已完成 (%s records),跳过。--resume=false 可强制重跑",
            step_name,
            data.get("records_n", "?"),
        )
        return True
    return False


# ---------------------------------------------------------------------------
# 进度条封装
# ---------------------------------------------------------------------------

def make_progress(iterable, desc: str, total: int | None = None, **kwargs):
    """带默认配置的 tqdm 进度条"""
    return tqdm(
        iterable,
        desc=desc,
        total=total,
        ncols=100,
        unit="it",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 环境检查
# ---------------------------------------------------------------------------

def check_env() -> None:
    """
    检查运行环境是否满足 V14-B 要求。
    打印检查结果。
    """
    import platform
    import importlib

    print("=" * 60)
    print("V14-B 环境检查")
    print("=" * 60)

    # Python 版本
    py_ver = sys.version_info
    ok = py_ver >= (3, 11)
    print(f"{'✅' if ok else '❌'} Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} "
          f"(需要 >= 3.11)")

    # 操作系统
    is_mac = platform.system() == "Darwin"
    arch = platform.machine()
    is_arm = arch in ("arm64", "aarch64")
    print(f"{'✅' if is_mac else '⚠️'} 操作系统: {platform.system()} {arch}")
    if is_mac and is_arm:
        print("  ✅ Apple Silicon 检测到")

    # PyTorch + MPS
    try:
        import torch
        mps_avail = torch.backends.mps.is_available()
        print(f"✅ PyTorch {torch.__version__}")
        print(f"{'✅' if mps_avail else '⚠️'} MPS {'可用' if mps_avail else '不可用 (将使用 CPU)'}")
    except ImportError:
        print("❌ PyTorch 未安装 (pip install torch)")

    # 关键包检查
    packages = [
        "networkx", "sklearn", "numpy", "pandas",
        "torch_geometric", "transformers", "sentence_transformers",
        "umap", "tqdm", "pydantic", "pyalex",
    ]
    for pkg in packages:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            print(f"  ✅ {pkg} {ver}")
        except ImportError:
            print(f"  ❌ {pkg} 未安装")

    # LLM provider
    provider = os.environ.get("LLM_PROVIDER", "(未设置)")
    print(f"\nLLM_PROVIDER: {provider}")
    if provider == "anthropic":
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        print(f"{'✅' if has_key else '❌'} ANTHROPIC_API_KEY {'已设置' if has_key else '未设置'}")
    elif provider == "openai":
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        print(f"{'✅' if has_key else '❌'} OPENAI_API_KEY {'已设置' if has_key else '未设置'}")
    elif provider == "ollama":
        url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        print(f"  OLLAMA_BASE_URL: {url}")

    # 数据库检查
    from echelon.v14b.config import DB_MAIN, DB_V14
    if DB_MAIN.exists():
        size_mb = DB_MAIN.stat().st_size / 1024 / 1024
        print(f"\n✅ DB: {DB_MAIN} ({size_mb:.1f} MB)")
    else:
        print(f"\n❌ DB 未找到: {DB_MAIN}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# 通用 CLI 参数解析
# ---------------------------------------------------------------------------

def add_common_args(parser) -> None:
    """
    向 argparse.ArgumentParser 添加所有 step 共用参数。

    Args:
        parser: ArgumentParser 实例
    """
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite 数据库路径 (默认: config.DB_MAIN)",
    )
    parser.add_argument(
        "--db-v14",
        type=Path,
        default=None,
        help="V14 结果数据库路径 (默认: config.DB_V14)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 条 (调试用)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="从 checkpoint 续跑 (默认启用)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="忽略 checkpoint,强制重跑",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="并发数 (默认: config.CONCURRENCY)",
    )


# ---------------------------------------------------------------------------
# 设备选择 (MPS / CPU)
# ---------------------------------------------------------------------------

def get_torch_device() -> "torch.device":
    """
    自动选择 PyTorch 设备。

    返回优先级: MPS > CPU (无 CUDA,只支持 Apple Silicon)
    """
    import torch
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# 日期工具
# ---------------------------------------------------------------------------

def year_to_z(year: int, year_min: int = 1991, year_max: int = 2026) -> float:
    """将出版年份映射到 Z 坐标 [0, 1]"""
    if year_max == year_min:
        return 0.5
    return max(0.0, min(1.0, (year - year_min) / (year_max - year_min)))


def str_to_year(date_str: str | None) -> int | None:
    """从 YYYY-MM-DD 字符串提取年份"""
    if not date_str:
        return None
    try:
        return int(str(date_str)[:4])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="V14-B 环境检查工具"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="check_env",
        choices=["check_env"],
    )
    args = parser.parse_args()

    if args.command == "check_env":
        check_env()
