import { useEffect, useMemo, useState } from "react";
import {
  Background, Controls, Handle, Position, ReactFlow,
  useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowDownLeft, ArrowUpRight, CircleDollarSign, Wallet } from "lucide-react";
import { TYPE_LABEL } from "../lib/constants.js";

const TYPE_ICONS = { 
  SUSPECT: Wallet, 
  INTERMEDIARY: ArrowUpRight, 
  CONTRACT: CircleDollarSign, 
  EXCHANGE_DEPOSIT: ArrowDownLeft, 
  VASP: CircleDollarSign 
};

function FlowNode({ data }) {
  const Icon = TYPE_ICONS[data.type] ?? Wallet;
  return (
    <div className={`flow-node flow-node-${data.type?.toLowerCase()} cursor-pointer transition-transform hover:scale-105`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-top">
        <span className="flow-node-icon"><Icon size={14} /></span>
        <span className="flow-node-type">{TYPE_LABEL[data.type] ?? data.type}</span>
        <span className="flow-node-status" />
      </div>
      <strong>{data.label}</strong>
      <span className="flow-node-address mono">{data.id}</span>
      <div className="flow-node-meta">
        <span>{data.balance != null ? `${Number(data.balance).toLocaleString()} USDT` : "On-chain entity"}</span>
        <span>{data.firstSeen ? new Date(data.firstSeen).toLocaleDateString() : "Verified"}</span>
      </div>
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
}

const nodeTypes = { wallet: FlowNode };

function buildGraph(graph) {
  if (!graph) return { nodes: [], edges: [] };
  const nodes = graph.nodes.map((node, index) => ({
    id: node.id,
    type: "wallet",
    position: { x: index * 245 + 30, y: index % 2 === 0 ? 80 : 215 },
    data: { ...node, label: node.label ?? node.id },
  }));
  const edges = graph.edges.map((edge) => ({
    id: edge.tx_hash,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: graph.attribution?.tx_hash === edge.tx_hash,
    label: `${Number(edge.amount ?? 0).toLocaleString()} ${edge.token ?? "USD"}`,
    data: { ...edge },
    style: { 
      stroke: graph.attribution?.tx_hash === edge.tx_hash ? "#d8b84d" : "#2a3654", 
      strokeWidth: graph.attribution?.tx_hash === edge.tx_hash ? 3 : 2,
      cursor: "pointer"
    },
    labelStyle: { fill: "#d8b84d", fontSize: 10, fontWeight: 600 },
    labelBgStyle: { fill: "#0f1420", fillOpacity: 0.9 },
    labelBgPadding: [6, 4],
  }));
  return { nodes, edges };
}

export default function GraphVisualizer({ graph, loading, onSelect }) {
  const initial = useMemo(() => buildGraph(graph), [graph]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    setNodes(initial.nodes);
    setEdges(initial.edges);
  }, [initial, setEdges, setNodes]);

  const selected = nodes.find((node) => node.id === selectedId);

  return (
    <div className="flow-canvas">
      {!graph && !loading && (
        <div className="flow-empty">
          <div className="flow-empty-icon"><Wallet size={22} className="text-[#d8b84d]" /></div>
          <strong>Awaiting wallet ingestion</strong>
          <span>Start a trace or click any preset to map counterparty topology and VASP endpoints.</span>
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
            value_usdt: edge.data?.amount,
            tx_hash: edge.data?.tx_hash,
            label: `Transfer ${edge.data?.amount} ${edge.data?.token}`,
            ...edge.data
          });
        }}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2, minZoom: 0.55, maxZoom: 1.1 }}
        minZoom={0.35}
        maxZoom={1.5}
        zoomOnScroll={false}
        panOnScroll={false}
        preventScrolling={false}
        zoomOnPinch
        zoomOnDoubleClick={false}
        zoomActivationKeyCode={["Meta", "Control"]}
        panOnDrag
        selectionOnDrag={false}
      >
        <Background color="#1b2e1f" gap={24} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {selected && (
        <div className="flow-selection">
          <span className="live-pulse" /> Selected: <strong>{selected.data.label}</strong> (Click to view dossier)
        </div>
      )}
    </div>
  );
}
