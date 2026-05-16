import { useCallback, useEffect, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

import {
  getGraph,
  type DocumentRead,
  type GraphEdge,
  type GraphNode,
} from "./api";

// Entity-type → colour. Same set as `ALLOWED_ENTITY_TYPES` in extraction.py.
const TYPE_COLOR: Record<string, string> = {
  Person: "#0ea5e9", // sky
  Organization: "#a855f7", // purple
  Location: "#10b981", // emerald
  Concept: "#f59e0b", // amber
  Technology: "#ef4444", // red
  Product: "#6366f1", // indigo
  Event: "#ec4899", // pink
  Other: "#64748b", // slate
};

// Shape react-force-graph expects: list of nodes (with id) + list of links.
interface FGNode {
  id: string;
  type: string;
  document_ids: number[];
}
interface FGLink {
  source: string;
  target: string;
  label: string;
}

export default function GraphView({
  docs,
  onError,
}: {
  docs: DocumentRead[];
  onError: (msg: string) => void;
}) {
  const [scope, setScope] = useState<"all" | number>("all");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [hovered, setHovered] = useState<FGNode | null>(null);

  // react-force-graph mutates the data array internally (it assigns x/y/vx/vy
  // to each node). We keep our React state as the source of truth and pass a
  // shallow copy on each render so the library can scribble on its copy.
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { nodes: ns, edges: es } = await getGraph(
        scope === "all" ? null : scope,
      );
      setNodes(ns);
      setEdges(es);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [scope, onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const data = {
    nodes: nodes.map<FGNode>((n) => ({
      id: n.name,
      type: n.type,
      document_ids: n.document_ids,
    })),
    links: edges.map<FGLink>((e) => ({
      source: e.head,
      target: e.tail,
      label: e.label,
    })),
  };

  // Track the container size so the canvas fills the available width and
  // resizes when the layout reflows.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 480 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({
        width: Math.max(320, Math.floor(entry.contentRect.width)),
        height: 480,
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Knowledge graph</h2>
        <div className="flex items-center gap-3 text-sm">
          <label>
            Scope:{" "}
            <select
              value={scope}
              onChange={(e) =>
                setScope(
                  e.target.value === "all" ? "all" : Number(e.target.value),
                )
              }
              className="ml-2 rounded border border-slate-300 px-2 py-1"
            >
              <option value="all">All documents</option>
              {docs
                .filter((d) => d.status === "ready")
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
            </select>
          </label>
          <button
            onClick={() => void refresh()}
            disabled={loading}
            className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="rounded border border-slate-200 bg-white p-4">
        {nodes.length === 0 && !loading ? (
          <p className="text-sm text-slate-500">
            No entities yet. Upload a document with named entities (people,
            organisations, technologies, …) and the graph will fill in after
            the upload completes.
          </p>
        ) : (
          <div ref={containerRef} className="w-full">
            <ForceGraph2D
              graphData={data}
              width={size.width}
              height={size.height}
              nodeLabel={(n) => {
                const node = n as FGNode;
                return `${node.id} (${node.type}) · in ${node.document_ids.length} doc(s)`;
              }}
              nodeColor={(n) => TYPE_COLOR[(n as FGNode).type] ?? TYPE_COLOR.Other}
              nodeRelSize={5}
              linkLabel={(l) => (l as FGLink).label}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={0.85}
              linkCurvature={0.1}
              linkColor={() => "#cbd5e1"}
              onNodeHover={(n) => setHovered(n as FGNode | null)}
              cooldownTicks={100}
            />
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 text-xs">
        {Object.entries(TYPE_COLOR).map(([type, color]) => (
          <span
            key={type}
            className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5"
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            {type}
          </span>
        ))}
      </div>

      {/* Hover detail */}
      {hovered && (
        <div className="rounded bg-slate-50 px-3 py-2 text-sm">
          <span className="font-medium">{hovered.id}</span>
          <span className="ml-2 text-slate-500">
            {hovered.type} · appears in document id{hovered.document_ids.length > 1 ? "s" : ""}{" "}
            {hovered.document_ids.join(", ")}
          </span>
        </div>
      )}
    </section>
  );
}
