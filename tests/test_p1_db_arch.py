"""
P1-A 数据库与架构修复单元测试 (8条 AUDIT)
==========================================

[修订自 AUDIT-027/030/031/032/055/079/081/082]

运行: pytest tests/test_p1_db_arch.py -v
"""

import os
import sys
import json
import tempfile
import math
from datetime import date, datetime, timezone
from decimal import Decimal

# 确保 echelon 包可以被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ============================================================================
# AUDIT-027: node_metric_history 纵表 + snapshot_year 分区
# ============================================================================

class TestNodeMetricHistory:
    """AUDIT-027: JSONB MVCC tuple bloat → 纵表拆分"""

    def test_make_row_basic(self):
        """make_row 正常创建行记录"""
        from echelon.schema.node_metric_history import make_row

        row = make_row(
            node_id="NODE_001",
            metric_name="bridging_centrality",
            metric_value=0.75,
            snapshot_date=date(2024, 6, 15),
        )
        assert row.node_id == "NODE_001"
        assert row.metric_name == "bridging_centrality"
        assert float(row.metric_value) == pytest.approx(0.75)
        assert row.snapshot_date == date(2024, 6, 15)
        assert row.snapshot_year == 2024

    def test_snapshot_year_derived_from_date(self):
        """snapshot_year 必须与 snapshot_date.year 一致"""
        from echelon.schema.node_metric_history import NodeMetricHistoryRow
        from echelon.core.ulid_utils import ulid_new

        # 正常:year 一致
        row = NodeMetricHistoryRow(
            id=ulid_new(),
            node_id="N1",
            metric_name="pagerank",
            metric_value=Decimal("0.123"),
            snapshot_date=date(2023, 1, 1),
            snapshot_year=2023,
        )
        assert row.snapshot_year == 2023

        # 异常:year 不一致
        with pytest.raises(ValueError, match="snapshot_year"):
            NodeMetricHistoryRow(
                id=ulid_new(),
                node_id="N1",
                metric_name="pagerank",
                metric_value=Decimal("0.123"),
                snapshot_date=date(2023, 1, 1),
                snapshot_year=2024,  # ← 不一致
            )

    def test_make_row_string_date(self):
        """snapshot_date 可以是 ISO 字符串"""
        from echelon.schema.node_metric_history import make_row

        row = make_row(
            node_id="N2",
            metric_name="cited_by_count",
            metric_value=100,
            snapshot_date="2025-03-01",
        )
        assert row.snapshot_date == date(2025, 3, 1)
        assert row.snapshot_year == 2025

    def test_decimal_precision(self):
        """metric_value 使用 Decimal,不丢失精度"""
        from echelon.schema.node_metric_history import make_row

        row = make_row(
            node_id="N3",
            metric_name="convergence_score",
            metric_value=Decimal("0.123456789012345"),
            snapshot_date=date(2024, 1, 1),
        )
        # Decimal 保留精度,不被 float 截断
        assert isinstance(row.metric_value, Decimal)
        assert str(row.metric_value).startswith("0.12345")

    def test_sqlite_insert_and_query(self):
        """SQLite 插入和查询功能"""
        from echelon.schema.node_metric_history import (
            make_row, insert_row_sqlite, query_node_metrics_sqlite,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            row1 = make_row("NODE_X", "pagerank", 0.5, "2024-01-01", run_id="run_001")
            row2 = make_row("NODE_X", "degree_centrality", 0.3, "2024-06-01")
            insert_row_sqlite(row1, db_path)
            insert_row_sqlite(row2, db_path)

            # 按 node_id + metric_name 查询
            results = query_node_metrics_sqlite("NODE_X", "pagerank", db_path)
            assert len(results) == 1
            assert results[0]["metric_name"] == "pagerank"
            assert results[0]["run_id"] == "run_001"

            # 按 node_id 查询全部
            all_rows = query_node_metrics_sqlite("NODE_X", None, db_path)
            assert len(all_rows) == 2
        finally:
            os.unlink(db_path)

    def test_ddl_contains_partition_comment(self):
        """DDL 字符串包含分区相关注释"""
        from echelon.schema.node_metric_history import NODE_METRIC_HISTORY_DDL_PG

        assert "PARTITION BY RANGE" in NODE_METRIC_HISTORY_DDL_PG
        assert "snapshot_year" in NODE_METRIC_HISTORY_DDL_PG


# ============================================================================
# AUDIT-030: Merge/Split API quota ≤10/小时/expert
# ============================================================================

class TestMergeQuotaTracker:
    """AUDIT-030: Merge/Split API quota 控制"""

    def _make_tracker(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        return db_path

    def test_basic_consume_and_remaining(self):
        """基本 quota 消耗与剩余查询"""
        from echelon.core.async_task_quota import MergeQuotaTracker

        db_path = self._make_tracker()
        try:
            tracker = MergeQuotaTracker(db_path=db_path, quota_per_hour=5)
            assert tracker.get_remaining("expert_A") == 5

            assert tracker.check_and_consume("expert_A") is True
            assert tracker.get_remaining("expert_A") == 4

            assert tracker.check_and_consume("expert_A") is True
            assert tracker.get_remaining("expert_A") == 3
        finally:
            os.unlink(db_path)

    def test_quota_exhausted(self):
        """超出 quota 后返回 False"""
        from echelon.core.async_task_quota import MergeQuotaTracker

        db_path = self._make_tracker()
        try:
            tracker = MergeQuotaTracker(db_path=db_path, quota_per_hour=3)

            for i in range(3):
                ok = tracker.check_and_consume("expert_B")
                assert ok is True, f"第{i+1}次应成功"

            # 第 4 次应被拒
            assert tracker.check_and_consume("expert_B") is False
            assert tracker.get_remaining("expert_B") == 0
        finally:
            os.unlink(db_path)

    def test_quota_isolation_between_experts(self):
        """不同 expert 的 quota 互不影响"""
        from echelon.core.async_task_quota import MergeQuotaTracker

        db_path = self._make_tracker()
        try:
            tracker = MergeQuotaTracker(db_path=db_path, quota_per_hour=2)
            tracker.check_and_consume("expert_A")
            tracker.check_and_consume("expert_A")
            assert tracker.check_and_consume("expert_A") is False

            # expert_B 未受影响
            assert tracker.get_remaining("expert_B") == 2
            assert tracker.check_and_consume("expert_B") is True
        finally:
            os.unlink(db_path)

    def test_reset_quota(self):
        """reset_quota 清除记录后可重新使用"""
        from echelon.core.async_task_quota import MergeQuotaTracker

        db_path = self._make_tracker()
        try:
            tracker = MergeQuotaTracker(db_path=db_path, quota_per_hour=1)
            tracker.check_and_consume("expert_C")
            assert tracker.check_and_consume("expert_C") is False

            tracker.reset_quota("expert_C")
            assert tracker.get_remaining("expert_C") == 1
            assert tracker.check_and_consume("expert_C") is True
        finally:
            os.unlink(db_path)

    def test_default_quota_is_10(self):
        """默认 quota = 10 次/小时"""
        from echelon.core.async_task_quota import MERGE_QUOTA_PER_HOUR
        assert MERGE_QUOTA_PER_HOUR == 10


# ============================================================================
# AUDIT-031: Split 触发节点 0 重新解析
# ============================================================================

class TestHandleGraphSplit:
    """AUDIT-031: Split 操作触发子论文重新解析"""

    def test_handle_graph_split_basic(self):
        """handle_graph_split 返回 PENDING 状态 ReparseTask"""
        from echelon.pdf.handle_graph_split import (
            handle_graph_split, ChildPaperRef, ReparseStatus,
        )

        children = [
            ChildPaperRef(child_id="CHILD_1", title="子论文A", abstract="摘要A"),
            ChildPaperRef(child_id="CHILD_2", title="子论文B", abstract="摘要B"),
        ]
        task = handle_graph_split("PARENT_001", children)

        assert task.parent_id == "PARENT_001"
        assert task.status == ReparseStatus.PENDING
        assert len(task.child_papers) == 2
        assert task.task_id  # 非空

    def test_handle_graph_split_dict_input(self):
        """handle_graph_split 接受 dict 格式输入"""
        from echelon.pdf.handle_graph_split import handle_graph_split

        children = [{"child_id": "C1", "abstract": "abstract text"}]
        task = handle_graph_split("P1", children)
        assert task.child_papers[0].child_id == "C1"

    def test_handle_graph_split_empty_children_raises(self):
        """空 child_papers 应抛出 ValueError"""
        from echelon.pdf.handle_graph_split import handle_graph_split

        with pytest.raises(ValueError, match="empty"):
            handle_graph_split("PARENT_X", [])

    def test_handle_graph_split_empty_parent_raises(self):
        """空 parent_id 应抛出 ValueError"""
        from echelon.pdf.handle_graph_split import handle_graph_split, ChildPaperRef

        with pytest.raises(ValueError, match="parent_id"):
            handle_graph_split("", [ChildPaperRef(child_id="C1")])

    def test_reparse_as_child_paper_with_evidence(self):
        """reparse_as_child_paper 正常返回结果"""
        from echelon.pdf.handle_graph_split import reparse_as_child_paper

        result = reparse_as_child_paper("CHILD_1", "This is abstract text about optics.")
        assert result["child_id"] == "CHILD_1"
        assert result["status"] == "ok"
        assert result["source"] == "abstract"
        assert "optics" in result["evidence_text"]

    def test_reparse_as_child_paper_empty_evidence(self):
        """空 parent_evidence 返回 empty status"""
        from echelon.pdf.handle_graph_split import reparse_as_child_paper

        result = reparse_as_child_paper("CHILD_2", None)
        assert result["status"] == "empty"
        assert result["evidence_text"] == ""

    def test_reparse_as_child_paper_truncation(self):
        """超长 evidence 被截断为 2000 字符"""
        from echelon.pdf.handle_graph_split import reparse_as_child_paper

        long_text = "x" * 5000
        result = reparse_as_child_paper("CHILD_3", long_text)
        assert len(result["evidence_text"]) == 2000

    def test_run_reparse_task(self):
        """run_reparse_task 执行完整流程"""
        from echelon.pdf.handle_graph_split import (
            handle_graph_split, run_reparse_task, ChildPaperRef, ReparseStatus,
        )

        children = [
            ChildPaperRef(child_id="C1", abstract="Abstract A"),
            ChildPaperRef(child_id="C2", abstract="Abstract B"),
        ]
        task = handle_graph_split("P_PARENT", children)
        done_task = run_reparse_task(task)

        assert done_task.status == ReparseStatus.DONE
        assert len(done_task.reparse_results) == 2
        assert done_task.finished_at is not None


# ============================================================================
# AUDIT-032: 幂等键 parser_compat_hash
# ============================================================================

class TestParserCompatHash:
    """AUDIT-032: parser_version → parser_compat_hash"""

    def test_compute_parser_compat_hash_deterministic(self):
        """相同输入 → 相同哈希(幂等)"""
        from echelon.core.parser_compat import compute_parser_compat_hash

        h1 = compute_parser_compat_hash("pdfplumber", "0.10.3", "2.1.0")
        h2 = compute_parser_compat_hash("pdfplumber", "0.10.3", "2.1.0")
        assert h1 == h2

    def test_hash_length_16(self):
        """哈希长度为 16 hex 字符(64 bits)"""
        from echelon.core.parser_compat import compute_parser_compat_hash

        h = compute_parser_compat_hash("grobid", "0.8.0", "2.1.0")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_version_change_changes_hash(self):
        """parser_version 变化 → hash 变化"""
        from echelon.core.parser_compat import compute_parser_compat_hash

        h1 = compute_parser_compat_hash("spacy", "3.7.2", "2.0.0")
        h2 = compute_parser_compat_hash("spacy", "3.7.3", "2.0.0")  # patch 变化
        assert h1 != h2

    def test_schema_version_change_changes_hash(self):
        """schema_version 变化 → hash 变化"""
        from echelon.core.parser_compat import compute_parser_compat_hash

        h1 = compute_parser_compat_hash("regex_evidence", "2.3.1", "2.0.0")
        h2 = compute_parser_compat_hash("regex_evidence", "2.3.1", "2.1.0")
        assert h1 != h2

    def test_registered_parsers_all_present(self):
        """5 个内置 parser 都在注册表中"""
        from echelon.core.parser_compat import PARSER_REGISTRY

        expected = {"pdfplumber", "grobid", "sentence_split", "regex_evidence", "spacy"}
        assert expected.issubset(set(PARSER_REGISTRY.keys()))

    def test_get_registered_hash(self):
        """get_registered_hash 返回非空 16 字符哈希"""
        from echelon.core.parser_compat import get_registered_hash

        for name in ["pdfplumber", "grobid", "sentence_split", "regex_evidence", "spacy"]:
            h = get_registered_hash(name)
            assert len(h) == 16, f"parser {name!r} hash length != 16"

    def test_get_registered_hash_unknown_raises(self):
        """未注册 parser 抛出 KeyError"""
        from echelon.core.parser_compat import get_registered_hash

        with pytest.raises(KeyError):
            get_registered_hash("nonexistent_parser")

    def test_register_new_parser(self):
        """动态注册新 parser"""
        from echelon.core.parser_compat import register_parser, get_registered_hash

        h = register_parser("test_parser", "1.0.0", "1.0.0", "测试 parser")
        assert len(h) == 16
        assert get_registered_hash("test_parser") == h

    def test_empty_args_raise(self):
        """空参数抛出 ValueError"""
        from echelon.core.parser_compat import compute_parser_compat_hash

        with pytest.raises(ValueError):
            compute_parser_compat_hash("", "1.0", "1.0")
        with pytest.raises(ValueError):
            compute_parser_compat_hash("parser", "", "1.0")
        with pytest.raises(ValueError):
            compute_parser_compat_hash("parser", "1.0", "")


# ============================================================================
# AUDIT-055: canonical_json 浮点 .6g 截断
# ============================================================================

class TestCanonicalJson:
    """AUDIT-055: canonical_json 浮点精度 + 幂等"""

    def test_float_ieee754_avalanche_fixed(self):
        """0.1+0.2 ≈ 0.3:规范化后哈希一致"""
        from echelon.core.canonical_json import canonical_dumps

        a = canonical_dumps({"x": 0.1 + 0.2})
        b = canonical_dumps({"x": 0.30000000000000004})
        # 两者 .6g 格式化后均为 0.3
        assert a == b, f"IEEE 754 雪崩未修复: {a!r} != {b!r}"

    def test_sort_keys(self):
        """dict key 按字母序排列"""
        from echelon.core.canonical_json import canonical_dumps

        result = canonical_dumps({"z": 1, "a": 2, "m": 3})
        assert result == '{"a":2,"m":3,"z":1}'

    def test_no_whitespace(self):
        """输出无额外空格"""
        from echelon.core.canonical_json import canonical_dumps

        result = canonical_dumps({"key": "value", "num": 42})
        assert " " not in result

    def test_decimal_support(self):
        """Decimal 类型正常序列化"""
        from echelon.core.canonical_json import canonical_dumps

        result = canonical_dumps({"v": Decimal("1.234567890")})
        # Decimal → float → .6g: 1.23457
        data = json.loads(result)
        assert abs(data["v"] - 1.23457) < 1e-4

    def test_nested_structure(self):
        """嵌套 dict/list 正常处理"""
        from echelon.core.canonical_json import canonical_dumps

        data = {"list": [1.1, 2.2, 3.3], "nested": {"a": 0.1 + 0.2}}
        result = canonical_dumps(data)
        parsed = json.loads(result)
        assert len(parsed["list"]) == 3

    def test_nan_inf_become_null(self):
        """NaN/Inf 序列化为 null"""
        from echelon.core.canonical_json import canonical_dumps

        result = canonical_dumps({"nan": float("nan"), "inf": float("inf")})
        parsed = json.loads(result)
        assert parsed["nan"] is None
        assert parsed["inf"] is None

    def test_bool_not_treated_as_int(self):
        """bool 不被当作 int 处理"""
        from echelon.core.canonical_json import canonical_dumps

        result = canonical_dumps({"flag": True, "zero": False})
        parsed = json.loads(result)
        assert parsed["flag"] is True
        assert parsed["zero"] is False

    def test_canonical_hash_deterministic(self):
        """canonical_hash 对相同数据返回相同结果"""
        from echelon.core.canonical_json import canonical_hash

        h1 = canonical_hash({"score": 0.1 + 0.2, "label": "test"})
        h2 = canonical_hash({"label": "test", "score": 0.3})
        assert h1 == h2

    def test_float_6g_precision(self):
        """.6g 格式化精度验证"""
        from echelon.core.canonical_json import canonical_dumps

        # 1.23456789 → 1.23457 (6位有效数字)
        result = canonical_dumps(1.23456789)
        parsed = json.loads(result)
        assert f"{parsed:.6g}" == f"{1.23457:.6g}"


# ============================================================================
# AUDIT-079: EdgeOverride 删除后 load_edge 报 404 修复
# ============================================================================

class TestEdgeOverride:
    """AUDIT-079: EdgeOverride 软删除 + audit_log 回溯"""

    def _make_store(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        from echelon.graph.edge_override import EdgeOverrideStore
        return EdgeOverrideStore(db_path=db_path), db_path

    def test_add_and_load_live_edge(self):
        """ADD 操作后可正常 load"""
        from echelon.graph.edge_override import EdgeRecord, EdgeAction

        store, db_path = self._make_store()
        try:
            edge = EdgeRecord(edge_id="E1", source_id="A", target_id="B")
            store.apply_edge_override(EdgeAction.ADD, edge)
            record = store.load_edge_with_audit_fallback("E1")
            assert record["source_id"] == "A"
            assert record["target_id"] == "B"
            assert record["_source"] == "live"
            assert record["is_deleted"] is False
        finally:
            os.unlink(db_path)

    def test_delete_then_fallback_to_audit_log(self):
        """DELETE 后 load_edge 从 audit_log 恢复 source/target"""
        from echelon.graph.edge_override import EdgeRecord, EdgeAction

        store, db_path = self._make_store()
        try:
            edge = EdgeRecord(edge_id="E2", source_id="SRC", target_id="TGT")
            store.apply_edge_override(EdgeAction.ADD, edge)
            store.apply_edge_override(EdgeAction.DELETE, edge)

            # 不应抛 404,应从 audit_log 恢复
            record = store.load_edge_with_audit_fallback("E2")
            assert record["source_id"] == "SRC"
            assert record["target_id"] == "TGT"
            assert record["is_deleted"] is True
            assert record["_source"] == "audit_log"
        finally:
            os.unlink(db_path)

    def test_load_nonexistent_raises_key_error(self):
        """不存在的边抛出 KeyError"""
        store, db_path = self._make_store()
        try:
            with pytest.raises(KeyError):
                store.load_edge_with_audit_fallback("NONEXISTENT_EDGE")
        finally:
            os.unlink(db_path)

    def test_audit_log_written_on_delete(self):
        """DELETE 操作写入 audit_log"""
        from echelon.graph.edge_override import EdgeRecord, EdgeAction

        store, db_path = self._make_store()
        try:
            edge = EdgeRecord(edge_id="E3", source_id="X", target_id="Y")
            store.apply_edge_override(EdgeAction.ADD, edge, operator_id="op_001")
            store.apply_edge_override(EdgeAction.DELETE, edge, operator_id="op_002")

            logs = store.get_audit_log("E3")
            assert len(logs) == 2
            assert logs[0]["action"] == "add"
            assert logs[1]["action"] == "delete"
            assert logs[0]["operator_id"] == "op_001"
        finally:
            os.unlink(db_path)

    def test_update_edge(self):
        """UPDATE 操作更新边属性"""
        from echelon.graph.edge_override import EdgeRecord, EdgeAction

        store, db_path = self._make_store()
        try:
            edge = EdgeRecord(edge_id="E4", source_id="A", target_id="B", weight=1.0)
            store.apply_edge_override(EdgeAction.ADD, edge)

            updated = EdgeRecord(edge_id="E4", source_id="A", target_id="B", weight=2.5)
            store.apply_edge_override(EdgeAction.UPDATE, updated)

            record = store.load_edge_with_audit_fallback("E4")
            assert abs(record["weight"] - 2.5) < 1e-9
            assert record["is_deleted"] is False
        finally:
            os.unlink(db_path)

    def test_module_level_functions(self):
        """模块级便捷函数正常工作"""
        from echelon.graph.edge_override import (
            apply_edge_override, load_edge_with_audit_fallback,
            EdgeRecord, EdgeAction,
        )

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            edge = EdgeRecord(edge_id="E5", source_id="S", target_id="T")
            apply_edge_override(EdgeAction.ADD, edge, db_path=db_path)
            rec = load_edge_with_audit_fallback("E5", db_path=db_path)
            assert rec["source_id"] == "S"
        finally:
            os.unlink(db_path)


# ============================================================================
# AUDIT-081: 撤稿增量级联
# ============================================================================

class TestRetractionCheck:
    """AUDIT-081: 撤稿增量检查与级联失效"""

    def test_cascade_invalidate_marks_paper(self):
        """cascade_invalidate 将论文标记为 is_retracted=1"""
        from echelon.ingest.retraction_check import cascade_invalidate

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            result = cascade_invalidate("PAPER_RETRACTED_001", db_path=db_path)
            assert result["paper_updated"] is True
            assert result["paper_id"] == "PAPER_RETRACTED_001"
            assert result["alert_written"] is True
        finally:
            os.unlink(db_path)

    def test_cascade_invalidate_creates_alert(self):
        """cascade_invalidate 写入专家告警"""
        from echelon.ingest.retraction_check import (
            cascade_invalidate, get_retraction_alerts,
        )

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            cascade_invalidate("PAPER_X", db_path=db_path)
            alerts = get_retraction_alerts(db_path=db_path)
            assert len(alerts) >= 1
            assert alerts[0]["paper_id"] == "PAPER_X"
            assert alerts[0]["alert_type"] == "retraction"
            assert alerts[0]["acknowledged"] == 0
        finally:
            os.unlink(db_path)

    def test_weekly_retraction_check_no_changes(self):
        """没有撤稿变化时 newly_retracted 为空"""
        from echelon.ingest.retraction_check import (
            weekly_retraction_check, CorpusPaperRef,
        )
        from datetime import date, timedelta

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            recent_date = (date.today() - timedelta(days=30)).isoformat()
            papers = [
                CorpusPaperRef(
                    paper_id=f"P{i}",
                    is_retracted=False,
                    publication_date=recent_date,
                )
                for i in range(5)
            ]
            result = weekly_retraction_check(papers, db_path=db_path)
            assert result["newly_retracted"] == []
            assert result["checked_count"] == 5
        finally:
            os.unlink(db_path)

    def test_weekly_retraction_check_detects_new_retraction(self):
        """fetcher_fn 返回 True 时触发级联失效"""
        from echelon.ingest.retraction_check import (
            weekly_retraction_check, CorpusPaperRef,
        )
        from datetime import date, timedelta

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            recent_date = (date.today() - timedelta(days=60)).isoformat()
            # 模拟论文当前 is_retracted=False,但外部 API 返回 True
            papers = [
                CorpusPaperRef(
                    paper_id="NEWLY_RETRACTED",
                    is_retracted=False,
                    publication_date=recent_date,
                )
            ]
            # fetcher_fn 模拟最新状态为 True
            def mock_fetcher(paper):
                return True

            result = weekly_retraction_check(
                papers, db_path=db_path, fetcher_fn=mock_fetcher
            )
            assert "NEWLY_RETRACTED" in result["newly_retracted"]
        finally:
            os.unlink(db_path)

    def test_weekly_check_window_filters_old_papers(self):
        """1 年以外的论文不纳入检查"""
        from echelon.ingest.retraction_check import (
            weekly_retraction_check, CorpusPaperRef,
        )

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            old_paper = CorpusPaperRef(
                paper_id="OLD_PAPER",
                is_retracted=False,
                publication_date="2010-01-01",  # 远超 1 年
            )
            result = weekly_retraction_check([old_paper], db_path=db_path)
            # 旧论文被过滤,checked_count=0
            assert result["checked_count"] == 0
        finally:
            os.unlink(db_path)

    def test_dict_input(self):
        """支持 dict 格式论文输入"""
        from echelon.ingest.retraction_check import weekly_retraction_check
        from datetime import date, timedelta

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            recent_date = (date.today() - timedelta(days=30)).isoformat()
            papers = [{"paper_id": "P_DICT", "is_retracted": False, "publication_date": recent_date}]
            result = weekly_retraction_check(papers, db_path=db_path)
            assert result["checked_count"] == 1
        finally:
            os.unlink(db_path)


# ============================================================================
# AUDIT-082: PDF 优先级 arXiv > Unpaywall > Crossref
# ============================================================================

class TestPdfSourcePriority:
    """AUDIT-082: PDF 来源优先级选择"""

    def test_arxiv_from_source_url(self):
        """source_url 含 arxiv.org → 返回 arXiv PDF URL"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": "https://arxiv.org/abs/2312.00001",
            "doi": "10.1000/xyz",
        }
        url = select_pdf_source(paper)
        assert url is not None
        assert "arxiv.org/pdf" in url
        assert "2312.00001" in url

    def test_arxiv_from_doi(self):
        """DOI 含 arXiv 标识 → 返回 arXiv PDF URL"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": None,
            "doi": "10.48550/arXiv.2312.00002",
        }
        url = select_pdf_source(paper)
        assert url is not None
        assert "arxiv.org/pdf" in url

    def test_arxiv_priority_over_doi_crossref(self):
        """arXiv 优先于 Crossref"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": "https://arxiv.org/abs/2401.12345",
            "doi": "10.1000/journal.123",
            "extra": {},
        }
        url = select_pdf_source(paper)
        assert "arxiv.org" in url

    def test_unpaywall_url_from_extra(self):
        """extra.unpaywall_url 优先于 Crossref"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": None,
            "doi": "10.1000/xyz",
            "extra": {"unpaywall_url": "https://oa.example.com/paper.pdf"},
        }
        url = select_pdf_source(paper)
        assert url == "https://oa.example.com/paper.pdf"

    def test_crossref_fallback(self):
        """无 arXiv/Unpaywall 时降级到 Crossref DOI URL"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": "https://example.com/normal",
            "doi": "10.1000/xyz",
            "extra": {},
        }
        url = select_pdf_source(paper)
        assert url is not None
        assert "doi.org/10.1000/xyz" in url

    def test_no_source_returns_none(self):
        """无任何来源信息 → 返回 None"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": None,
            "doi": None,
            "extra": {},
        }
        url = select_pdf_source(paper)
        assert url is None

    def test_priority_constants(self):
        """优先级常量:arXiv=1 < Unpaywall=2 < Crossref=3"""
        from echelon.ingest.pdf_source_priority import PDF_SOURCE_PRIORITY

        assert PDF_SOURCE_PRIORITY["arxiv"] == 1
        assert PDF_SOURCE_PRIORITY["unpaywall"] == 2
        assert PDF_SOURCE_PRIORITY["crossref"] == 3
        assert PDF_SOURCE_PRIORITY["arxiv"] < PDF_SOURCE_PRIORITY["unpaywall"]
        assert PDF_SOURCE_PRIORITY["unpaywall"] < PDF_SOURCE_PRIORITY["crossref"]

    def test_batch_processing(self):
        """批量处理返回正确结构"""
        from echelon.ingest.pdf_source_priority import select_pdf_sources_batch

        papers = [
            {"id": "P1", "source_url": "https://arxiv.org/abs/2312.00001", "doi": None, "extra": {}},
            {"id": "P2", "source_url": None, "doi": "10.1000/xyz", "extra": {}},
            {"id": "P3", "source_url": None, "doi": None, "extra": {}},
        ]
        results = select_pdf_sources_batch(papers)
        assert len(results) == 3
        assert results[0]["source"] == "arxiv"
        assert results[2]["pdf_url"] is None

    def test_paper_object_interface(self):
        """支持具有 .source_url / .doi 属性的对象"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        class FakePaper:
            source_url = "https://arxiv.org/abs/2401.99999"
            doi = "10.1000/fake"
            openalex_id = None
            extra = {}

        url = select_pdf_source(FakePaper())
        assert "arxiv.org/pdf" in url

    def test_arxiv_id_from_extra(self):
        """extra.arxiv_id 字段可作为 arXiv 来源"""
        from echelon.ingest.pdf_source_priority import select_pdf_source

        paper = {
            "source_url": None,
            "doi": None,
            "extra": {"arxiv_id": "2312.99999"},
        }
        url = select_pdf_source(paper)
        assert url is not None
        assert "2312.99999" in url
