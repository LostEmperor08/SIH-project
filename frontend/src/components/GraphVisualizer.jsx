import { useEffect, useMemo, useState } from "react";
import {
  Background, Controls, Handle, Position, ReactFlow,
  useEdgesState, useNodesState, MarkerType, MiniMap
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowDownLeft, ArrowUpRight, CircleDollarSign, Wallet,
  ShieldAlert, ShieldCheck, Copy, Check, ExternalLink, Sparkles, Filter
} from "lucide-react";
import { TYPE_LABEL } from "../lib/constants.js";

const TYPE_ICONS = {
  SUSPECT: Wallet,
  INTERMEDIARY: ArrowUpRight,
  CONTRACT: CircleDollarSign,
  EXCHANGE_DEPOSIT: ArrowDownLeft,
  VASP: ShieldCheck
};

function FlowNode({ data }) {
  const Icon = TYPE_ICONS[data.type] ?? Wallet;
  const riskVal = Math.round(Number(data.riskScore ?? data.risk ?? data.risk_score ?? 0));
  const riskBand = (data.riskBand || (riskVal >= 80 ? "CRITICAL" : riskVal >= 60 ? "HIGH" : riskVal >= 35 ? "MEDIUM" : "LOW")).toUpperCase();

  return (
    <div className={`flow-node flow-node-${data.type?.toLowerCase()} cursor-pointer transition-transform hover:scale-105`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-top">
        <span className="flow-node-icon"><Icon size={14} /></span>
        <span className="flow-node-type">{TYPE_LABEL[data.type] ?? data.type}</span>
        <span className={`flow-node-risk-pill px-1.5 py-0.5 rounded text-[9px] font-mono font-extrabold uppercase ${
          riskBand === "CRITICAL" ? "bg-red-500/30 text-red-300 border border-red-500/50" :
          riskBand === "HIGH" ? "bg-amber-500/30 text-amber-300 border border-amber-500/50" :
          riskBand === "MEDIUM" || riskBand === "ELEVATED" ? "bg-yellow-500/30 text-yellow-300 border border-yellow-500/50" :
          "bg-emerald-500/30 text-emerald-300 border border-emerald-500/50"
        }`}>
          {riskBand} ({riskVal})
        </span>
      </div>
      <div className="flow-node-body">
        <div className="flow-node-label">{data.label ?? data.id}</div>
        <div className="flow-node-meta">{data.address ?? data.id}</div>
      </div>
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
}

const nodeTypes = { wallet: FlowNode };

function layoutGraph(graph, focusMoneyPath = false) {
  if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length) {
    return { nodes: [], edges: [] };
  }

  const nodes = [...graph.nodes];
  const edges = Array.isArray(graph.edges) ? [...graph.edges] : [];
  const nodeById = new Map(nodes.map((node) => [String(node.id), node]));
  const outgoing = new Map(nodes.map((node) => [String(node.id), []]));
  const incoming = new Map(nodes.map((node) => [String(node.id), []]));

  edges.forEach((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (outgoing.has(source) && incoming.has(target)) {
      outgoing.get(source).push(target);
      incoming.get(target).push(source);
    }
  });

  const nodeData = (node) => node?.data && typeof node.data === "object"
    ? { ...node, ...node.data }
    : node;
  const roots = nodes
    .filter((node) => {
      const data = nodeData(node);
      return Boolean(data.isTarget || data.type === "SUSPECT" || data.type === "target");
    })
    .map((node) => String(node.id));
  const seedIds = roots.length
    ? roots
    : nodes
        .filter((node) => (incoming.get(String(node.id)) || []).length === 0)
        .map((node) => String(node.id));
  const seeds = seedIds.length ? seedIds : nodes.map((node) => String(node.id));
  const rank = new Map(seeds.map((id) => [id, 0]));
  const queue = [...seeds];

  // Breadth-first ranks are bounded and cycle-safe. A longest-path style
  // relaxation keeps increasing ranks around blockchain cycles and causes
  // fitView to shrink the entire graph into an unreadable strip.
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const source = queue[cursor];
    const sourceRank = rank.get(source);
    (outgoing.get(source) || []).forEach((target) => {
      if (rank.has(target)) return;
      rank.set(target, sourceRank + 1);
      queue.push(target);
    });
  }

  // Inbound-only activity is still part of the visible neighborhood. Use
  // undirected distance only for nodes the directed traversal could not
  // reach, without changing the edge direction shown to the investigator.
  const undirected = new Map(nodes.map((node) => [String(node.id), []]));
  edges.forEach((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (undirected.has(source) && undirected.has(target)) {
      undirected.get(source).push(target);
      undirected.get(target).push(source);
    }
  });
  const neighborhoodQueue = [...rank.keys()];
  for (let cursor = 0; cursor < neighborhoodQueue.length; cursor += 1) {
    const source = neighborhoodQueue[cursor];
    const sourceRank = rank.get(source);
    (undirected.get(source) || []).forEach((target) => {
      if (rank.has(target)) return;
      rank.set(target, sourceRank + 1);
      neighborhoodQueue.push(target);
    });
  }

  // If the response has disconnected components, keep them visible using
  // their existing hop, then place any remaining nodes in a compact column.
  nodes.forEach((node) => {
    const id = String(node.id);
    if (rank.has(id)) return;
    const hop = Number(nodeData(node).hop);
    rank.set(id, Number.isFinite(hop) && hop >= 0 ? hop : 0);
  });

  const hopGroups = new Map();
  rank.forEach((hop, id) => {
    if (!hopGroups.has(hop)) hopGroups.set(hop, []);
    hopGroups.get(hop).push(id);
  });

  const sortedHops = Array.from(hopGroups.keys()).sort((a, b) => a - b);
  const positionedNodes = [];

  sortedHops.forEach((hop) => {
    const group = hopGroups.get(hop);
    const colX = hop * 320 + 80;
    const spacing = Math.max(150, Math.min(210, 680 / Math.max(group.length, 1)));
    const totalHeight = (group.length - 1) * spacing;
    const startY = Math.max(50, 240 - (totalHeight / 2));

    group.sort((a, b) => {
      const aParent = (incoming.get(a) || []).find((id) => rank.get(id) === hop - 1);
      const bParent = (incoming.get(b) || []).find((id) => rank.get(id) === hop - 1);
      return String(aParent || a).localeCompare(String(bParent || b));
    });

    group.forEach((id, rowIdx) => {
      const data = nodeData(nodeById.get(id));
      positionedNodes.push({
        id,
        type: "wallet",
        position: { x: colX, y: startY + (rowIdx * spacing) },
        data: { ...data, label: data.label ?? id },
      });
    });
  });

  const positionedEdges = edges.map((edge, idx) => {
    const isAttributed = graph.attribution?.tx_hash && graph.attribution.tx_hash === edge.tx_hash;
    const isMoneyPath = Boolean(edge.animated || isAttributed || (edge.data && edge.data.onMoneyPath));
    const amt = Number(edge.amount ?? edge.valueUsd ?? 0);
    const labelText = amt >= 1 ? `$${amt.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${edge.txCount ?? 1} tx`;

    return {
      id: String(edge.id || edge.tx_hash || `edge-${edge.source}-${edge.target}-${idx}`),
      source: String(edge.source),
      target: String(edge.target),
      type: "smoothstep",
      animated: Boolean(isMoneyPath),
      label: labelText,
      data: { ...edge },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isMoneyPath ? "#E5B83B" : "#4b5563",
        width: 14,
        height: 14,
      },
      style: {
        stroke: isMoneyPath ? "#E5B83B" : "#374151",
        strokeWidth: isMoneyPath ? 3 : 1.5,
        cursor: "pointer",
      },
      labelStyle: { fill: isMoneyPath ? "#FFE28A" : "#9ca3af", fontSize: 11, fontWeight: 700, fontFamily: "monospace" },
      labelBgStyle: { fill: "#081b13", fillOpacity: 0.95, stroke: isMoneyPath ? "#E5B83B" : "#374151", strokeWidth: 1 },
      labelBgPadding: [6, 4],
      labelBgBorderRadius: 6,
    };
  });

  return { nodes: positionedNodes, edges: positionedEdges };
}

export default function GraphVisualizer({ graph, loading, onSelect }) {
  const [focusMode, setFocusMode] = useState(false);
  const layouted = useMemo(() => layoutGraph(graph, focusMode), [graph, focusMode]);
  const flowSummary = useMemo(() => {
    if (!graph?.nodes?.length || !graph?.edges?.length) return null;

    const suspect = graph.nodes.find((node) => {
      const data = node.data && typeof node.data === "object"
        ? { ...node, ...node.data }
        : node;
      return data.isTarget || data.type === "SUSPECT" || data.type === "target";
    });
    if (!suspect) return null;

    const suspectId = String(suspect.id).toLowerCase();
    const labelFor = (address) => {
      const node = graph.nodes.find((candidate) => String(candidate.id).toLowerCase() === address);
      const data = node?.data && typeof node.data === "object" ? { ...node, ...node.data } : node;
      return data?.label && data.label !== address ? data.label : `${address.slice(0, 8)}…${address.slice(-6)}`;
    };
    const aggregate = (entries) => {
      const totals = new Map();
      entries.forEach(({ address, amount }) => {
        if (!address || address === suspectId) return;
        totals.set(address, (totals.get(address) || 0) + amount);
      });
      return [...totals.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([address, amount]) => ({ address, label: labelFor(address), amount }));
    };

    const received = [];
    const sent = [];
    let totalReceived = 0;
    graph.edges.forEach((edge) => {
      const source = String(edge.source || "").toLowerCase();
      const target = String(edge.target || "").toLowerCase();
      const amount = Number(edge.amount ?? edge.valueUsd ?? edge.value_usd ?? 0);
      if (!Number.isFinite(amount) || amount < 0) return;
      if (source === suspectId) sent.push({ address: target, amount });
      if (target === suspectId) {
        received.push({ address: source, amount });
        totalReceived += amount;
      }
    });

    return {
      wallet: suspect.id,
      received,
      sent,
      topSenders: aggregate(received),
      topRecipients: aggregate(sent),
      totalReceived,
    };
  }, [graph]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layouted.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layouted.edges);
  const [selectedId, setSelectedId] = useState(null);
  const [flowInstance, setFlowInstance] = useState(null);

  useEffect(() => {
    setNodes(layouted.nodes);
    setEdges(layouted.edges);
    if (flowInstance) {
      requestAnimationFrame(() => {
        flowInstance.fitView({ padding: 0.18, minZoom: 0.45, maxZoom: 1.15 });
      });
    }
  }, [flowInstance, layouted, setEdges, setNodes]);

  const selected = nodes.find((node) => node.id === selectedId);

  return (
    <div className="flow-canvas relative h-[520px] w-full rounded-2xl overflow-hidden bg-[#040d09] border border-white/10">
      <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded-xl border border-white/10 text-xs text-slate-300">
        <Sparkles size={13} className="text-[#E5B83B]" />
        <span className="font-bold text-white">Interactive Forensic Topology</span>
        <span className="text-slate-500">?</span>
        <span className="text-[11px] text-slate-400 font-mono">{nodes.length} Nodes ? {edges.length} Links</span>
      </div>

      {flowSummary && (
        <div className="absolute right-3 top-3 z-10 w-[min(360px,calc(100%-1.5rem))] rounded-xl border border-white/10 bg-black/75 p-3 text-[11px] text-slate-300 shadow-xl backdrop-blur-md">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="font-bold uppercase tracking-wider text-[#FFE28A]">Fund direction</span>
            <span className="font-mono font-bold text-emerald-300">
              Received: {flowSummary.totalReceived.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="mb-1 flex items-center gap-1 font-semibold text-emerald-300">
                <ArrowDownLeft size={13} /> More received from
              </div>
              {flowSummary.topSenders.length ? flowSummary.topSenders.map((item) => (
                <div key={item.address} className="flex items-center justify-between gap-2 font-mono">
                  <span className="truncate" title={item.address}>{item.label}</span>
                  <span className="shrink-0 text-slate-200">{item.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT</span>
                </div>
              )) : <span className="text-slate-500">No inbound transfer</span>}
            </div>
            <div>
              <div className="mb-1 flex items-center gap-1 font-semibold text-amber-300">
                <ArrowUpRight size={13} /> More sent to
              </div>
              {flowSummary.topRecipients.length ? flowSummary.topRecipients.map((item) => (
                <div key={item.address} className="flex items-center justify-between gap-2 font-mono">
                  <span className="truncate" title={item.address}>{item.label}</span>
                  <span className="shrink-0 text-slate-200">{item.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT</span>
                </div>
              )) : <span className="text-slate-500">No outbound transfer</span>}
            </div>
          </div>
          <div className="mt-2 border-t border-white/10 pt-1.5 text-[10px] text-slate-500">
            Values are summed from the displayed graph edges as USD/USDT-equivalent amounts.
          </div>
        </div>
      )}

      {!graph && !loading && (
        <div className="flow-empty absolute inset-0 flex flex-col items-center justify-center z-10 bg-black/60 backdrop-blur-sm p-6 text-center">
          <div className="p-4 rounded-2xl bg-[#E5B83B]/10 border border-[#E5B83B]/30 mb-3 text-[#E5B83B]">
            <Wallet size={28} />
          </div>
          <strong className="text-base text-white">Awaiting wallet ingestion</strong>
          <span className="text-xs text-slate-400 max-w-sm mt-1">
            Enter any suspect address above to autonomously map the multi-hop money laundering route to the receiving exchange.
          </span>
        </div>
      )}

      <ReactFlow
        nodes={nodes.map((node) => ({ ...node, selected: node.id === selectedId }))}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => {
          setSelectedId(node.id);
          onSelect?.({ ...node.data });
        }}
        onEdgeClick={(_, edge) => {
          onSelect?.({
            id: edge.id,
            origin_sender: edge.source,
            counterparty: edge.target,
            value_usdt: edge.data?.amount || edge.data?.valueUsd,
            tx_hash: edge.data?.tx_hash || (edge.data?.txHashes && edge.data?.txHashes[0]),
            label: `Transfer flow: ${edge.label || ""}`,
            ...edge.data
          });
        }}
        nodeTypes={nodeTypes}
        onInit={setFlowInstance}
        fitView
        fitViewOptions={{ padding: 0.18, minZoom: 0.45, maxZoom: 1.15 }}
        minZoom={0.25}
        maxZoom={1.6}
        panOnDrag
        zoomOnPinch
      >
        <Background color="#163829" gap={28} size={1.2} />
        <Controls showInteractive={false} className="!bg-black/80 !border-white/10 !fill-white" />
      </ReactFlow>

      {selected && (
        <div className="flow-selection absolute bottom-3 left-3 z-10 bg-black/80 backdrop-blur-md px-3.5 py-2 rounded-xl border border-[#E5B83B]/40 text-xs text-slate-200 flex items-center gap-2 shadow-xl">
          <span className="h-2 w-2 rounded-full bg-[#E5B83B] animate-ping" />
          <span>Selected Entity: <strong className="text-white font-mono">{selected.data.label || selected.id}</strong></span>
          <span className="text-slate-500">? Click to inspect full dossier</span>
        </div>
      )}
    </div>
  );
}
