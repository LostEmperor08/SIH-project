-- =====================================================================
-- Migration 11: Cross-Chain Bridge Directory & Transfers Schema
-- SIH 2026 Problem Statement 26183 (Batch 3)
-- =====================================================================

CREATE TABLE IF NOT EXISTS bridges (
    id TEXT PRIMARY KEY,                       -- e.g. 'bridge_stargate', 'bridge_polygon_pos'
    name TEXT NOT NULL,                        -- Display Name e.g. 'Stargate / LayerZero'
    protocol TEXT NOT NULL,                    -- Protocol e.g. 'LayerZero', 'Hop', 'PolygonPoS'
    supported_source_chains TEXT[] NOT NULL DEFAULT '{}',
    supported_destination_chains TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',     -- 'active', 'paused', 'deprecated'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bridge_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_id TEXT NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
    chain TEXT NOT NULL,                       -- 'eth', 'polygon', 'bsc', 'tron', 'btc'
    address TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'ROUTER',       -- 'DEPOSIT', 'LOCK', 'BURN', 'MINT', 'RELEASE', 'ROUTER', 'MESSAGING', 'VALIDATOR', 'UNKNOWN'
    active BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'verified_directory',
    verification_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bridge_contract_chain_addr UNIQUE (chain, address, bridge_id)
);

CREATE TABLE IF NOT EXISTS bridge_routes (
    id TEXT PRIMARY KEY,                       -- e.g. 'route_stargate_eth_polygon_usdt'
    bridge_id TEXT NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
    source_chain TEXT NOT NULL,
    destination_chain TEXT NOT NULL,
    source_asset TEXT NOT NULL,
    destination_asset TEXT NOT NULL,
    route_type TEXT NOT NULL DEFAULT 'LOCK_RELEASE', -- 'LOCK_RELEASE', 'BURN_MINT', 'MESSAGING', 'ATOMIC_SWAP'
    fee_bps INT NOT NULL DEFAULT 30,           -- Fee in basis points (e.g. 30 = 0.3%)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cross_chain_transfers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_id TEXT NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
    source_chain TEXT NOT NULL,
    source_tx_hash TEXT NOT NULL,
    source_address TEXT NOT NULL,
    source_event_id TEXT,
    destination_chain TEXT NOT NULL,
    destination_tx_hash TEXT NOT NULL,
    destination_address TEXT NOT NULL,
    destination_event_id TEXT,
    source_asset TEXT NOT NULL,
    destination_asset TEXT NOT NULL,
    source_amount NUMERIC(24,8) NOT NULL,
    destination_amount NUMERIC(24,8) NOT NULL,
    message_id TEXT,
    nonce TEXT,
    correlation_type TEXT NOT NULL DEFAULT 'FUZZY_ROUTE', -- 'MESSAGE_ID', 'PROTOCOL_SEQUENCE', 'EXACT_EVENT', 'FUZZY_ROUTE', 'UNCONFIRMED'
    correlation_confidence NUMERIC(4,3) NOT NULL DEFAULT 0.850,
    correlation_quality TEXT NOT NULL DEFAULT 'HIGH',     -- 'EXACT', 'HIGH', 'MEDIUM', 'LOW', 'UNCONFIRMED'
    attributed_value_usd NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    evidence JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_bridge_contracts_chain_addr ON bridge_contracts(chain, address) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_cross_chain_src ON cross_chain_transfers(source_chain, source_tx_hash);
CREATE INDEX IF NOT EXISTS idx_cross_chain_dst ON cross_chain_transfers(destination_chain, destination_tx_hash);
CREATE INDEX IF NOT EXISTS idx_cross_chain_msg ON cross_chain_transfers(message_id) WHERE message_id IS NOT NULL;

-- RLS Policies
ALTER TABLE bridges ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridge_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridge_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE cross_chain_transfers ENABLE ROW LEVEL SECURITY;

CREATE POLICY bridges_select_all ON bridges FOR SELECT USING (true);
CREATE POLICY bridge_contracts_select_all ON bridge_contracts FOR SELECT USING (true);
CREATE POLICY bridge_routes_select_all ON bridge_routes FOR SELECT USING (true);
CREATE POLICY cross_chain_transfers_select_all ON cross_chain_transfers FOR SELECT USING (true);

-- Seed Dataset for Major Bridges and Contracts
INSERT INTO bridges (id, name, protocol, supported_source_chains, supported_destination_chains, status)
VALUES
    ('bridge_stargate', 'Stargate / LayerZero', 'LayerZero', ARRAY['eth', 'polygon', 'bsc'], ARRAY['eth', 'polygon', 'bsc'], 'active'),
    ('bridge_polygon_pos', 'Polygon PoS Portal Bridge', 'PolygonPoS', ARRAY['eth'], ARRAY['polygon'], 'active'),
    ('bridge_hop', 'Hop Protocol', 'Hop', ARRAY['eth', 'polygon'], ARRAY['eth', 'polygon'], 'active'),
    ('bridge_wormhole', 'Wormhole Portal', 'Wormhole', ARRAY['eth', 'polygon', 'bsc'], ARRAY['eth', 'polygon', 'bsc', 'tron'], 'active')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status;

-- Seed Bridge Contracts
INSERT INTO bridge_contracts (bridge_id, chain, address, role, source, verification_reference)
VALUES
    -- Stargate / LayerZero
    ('bridge_stargate', 'eth', '0x8731d54e9d02c286767d56ac03e8037c07e01e98', 'ROUTER', 'etherscan_verified', 'stargate_eth_router'),
    ('bridge_stargate', 'polygon', '0x45a2e574423823529a408152bc0e82c06b1ed606', 'ROUTER', 'polygonscan_verified', 'stargate_polygon_router'),
    ('bridge_stargate', 'bsc', '0x4a8240b0902926a37813a4369e8b15d04dd2604d', 'ROUTER', 'bscscan_verified', 'stargate_bsc_router'),

    -- Polygon PoS Bridge
    ('bridge_polygon_pos', 'eth', '0xa0c68c638235ee32657e8f720a23cec1bfc77c77', 'LOCK', 'etherscan_verified', 'polygon_pos_eth_bridge'),
    ('bridge_polygon_pos', 'polygon', '0x0000000000000000000000000000000000001010', 'RELEASE', 'polygonscan_verified', 'polygon_pos_polygon_mint'),

    -- Hop Protocol
    ('bridge_hop', 'eth', '0x3666f603cc12693e9f78817651a2d59bf38ef34f', 'LOCK', 'etherscan_verified', 'hop_eth_usdt_bridge'),
    ('bridge_hop', 'polygon', '0xa6a383850285b0b2e86978f3b8e8f8045d475a80', 'RELEASE', 'polygonscan_verified', 'hop_polygon_usdt_bridge')
ON CONFLICT ON CONSTRAINT uq_bridge_contract_chain_addr DO UPDATE SET role = EXCLUDED.role;

-- Seed Bridge Routes
INSERT INTO bridge_routes (id, bridge_id, source_chain, destination_chain, source_asset, destination_asset, route_type, fee_bps)
VALUES
    ('route_stargate_eth_polygon_usdt', 'bridge_stargate', 'eth', 'polygon', 'USDT', 'USDT', 'MESSAGING', 30),
    ('route_stargate_eth_bsc_usdt', 'bridge_stargate', 'eth', 'bsc', 'USDT', 'USDT', 'MESSAGING', 30),
    ('route_polygon_pos_eth_polygon_usdt', 'bridge_polygon_pos', 'eth', 'polygon', 'USDT', 'USDT0', 'LOCK_RELEASE', 15),
    ('route_hop_eth_polygon_usdt', 'bridge_hop', 'eth', 'polygon', 'USDT', 'USDT.e', 'LOCK_RELEASE', 25)
ON CONFLICT (id) DO UPDATE SET fee_bps = EXCLUDED.fee_bps;
