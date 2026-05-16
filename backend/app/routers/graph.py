"""GET /graph — return the knowledge graph (or a per-document subgraph)
as JSON for the frontend force-directed renderer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth_deps import get_current_user
from app.schemas import GraphEdgeOut, GraphNodeOut, GraphResponse
from app.services import graph as graph_service

router = APIRouter(
    prefix="/graph",
    tags=["graph"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=GraphResponse)
def get_graph(
    document_id: int | None = Query(
        default=None,
        description=(
            "Restrict to entities present in this document. If omitted, the "
            "full corpus-wide graph is returned."
        ),
    ),
) -> GraphResponse:
    try:
        payload = graph_service.read_graph(document_id=document_id)
    except Exception as exc:  # noqa: BLE001 — Neo4j unreachable is common in dev
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"graph unavailable: {type(exc).__name__}: {exc}",
        ) from exc
    return GraphResponse(
        nodes=[
            GraphNodeOut(name=n.name, type=n.type, document_ids=n.document_ids)
            for n in payload.nodes
        ],
        edges=[
            GraphEdgeOut(
                head=e.head, label=e.label, tail=e.tail, document_ids=e.document_ids
            )
            for e in payload.edges
        ],
    )
