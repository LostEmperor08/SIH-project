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

function CustomFlowNode({ data }) {
  const [copied, setCopied] = useState(false);
  const isSuspect = data.type === "SUSPECT" || data.isTarget;
  const isVasp = data.type === "VASP" || data.entity === "exchange" || data.hopsToExchange === 0;
  const Icon = isSuspect ? Wallet : isVasp ? ShieldCheck : (TYPE_ICONS[data.type] ?? ArrowUpRight);

  const copyAddr = (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(data.address || data.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const risk = Number(data.riskScore ?? data.risk ?? (isSuspect ? 95 : isVasp ? 99 : 65));
  const shortAddr = data.address 
    ? `${data.address.slice(0, 6)}...${data.address.slice(-4)}`
    : `${String(data.id || "").slice(0, 6)}...${String(data.id || "").slice(-4)}`;

  return (
    <div 
      className={`relative rounded-2xl p-3.5 transition-all duration-200 cursor-pointer shadow-2xl min-w-[240px] max-w-[270px] ${
        isSuspect
          ? "border-2 border-[#E5B83B] bg-[rgba(20,16,5,0.95)] shadow-[0_0_25px_rgba(229,184,59,0.3)] hover:scale-[1.03]"
          : isVasp
          ? "border-2 border-emerald-500 bg-[rgba(5,25,18,0.95)] shadow-[0_0_25px_rgba(16,185,129,0.3)] hover:scale-[1.03]"
          : "border border-white/15 bg-[rgba(10,18,14,0.92)] hover:border-[#E5B83B]/50 hover:scale-[1.02]"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-[#E5B83B] !w-2.5 !h-2.5 !border-2 !border-black" />
      
      {/* Header Tag */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <div className={`p-1 rounded-lg ${
            isSuspect ? "bg-[#E5B83B]/20 text-[#E5B83B]" : isVasp ? "bg-emerald-500/20 text-emerald-400" : "bg-cyan-500/20 text-cyan-400"
          }`}>
            <Icon size={13} />
          </div>
          <span className={`text-[10px] font-extrabold uppercase tracking-wider ${
            isSuspect ? "text-[#E5B83B]" : isVasp ? "text-emerald-400" : "text-slate-300"
          }`}>
            {isSuspect ? "Suspect Target" : isVasp ? "Terminal VASP" : "Layering Mule"}
          </span>
        </div>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-white/10 bg-black/50 text-slate-300 font-bold">
          Hop #{data.hop ?? 0}
        </span>
      </div>

      {/* Main Title & Address */}
      <div className="mb-2.5">
        <div className="text-xs font-bold text-white truncate max-w-[220px]" title={data.label || data.id}>
          {data.label || shortAddr}
        </div>
        <div className="flex items-center justify-between mt-1 text-[11px] font-mono text-slate-400 bg-black/40 px-2 py-1 rounded-lg border border-white/5">
          <span>{shortAddr}</span>
          <button 
            type="button" 
            onClick={copyAddr}
            className="hover:text-white transition p-0.5 text-slate-400"
            title="Copy address"
          >
            {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          </button>
        </div>
      </div>

      {/* Stats Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-white/10 text-[10px] font-mono">
        <div className="text-slate-300">
          <span className="text-slate-500 block text-[9px] font-sans uppercase">Traced Volume</span>
          <span className="font-bold text-emerald-400">
            ${Number(data.inUsd || data.outUsd || data.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="text-right">
          <span className="text-slate-500 block text-[9px] font-sans uppercase">Risk Score</span>
          <span className={`font-bold px-1.5 py-0.5 rounded text-[9px] ${
            risk >= 90 ? "bg-red-950/80 text-red-300 border border-red-500/40" : "bg-amber-950/80 text-amber-300 border border-amber-500/40"
          }`}>
            {risk}/100
          </span>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-[#E5B83B] !w-2.5 !h-2.5 !border-2 !border-black" />
    </div>
  );
}

const nodeTypes = { wallet: CustomFlowNode };

function layoutGraph(graph, focusMoneyPath = false) {
  if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length) {
    return { nodes: [], edges: [] };
  }

  const nodes = [...graph.nodes];
  const edges = Array.isArray(graph.edges) ? [...graph.edges] : [];

  // Group nodes by hop
  const hopGroups = new Map();
  nodes.forEach((node) => {
    const hop = Number(node.hop ?? 0);
    if (!hopGroups.has(hop)) hopGroups.set(hop, []);
    hopGroups.get(hop).push(node);
  });

  const sortedHops = Array.from(hopGroups.keys()).sort((a, b) => a - b);
  const positionedNodes = [];

  sortedHops.forEach((hop) => {
    const group = hopGroups.get(hop);
    const colX = hop * 360 + 60;
    const totalHeight = group.length * 170;
    const startY = Math.max(50, 240 - (totalHeight / 2));

    group.forEach((node, rowIdx) => {
      positionedNodes.push({
        id: String(node.id),
        type: "wallet",
        position: { x: colX, y: startY + (rowIdx * 170) },
        data: { ...node, label: node.label ?? node.id },
      });
    });
  });

  const positionedEdges = edges.map((edge, idx) => {
    const isAttributed = graph.attribution?.tx_hash && graph.attribution.tx_hash === edge.tx_hash;
    const isMoneyPath = edge.animated || isAttributed || (edge.data && edge.data.onMoneyPath);
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
  const [nodes, setNodes, onNodesChange] = useNodesState(layouted.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layouted.edges);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    setNodes(layouted.nodes);
    setEdges(layouted.edges);
  }, [layouted, setEdges, setNodes]);

  const selected = nodes.find((node) => node.id === selectedId);

  return (
    <div className="flow-canvas relative h-[520px] w-full rounded-2xl overflow-hidden bg-[#040d09] border border-white/10">
      {/* Top Controls Overlay */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded-xl border border-white/10 text-xs text-slate-300">
        <Sparkles size={13} className="text-[#E5B83B]" />
        <span className="font-bold text-white">Interactive Forensic Topology</span>
        <span className="text-slate-500">·</span>
        <span className="text-[11px] text-slate-400 font-mono">{nodes.length} Nodes · {edges.length} Links</span>
      </div>

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
          <span className="text-slate-500">· Click to inspect full dossier</span>
        </div>
      )}
    </div>
  );
}
