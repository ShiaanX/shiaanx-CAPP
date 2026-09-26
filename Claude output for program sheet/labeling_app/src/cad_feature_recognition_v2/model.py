"""PyTorch models for MFCAD++ face feature recognition."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
import torch.nn.functional as F

from .h5_data import H5GraphBatch


@dataclass(frozen=True)
class TorchGraphBatch:
    face_x: torch.Tensor
    labels: torch.Tensor
    face_edge_indices: list[torch.Tensor]
    face_edge_values: list[torch.Tensor]
    facet_x: torch.Tensor
    facet_edge_index: torch.Tensor
    facet_edge_values: torch.Tensor
    facet_to_face_index: torch.Tensor
    facet_to_face_values: torch.Tensor


class RelGraphConv(nn.Module):
    """Relation-aware mean aggregation graph convolution."""

    def __init__(self, in_dim: int, out_dim: int, *, num_relations: int, dropout: float) -> None:
        super().__init__()
        self.self_linear = nn.Linear(in_dim, out_dim)
        self.rel_linears = nn.ModuleList(nn.Linear(in_dim, out_dim, bias=False) for _ in range(num_relations))
        self.norm = nn.LayerNorm(out_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: torch.Tensor,
        edge_indices: list[torch.Tensor],
        edge_values: list[torch.Tensor],
    ) -> torch.Tensor:
        out = self.self_linear(x)
        node_count = x.shape[0]
        for linear, edge_index, values in zip(self.rel_linears, edge_indices, edge_values, strict=True):
            if edge_index.numel() == 0:
                continue
            dst = edge_index[:, 0]
            src = edge_index[:, 1]
            weighted = x[src] * values.unsqueeze(1)
            aggregated = x.new_zeros((node_count, x.shape[1]))
            aggregated.index_add_(0, dst, weighted)
            degree = x.new_zeros(node_count)
            degree.index_add_(0, dst, values)
            aggregated = aggregated / degree.clamp_min(1.0).unsqueeze(1)
            out = out + linear(aggregated)
        return self.dropout(F.relu(self.norm(out)))


def aggregate_mean(
    *,
    src_features: torch.Tensor,
    dst_index: torch.Tensor,
    src_index: torch.Tensor,
    values: torch.Tensor,
    dst_size: int,
) -> torch.Tensor:
    """Weighted mean aggregation from source nodes to destination nodes."""
    weighted = src_features[src_index] * values.unsqueeze(1)
    aggregated = src_features.new_zeros((dst_size, src_features.shape[1]))
    aggregated.index_add_(0, dst_index, weighted)
    degree = src_features.new_zeros(dst_size)
    degree.index_add_(0, dst_index, values)
    return aggregated / degree.clamp_min(1.0).unsqueeze(1)


class FaceRelationalGNN(nn.Module):
    """Face-only relation-aware baseline."""

    def __init__(self, *, input_dim: int, hidden_dim: int, num_classes: int, layers: int, dropout: float) -> None:
        super().__init__()
        self.layers = nn.ModuleList(
            RelGraphConv(
                in_dim=input_dim if index == 0 else hidden_dim,
                out_dim=hidden_dim,
                num_relations=3,
                dropout=dropout,
            )
            for index in range(layers)
        )
        self.classifier = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, batch: TorchGraphBatch) -> torch.Tensor:
        x = batch.face_x
        for layer in self.layers:
            next_x = layer(x, batch.face_edge_indices, batch.face_edge_values)
            x = next_x if x.shape != next_x.shape else x + next_x
        return self.classifier(x)


class HierarchicalFaceFacetGNN(nn.Module):
    """Face + mesh-facet GNN with bidirectional cross aggregation."""

    def __init__(
        self,
        *,
        face_input_dim: int,
        facet_input_dim: int,
        hidden_dim: int,
        num_classes: int,
        layers: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.face_encoder = nn.Sequential(
            nn.Linear(face_input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.facet_encoder = nn.Sequential(
            nn.Linear(facet_input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.face_layers = nn.ModuleList(
            RelGraphConv(hidden_dim, hidden_dim, num_relations=3, dropout=dropout) for _ in range(layers)
        )
        self.facet_layers = nn.ModuleList(
            RelGraphConv(hidden_dim, hidden_dim, num_relations=1, dropout=dropout) for _ in range(layers)
        )
        self.face_from_facet = nn.ModuleList(nn.Linear(hidden_dim, hidden_dim) for _ in range(layers))
        self.facet_from_face = nn.ModuleList(nn.Linear(hidden_dim, hidden_dim) for _ in range(layers))
        self.face_cross_norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(layers))
        self.facet_cross_norms = nn.ModuleList(nn.LayerNorm(hidden_dim) for _ in range(layers))
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, batch: TorchGraphBatch) -> torch.Tensor:
        face = self.face_encoder(batch.face_x)
        facet = self.facet_encoder(batch.facet_x)
        facet_index = batch.facet_to_face_index[:, 0]
        face_index = batch.facet_to_face_index[:, 1]

        for layer_index, (face_layer, facet_layer) in enumerate(zip(self.face_layers, self.facet_layers, strict=True)):
            face = face + face_layer(face, batch.face_edge_indices, batch.face_edge_values)
            facet = facet + facet_layer(facet, [batch.facet_edge_index], [batch.facet_edge_values])

            face_cross = aggregate_mean(
                src_features=facet,
                dst_index=face_index,
                src_index=facet_index,
                values=batch.facet_to_face_values,
                dst_size=face.shape[0],
            )
            facet_cross = aggregate_mean(
                src_features=face,
                dst_index=facet_index,
                src_index=face_index,
                values=batch.facet_to_face_values,
                dst_size=facet.shape[0],
            )

            face = face + self.dropout(
                F.relu(self.face_cross_norms[layer_index](self.face_from_facet[layer_index](face_cross)))
            )
            facet = facet + self.dropout(
                F.relu(self.facet_cross_norms[layer_index](self.facet_from_face[layer_index](facet_cross)))
            )

        return self.classifier(face)


def batch_to_torch(batch: H5GraphBatch, *, device: torch.device, surface_classes: int = 12) -> TorchGraphBatch:
    """Convert an HDF5 graph batch to torch tensors.

    `V_1` has four continuous face features plus a normalized OCC surface type.
    We use a one-hot surface encoding because it is a categorical signal.
    """
    raw = torch.from_numpy(batch.node_features).to(device=device, dtype=torch.float32)
    continuous = raw[:, :4]
    surface_code = torch.round(raw[:, 4] * 11).to(dtype=torch.long).clamp(min=0, max=surface_classes - 1)
    surface_one_hot = F.one_hot(surface_code, num_classes=surface_classes).to(dtype=torch.float32)
    face_x = torch.cat([continuous, surface_one_hot], dim=1)

    return TorchGraphBatch(
        face_x=face_x,
        labels=torch.from_numpy(batch.labels).to(device=device, dtype=torch.long),
        face_edge_indices=[torch.from_numpy(edge).to(device=device, dtype=torch.long) for edge in batch.edge_indices],
        face_edge_values=[torch.from_numpy(value).to(device=device, dtype=torch.float32) for value in batch.edge_values],
        facet_x=torch.from_numpy(batch.facet_features).to(device=device, dtype=torch.float32),
        facet_edge_index=torch.from_numpy(batch.facet_edge_index).to(device=device, dtype=torch.long),
        facet_edge_values=torch.from_numpy(batch.facet_edge_values).to(device=device, dtype=torch.float32),
        facet_to_face_index=torch.from_numpy(batch.facet_to_face_index).to(device=device, dtype=torch.long),
        facet_to_face_values=torch.from_numpy(batch.facet_to_face_values).to(device=device, dtype=torch.float32),
    )


def build_model(
    *,
    model_arch: str,
    input_dim: int,
    hidden_dim: int,
    layers: int,
    dropout: float,
    num_classes: int = 25,
) -> nn.Module:
    """Build a model by architecture name."""
    if model_arch == "face":
        return FaceRelationalGNN(
            input_dim=input_dim,
            hidden_dim=hidden_dim,
            num_classes=num_classes,
            layers=layers,
            dropout=dropout,
        )
    if model_arch == "hierarchical":
        return HierarchicalFaceFacetGNN(
            face_input_dim=input_dim,
            facet_input_dim=4,
            hidden_dim=hidden_dim,
            num_classes=num_classes,
            layers=layers,
            dropout=dropout,
        )
    raise ValueError(f"Unsupported model architecture: {model_arch}")

