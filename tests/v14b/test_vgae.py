"""
tests/v14b/test_vgae.py

VGAE 前向 + 训练 1 epoch 测试
"""
import pytest
import numpy as np


def check_torch_geometric():
    try:
        import torch
        import torch_geometric
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not check_torch_geometric(),
    reason="torch_geometric not installed"
)


class TestVGAEModel:
    def test_build_vgae_returns_model(self):
        from echelon.v14b.step5b_vgae import build_vgae_model
        model, device = build_vgae_model(input_dim=16)
        if model is None:
            pytest.skip("torch_geometric not available")
        assert model is not None
        assert device is not None

    def test_vgae_forward_pass(self):
        """VGAE 前向传播不崩溃"""
        import torch
        from torch_geometric.data import Data
        from echelon.v14b.step5b_vgae import build_vgae_model

        model, device = build_vgae_model(input_dim=16)
        if model is None:
            pytest.skip("torch_geometric not available")

        # 小图: 10 节点, 8 边
        n_nodes = 10
        x = torch.randn(n_nodes, 16, device=device)
        edges = torch.tensor([
            [0, 1, 2, 3, 4, 5, 6, 7],
            [1, 2, 3, 4, 5, 6, 7, 8]
        ], dtype=torch.long, device=device)

        model.eval()
        with torch.no_grad():
            z = model.encode(x, edges)
            assert z.shape == (n_nodes, 128)  # VGAE_LATENT_DIM

    def test_vgae_latent_shape(self):
        """VGAE 潜在向量形状正确"""
        import torch
        from echelon.v14b.step5b_vgae import build_vgae_model
        from echelon.v14b.config import VGAE_LATENT_DIM

        model, device = build_vgae_model(input_dim=32)
        if model is None:
            pytest.skip()

        n = 8
        x = torch.randn(n, 32, device=device)
        edges = torch.tensor([[0, 1, 2], [1, 2, 3]], dtype=torch.long, device=device)

        model.eval()
        with torch.no_grad():
            z = model.encode(x, edges)
            assert z.shape[0] == n
            assert z.shape[1] == VGAE_LATENT_DIM

    def test_vgae_recon_loss_positive(self):
        """重建损失应为正数"""
        import torch
        from echelon.v14b.step5b_vgae import build_vgae_model

        model, device = build_vgae_model(input_dim=16)
        if model is None:
            pytest.skip()

        x = torch.randn(8, 16, device=device)
        edges = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long, device=device)

        model.train()
        z = model.encode(x, edges)
        loss = model.recon_loss(z, edges)
        assert float(loss) >= 0

    def test_node_features_shape(self):
        """节点特征矩阵形状正确"""
        from echelon.v14b.config import VGAE_INPUT_DIM
        import sqlite3
        import tempfile

        # 创建最小测试 DB
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            db_path = Path(tmp) / "test.sqlite3"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE papers (
                    id INTEGER PRIMARY KEY,
                    publication_year INTEGER,
                    cited_by_count INTEGER,
                    keystone_score_v14 REAL,
                    primary_field_id INTEGER
                );
            """)
            for i in range(1, 6):
                conn.execute(
                    "INSERT INTO papers VALUES (?, ?, ?, ?, ?)",
                    (i, 2020 + i, i * 10, 0.5, i % 5)
                )
            conn.commit()

            from echelon.v14b.step5b_vgae import build_node_features
            from echelon.v14b.db_schema import init_v14b_db
            db_v14 = Path(tmp) / "v14.sqlite3"
            conn_v14 = init_v14b_db(db_v14)

            node_ids = [1, 2, 3, 4, 5]
            features = build_node_features(conn, conn_v14, node_ids)
            conn.close()
            conn_v14.close()

            assert features.shape == (5, VGAE_INPUT_DIM)
            assert not np.any(np.isnan(features))


class TestVGAETraining:
    def test_training_one_epoch(self):
        """VGAE 训练 1 epoch 不崩溃"""
        import torch
        from echelon.v14b.step5b_vgae import build_vgae_model
        from echelon.v14b.config import VGAE_LR, VGAE_BETA

        model, device = build_vgae_model(input_dim=16)
        if model is None:
            pytest.skip("torch_geometric not available")

        from torch_geometric.utils import train_test_split_edges
        from torch_geometric.data import Data

        n = 20
        x = torch.randn(n, 16, device=device)
        edge_list = [[i, i + 1] for i in range(n - 1)]
        edge_index = torch.tensor(edge_list, dtype=torch.long).t().contiguous().to(device)
        data = Data(x=x, edge_index=edge_index, num_nodes=n)
        data = train_test_split_edges(data, val_ratio=0.1, test_ratio=0.1)

        optimizer = torch.optim.Adam(model.parameters(), lr=VGAE_LR)

        model.train()
        optimizer.zero_grad()
        z = model.encode(data.x, data.train_pos_edge_index)
        loss = model.recon_loss(z, data.train_pos_edge_index)
        kl = VGAE_BETA * (1 / n) * model.kl_loss()
        total = loss + kl
        total.backward()
        optimizer.step()

        assert float(total) > 0
        assert not torch.isnan(total)
