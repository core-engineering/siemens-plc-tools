# ruff: noqa: E501
"""Vue.js 3 web interface for OPC UA simulation.

Provides an interactive single-page application for browsing the OPC UA
node tree, reading/writing variables, and monitoring live values.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def register_sim_page(app: FastAPI) -> None:
    """Register the /sim/ page route on a FastAPI app.

    Parameters
    ----------
    app : FastAPI
        The FastAPI application to register routes on.
    """

    @app.get("/sim", response_class=HTMLResponse)
    @app.get("/sim/", response_class=HTMLResponse)
    async def sim_page() -> HTMLResponse:
        """Serve the PLC Simulation interface."""
        return HTMLResponse(content=_build_sim_html())


def _build_sim_html() -> str:
    """Build the simulation interface HTML."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PLC Simulation</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1e1e2e; color: #cdd6f4; }

        /* Layout */
        .app { display: flex; flex-direction: column; height: 100vh; }
        .topbar { display: flex; align-items: center; padding: 10px 16px; background: #313244; border-bottom: 1px solid #45475a; gap: 12px; flex-shrink: 0; }
        .body { display: flex; flex: 1; overflow: hidden; }
        .sidebar { width: 340px; background: #1e1e2e; border-right: 1px solid #45475a; display: flex; flex-direction: column; flex-shrink: 0; }
        .main-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .detail-panel { flex: 1; padding: 20px; overflow-y: auto; }
        .monitor-panel { border-top: 1px solid #45475a; max-height: 40vh; overflow-y: auto; flex-shrink: 0; }

        /* Top bar */
        .topbar .home-link { color: #89b4fa; text-decoration: none; font-size: 14px; }
        .topbar .home-link:hover { text-decoration: underline; }
        .topbar h1 { font-size: 16px; font-weight: 600; flex: 1; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .status-dot.connected { background: #a6e3a1; box-shadow: 0 0 6px #a6e3a1; }
        .status-dot.disconnected { background: #f38ba8; }
        .status-dot.connecting { background: #f9e2af; animation: pulse 1s infinite; }
        .status-dot.error { background: #f38ba8; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .endpoint-label { font-size: 12px; color: #a6adc8; font-family: monospace; }
        .btn { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 500; }
        .btn-connect { background: #a6e3a1; color: #1e1e2e; }
        .btn-connect:hover { background: #94d99a; }
        .btn-disconnect { background: #f38ba8; color: #1e1e2e; }
        .btn-disconnect:hover { background: #e87d99; }
        .btn-primary { background: #89b4fa; color: #1e1e2e; }
        .btn-primary:hover { background: #7ba8ee; }
        .btn-small { padding: 4px 10px; font-size: 12px; }

        /* Sidebar */
        .sidebar-header { padding: 12px 16px; background: #313244; font-size: 13px; font-weight: 600; border-bottom: 1px solid #45475a; }
        .search-box { padding: 10px; }
        .search-box input { width: 100%; padding: 8px 12px; border: none; border-radius: 4px; background: #313244; color: #cdd6f4; font-size: 13px; }
        .search-box input::placeholder { color: #6c7086; }
        .tree-container { flex: 1; overflow-y: auto; padding-bottom: 20px; }

        /* Tree nodes */
        .tree-node { user-select: none; }
        .tree-row { display: flex; align-items: center; padding: 5px 8px; cursor: pointer; font-size: 13px; gap: 4px; border-bottom: 1px solid rgba(69, 71, 90, 0.3); }
        .tree-row:hover { background: #313244; }
        .tree-row.selected { background: #45475a; }
        .tree-expand { width: 18px; text-align: center; color: #6c7086; font-size: 11px; flex-shrink: 0; }
        .tree-icon { flex-shrink: 0; font-size: 14px; }
        .tree-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tree-badges { display: flex; gap: 4px; flex-shrink: 0; }
        .badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
        .badge-type { background: #45475a; color: #f9e2af; }
        .badge-rw { background: #313244; color: #a6e3a1; }
        .badge-r { background: #313244; color: #6c7086; }
        .tree-children { margin-left: 16px; }

        /* Detail panel */
        .empty-state { text-align: center; padding: 60px 20px; }
        .empty-state h2 { color: #6c7086; font-size: 18px; margin-bottom: 8px; }
        .empty-state p { color: #585b70; font-size: 14px; }
        .not-connected { text-align: center; padding: 60px 20px; }
        .not-connected h2 { color: #f38ba8; font-size: 18px; margin-bottom: 12px; }
        .not-connected p { color: #6c7086; font-size: 14px; margin-bottom: 16px; }

        .node-detail { background: #313244; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .node-detail h2 { font-size: 18px; margin-bottom: 16px; font-family: monospace; color: #89b4fa; }
        .detail-grid { display: grid; grid-template-columns: 120px 1fr; gap: 8px; font-size: 14px; }
        .detail-label { color: #6c7086; }
        .detail-value { font-family: monospace; }

        /* Value display */
        .value-display { background: #1e1e2e; border-radius: 8px; padding: 20px; margin-bottom: 16px; text-align: center; }
        .value-display .current-value { font-size: 36px; font-weight: 700; font-family: monospace; color: #a6e3a1; }
        .value-display .value-meta { font-size: 12px; color: #6c7086; margin-top: 8px; }
        .value-display .live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #a6e3a1; animation: pulse 2s infinite; margin-right: 6px; }

        /* Write control */
        .write-control { background: #313244; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        .write-control h3 { font-size: 14px; margin-bottom: 12px; color: #f9e2af; }
        .write-row { display: flex; gap: 8px; align-items: center; }
        .write-row input, .write-row select { flex: 1; padding: 8px 12px; border: 1px solid #45475a; border-radius: 4px; background: #1e1e2e; color: #cdd6f4; font-family: monospace; }
        .toggle-switch { position: relative; width: 50px; height: 26px; cursor: pointer; }
        .toggle-switch input { display: none; }
        .toggle-track { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: #45475a; border-radius: 13px; transition: background 0.2s; }
        .toggle-track::after { content: ''; position: absolute; width: 20px; height: 20px; border-radius: 50%; background: #cdd6f4; top: 3px; left: 3px; transition: transform 0.2s; }
        .toggle-switch input:checked + .toggle-track { background: #a6e3a1; }
        .toggle-switch input:checked + .toggle-track::after { transform: translateX(24px); }

        /* Monitor table */
        .monitor-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; background: #313244; border-bottom: 1px solid #45475a; }
        .monitor-header h3 { font-size: 13px; }
        .monitor-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .monitor-table th { padding: 8px 12px; text-align: left; background: #313244; color: #6c7086; font-weight: 500; position: sticky; top: 0; }
        .monitor-table td { padding: 6px 12px; border-bottom: 1px solid rgba(69, 71, 90, 0.3); font-family: monospace; }
        .monitor-table tr:hover { background: #313244; }
        .quality-good { color: #a6e3a1; }
        .quality-bad { color: #f38ba8; }

        /* Breadcrumb */
        .breadcrumb { padding: 10px 20px; font-size: 12px; color: #6c7086; border-bottom: 1px solid #45475a; }
        .breadcrumb span { cursor: pointer; }
        .breadcrumb span:hover { color: #89b4fa; }
        .breadcrumb .sep { margin: 0 4px; }

        /* Loading spinner */
        .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #45475a; border-top-color: #89b4fa; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
<div id="app">
    <!-- Top Bar -->
    <div class="topbar">
        <a href="/" class="home-link">&larr; Home</a>
        <h1>PLC Simulation</h1>
        <span class="endpoint-label">{{ config.endpoint }}</span>
        <span class="status-dot" :class="connectionStatus"></span>
        <span style="font-size:12px;">{{ connectionStatus }}</span>
        <button v-if="connectionStatus !== 'connected'" class="btn btn-connect" @click="doConnect" :disabled="connectionStatus === 'connecting'">
            Connect
        </button>
        <button v-else class="btn btn-disconnect" @click="doDisconnect">
            Disconnect
        </button>
    </div>

    <div class="body">
        <!-- Sidebar: Node Tree -->
        <div class="sidebar">
            <div class="sidebar-header">OPC UA Node Tree</div>
            <div class="search-box">
                <input v-model="searchQuery" placeholder="Search nodes..." @input="filterTree">
            </div>
            <div class="tree-container">
                <div v-if="connectionStatus !== 'connected'" style="padding: 20px; text-align: center; color: #6c7086;">
                    Connect to browse nodes
                </div>
                <div v-else-if="rootNodes.length === 0" style="padding: 20px; text-align: center;">
                    <span class="spinner"></span> Loading...
                </div>
                <template v-else>
                    <tree-node
                        v-for="node in filteredRootNodes"
                        :key="node.node_id"
                        :node="node"
                        :selected-id="selectedNodeId"
                        :expanded-ids="expandedIds"
                        :children-map="childrenMap"
                        :loading-ids="loadingIds"
                        @select="selectNode"
                        @toggle="toggleNode"
                    />
                </template>
            </div>
        </div>

        <!-- Main Panel -->
        <div class="main-panel">
            <!-- Breadcrumb -->
            <div v-if="selectedNode" class="breadcrumb">
                <span @click="selectNode(null)">Root</span>
                <template v-for="(crumb, i) in breadcrumbs" :key="i">
                    <span class="sep">/</span>
                    <span @click="selectNode(crumb)">{{ crumb.display_name }}</span>
                </template>
            </div>

            <!-- Detail Panel -->
            <div class="detail-panel">
                <!-- Not connected state -->
                <div v-if="connectionStatus !== 'connected'" class="not-connected">
                    <h2>Not Connected</h2>
                    <p>Click <strong>Connect</strong> to connect to the OPC UA server at<br>
                    <code>{{ config.endpoint }}</code></p>
                    <button class="btn btn-connect" @click="doConnect">Connect</button>
                </div>

                <!-- No selection -->
                <div v-else-if="!selectedNode" class="empty-state">
                    <h2>Select a Node</h2>
                    <p>Browse the tree on the left and select a variable to view its details.</p>
                </div>

                <!-- Node detail -->
                <template v-else>
                    <!-- Value display (for variables) -->
                    <div v-if="selectedNode.node_class === 'Variable'" class="value-display">
                        <div v-if="currentValue !== null">
                            <span class="live-dot"></span>
                            <span class="current-value">{{ formatValue(currentValue.value) }}</span>
                            <div class="value-meta">
                                {{ currentValue.data_type }} &middot;
                                Quality: {{ currentValue.quality }}
                                <span v-if="currentValue.source_timestamp"> &middot; {{ formatTimestamp(currentValue.source_timestamp) }}</span>
                            </div>
                        </div>
                        <div v-else style="color: #6c7086;">
                            <span class="spinner"></span> Reading...
                        </div>
                    </div>

                    <!-- Node info -->
                    <div class="node-detail">
                        <h2>{{ selectedNode.display_name }}</h2>
                        <div class="detail-grid">
                            <span class="detail-label">Node ID</span>
                            <span class="detail-value">{{ selectedNode.node_id }}</span>
                            <span class="detail-label">Browse Name</span>
                            <span class="detail-value">{{ selectedNode.browse_name }}</span>
                            <span class="detail-label">Node Class</span>
                            <span class="detail-value">{{ selectedNode.node_class }}</span>
                            <template v-if="selectedNode.node_class === 'Variable'">
                                <span class="detail-label">Data Type</span>
                                <span class="detail-value">{{ selectedNode.data_type }}</span>
                                <span class="detail-label">Writable</span>
                                <span class="detail-value">{{ selectedNode.is_writable ? 'Yes' : 'No' }}</span>
                            </template>
                            <span class="detail-label">Children</span>
                            <span class="detail-value">{{ selectedNode.children_count }}</span>
                        </div>
                    </div>

                    <!-- Write control (for writable variables) -->
                    <div v-if="selectedNode.is_writable" class="write-control">
                        <h3>Write Value</h3>
                        <div class="write-row">
                            <template v-if="selectedNode.data_type === 'Boolean'">
                                <label class="toggle-switch">
                                    <input type="checkbox" v-model="writeValueBool" @change="doWrite">
                                    <div class="toggle-track"></div>
                                </label>
                                <span style="font-size:14px;">{{ writeValueBool ? 'TRUE' : 'FALSE' }}</span>
                            </template>
                            <template v-else>
                                <input
                                    v-model="writeValueText"
                                    :type="isNumericType(selectedNode.data_type) ? 'number' : 'text'"
                                    :step="isFloatType(selectedNode.data_type) ? '0.01' : '1'"
                                    @keyup.enter="doWrite"
                                    placeholder="Enter value..."
                                >
                                <button class="btn btn-primary btn-small" @click="doWrite">Write</button>
                            </template>
                        </div>
                        <div v-if="writeStatus" style="margin-top: 8px; font-size: 12px;" :style="{color: writeStatus.ok ? '#a6e3a1' : '#f38ba8'}">
                            {{ writeStatus.message }}
                        </div>
                    </div>

                    <!-- Add to monitor button -->
                    <div v-if="selectedNode.node_class === 'Variable'" style="margin-bottom: 16px;">
                        <button
                            class="btn btn-primary btn-small"
                            @click="addToMonitor(selectedNode)"
                            :disabled="isMonitored(selectedNode.node_id)"
                        >
                            {{ isMonitored(selectedNode.node_id) ? 'Already Monitored' : 'Add to Monitor' }}
                        </button>
                    </div>
                </template>
            </div>

            <!-- Monitor Panel -->
            <div v-if="monitoredNodes.length > 0" class="monitor-panel">
                <div class="monitor-header">
                    <h3>Monitored Variables ({{ monitoredNodes.length }})</h3>
                    <div style="display:flex; gap: 8px;">
                        <button class="btn btn-small" style="background:#45475a;color:#cdd6f4;" @click="refreshMonitor">Refresh</button>
                        <button class="btn btn-small" style="background:#f38ba8;color:#1e1e2e;" @click="clearMonitor">Clear</button>
                    </div>
                </div>
                <table class="monitor-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Value</th>
                            <th>Type</th>
                            <th>Quality</th>
                            <th>Timestamp</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="m in monitoredNodes" :key="m.node_id" @click="selectNodeById(m.node_id)" style="cursor:pointer;">
                            <td>{{ m.display_name || m.node_id }}</td>
                            <td style="font-weight:600; color: #a6e3a1;">{{ m.value !== undefined ? formatValue(m.value) : '...' }}</td>
                            <td style="color: #f9e2af;">{{ m.data_type }}</td>
                            <td :class="m.quality === 'Good' ? 'quality-good' : 'quality-bad'">{{ m.quality || '-' }}</td>
                            <td style="color: #6c7086; font-size: 11px;">{{ m.source_timestamp ? formatTimestamp(m.source_timestamp) : '' }}</td>
                            <td><span style="cursor:pointer; color: #f38ba8;" @click.stop="removeFromMonitor(m.node_id)">&times;</span></td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<script>
const { createApp, ref, computed, watch, onMounted, onUnmounted } = Vue;

// Tree Node component
const TreeNode = {
    name: 'TreeNode',
    props: ['node', 'selectedId', 'expandedIds', 'childrenMap', 'loadingIds'],
    emits: ['select', 'toggle'],
    template: `
        <div class="tree-node">
            <div class="tree-row" :class="{selected: node.node_id === selectedId}" @click="$emit('select', node)">
                <span class="tree-expand" @click.stop="$emit('toggle', node)">
                    <template v-if="node.children_count > 0">
                        <span v-if="loadingIds.has(node.node_id)" class="spinner" style="width:12px;height:12px;border-width:1px;"></span>
                        <template v-else>{{ expandedIds.has(node.node_id) ? '&#9660;' : '&#9654;' }}</template>
                    </template>
                </span>
                <span class="tree-icon">{{ node.node_class === 'Variable' ? '&#128202;' : '&#128193;' }}</span>
                <span class="tree-label">{{ node.display_name }}</span>
                <span class="tree-badges">
                    <span v-if="node.data_type" class="badge badge-type">{{ node.data_type }}</span>
                    <span v-if="node.is_writable" class="badge badge-rw">RW</span>
                    <span v-else-if="node.node_class === 'Variable'" class="badge badge-r">R</span>
                </span>
            </div>
            <div v-if="expandedIds.has(node.node_id) && childrenMap[node.node_id]" class="tree-children">
                <tree-node
                    v-for="child in childrenMap[node.node_id]"
                    :key="child.node_id"
                    :node="child"
                    :selected-id="selectedId"
                    :expanded-ids="expandedIds"
                    :children-map="childrenMap"
                    :loading-ids="loadingIds"
                    @select="(n) => $emit('select', n)"
                    @toggle="(n) => $emit('toggle', n)"
                />
            </div>
        </div>
    `,
};

const app = createApp({
    components: { TreeNode },
    setup() {
        // State
        const config = ref({ endpoint: '', interface: '', namespaces: [], subscription_interval_ms: 500, has_config: false });
        const connectionStatus = ref('disconnected');
        const rootNodes = ref([]);
        const selectedNode = ref(null);
        const selectedNodeId = computed(() => selectedNode.value ? selectedNode.value.node_id : null);
        const currentValue = ref(null);
        const searchQuery = ref('');
        const expandedIds = ref(new Set());
        const childrenMap = ref({});
        const loadingIds = ref(new Set());
        const monitoredNodes = ref([]);
        const writeValueText = ref('');
        const writeValueBool = ref(false);
        const writeStatus = ref(null);
        const breadcrumbs = ref([]);
        const allNodesFlat = ref({}); // node_id -> node for breadcrumb navigation
        let pollInterval = null;

        // Fetch config on mount
        onMounted(async () => {
            try {
                const r = await fetch('/api/sim/config');
                config.value = await r.json();
            } catch (e) { console.error('Config fetch error:', e); }

            // Check existing status
            try {
                const r = await fetch('/api/sim/status');
                const s = await r.json();
                connectionStatus.value = s.status;
                if (s.status === 'connected') {
                    await loadRoots();
                }
            } catch (e) { /* ignore */ }
        });

        onUnmounted(() => { if (pollInterval) clearInterval(pollInterval); });

        // Connect
        async function doConnect() {
            connectionStatus.value = 'connecting';
            try {
                const r = await fetch('/api/sim/connect', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({}) });
                const data = await r.json();
                connectionStatus.value = data.status;
                if (data.status === 'connected') {
                    await loadRoots();
                }
            } catch (e) {
                connectionStatus.value = 'error';
                console.error('Connect error:', e);
            }
        }

        // Disconnect
        async function doDisconnect() {
            try {
                await fetch('/api/sim/disconnect', { method: 'POST' });
            } catch (e) { /* ignore */ }
            connectionStatus.value = 'disconnected';
            rootNodes.value = [];
            selectedNode.value = null;
            currentValue.value = null;
            expandedIds.value = new Set();
            childrenMap.value = {};
            if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
        }

        // Load root nodes
        async function loadRoots() {
            try {
                const r = await fetch('/api/sim/browse');
                const data = await r.json();
                rootNodes.value = data.nodes;
                data.nodes.forEach(n => { allNodesFlat.value[n.node_id] = n; });
            } catch (e) { console.error('Browse error:', e); }
        }

        // Toggle tree node expansion
        async function toggleNode(node) {
            const ids = new Set(expandedIds.value);
            if (ids.has(node.node_id)) {
                ids.delete(node.node_id);
            } else {
                ids.add(node.node_id);
                if (!childrenMap.value[node.node_id]) {
                    const lids = new Set(loadingIds.value);
                    lids.add(node.node_id);
                    loadingIds.value = lids;
                    try {
                        const r = await fetch('/api/sim/browse?node_id=' + encodeURIComponent(node.node_id));
                        const data = await r.json();
                        childrenMap.value = { ...childrenMap.value, [node.node_id]: data.nodes };
                        data.nodes.forEach(n => { allNodesFlat.value[n.node_id] = n; });
                    } catch (e) { console.error('Browse error:', e); }
                    lids.delete(node.node_id);
                    loadingIds.value = new Set(lids);
                }
            }
            expandedIds.value = ids;
        }

        // Select a node
        async function selectNode(node) {
            selectedNode.value = node;
            currentValue.value = null;
            writeStatus.value = null;

            if (!node) { breadcrumbs.value = []; return; }

            // Build breadcrumbs from parent chain
            const crumbs = [];
            let current = node;
            while (current && current.parent_node_id && allNodesFlat.value[current.parent_node_id]) {
                current = allNodesFlat.value[current.parent_node_id];
                crumbs.unshift(current);
            }
            breadcrumbs.value = [...crumbs, node];

            // Read value for variables
            if (node.node_class === 'Variable') {
                await readSelectedValue();
                // Initialize write value
                if (node.data_type === 'Boolean') {
                    writeValueBool.value = currentValue.value ? !!currentValue.value.value : false;
                } else {
                    writeValueText.value = currentValue.value ? String(currentValue.value.value) : '';
                }
            }
        }

        function selectNodeById(nodeId) {
            const node = allNodesFlat.value[nodeId];
            if (node) selectNode(node);
        }

        // Read selected variable value
        async function readSelectedValue() {
            if (!selectedNode.value || selectedNode.value.node_class !== 'Variable') return;
            try {
                const r = await fetch('/api/sim/read?node_id=' + encodeURIComponent(selectedNode.value.node_id));
                const data = await r.json();
                if (data.values && data.values.length > 0) {
                    currentValue.value = data.values[0];
                }
            } catch (e) { console.error('Read error:', e); }
        }

        // Write value
        async function doWrite() {
            if (!selectedNode.value) return;
            const val = selectedNode.value.data_type === 'Boolean' ? writeValueBool.value : writeValueText.value;
            try {
                const r = await fetch('/api/sim/write', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ node_id: selectedNode.value.node_id, value: val, data_type: selectedNode.value.data_type }),
                });
                const data = await r.json();
                if (data.success) {
                    writeStatus.value = { ok: true, message: 'Write successful' };
                    // Re-read the value
                    setTimeout(readSelectedValue, 200);
                } else {
                    writeStatus.value = { ok: false, message: data.error || 'Write failed' };
                }
            } catch (e) {
                writeStatus.value = { ok: false, message: String(e) };
            }
            setTimeout(() => { writeStatus.value = null; }, 3000);
        }

        // Monitor
        function addToMonitor(node) {
            if (monitoredNodes.value.find(m => m.node_id === node.node_id)) return;
            monitoredNodes.value.push({ ...node, value: undefined, quality: '', source_timestamp: '' });
            refreshMonitor();
            // Start polling if not already
            if (!pollInterval) {
                pollInterval = setInterval(refreshMonitor, config.value.subscription_interval_ms || 1000);
            }
        }

        function removeFromMonitor(nodeId) {
            monitoredNodes.value = monitoredNodes.value.filter(m => m.node_id !== nodeId);
            if (monitoredNodes.value.length === 0 && pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        }

        function isMonitored(nodeId) {
            return monitoredNodes.value.some(m => m.node_id === nodeId);
        }

        function clearMonitor() {
            monitoredNodes.value = [];
            if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
        }

        async function refreshMonitor() {
            if (monitoredNodes.value.length === 0 || connectionStatus.value !== 'connected') return;
            const ids = monitoredNodes.value.map(m => m.node_id);
            const params = ids.map(id => 'node_id=' + encodeURIComponent(id)).join('&');
            try {
                const r = await fetch('/api/sim/read?' + params);
                const data = await r.json();
                if (data.values) {
                    data.values.forEach(v => {
                        const m = monitoredNodes.value.find(m => m.node_id === v.node_id);
                        if (m) {
                            m.value = v.value;
                            m.data_type = v.data_type;
                            m.quality = v.quality;
                            m.source_timestamp = v.source_timestamp;
                            m.display_name = v.display_name || m.display_name;
                        }
                    });
                }
            } catch (e) { console.error('Monitor refresh error:', e); }

            // Also refresh selected value
            if (selectedNode.value && selectedNode.value.node_class === 'Variable') {
                readSelectedValue();
            }
        }

        // Filtering
        const filteredRootNodes = computed(() => {
            if (!searchQuery.value) return rootNodes.value;
            return filterNodes(rootNodes.value, searchQuery.value.toLowerCase());
        });

        function filterNodes(nodes, query) {
            return nodes.filter(n => {
                if (n.display_name.toLowerCase().includes(query)) return true;
                if (n.browse_name.toLowerCase().includes(query)) return true;
                // Check children
                const children = childrenMap.value[n.node_id];
                if (children && filterNodes(children, query).length > 0) return true;
                return false;
            });
        }

        // Formatting helpers
        function formatValue(val) {
            if (val === null || val === undefined) return 'null';
            if (typeof val === 'boolean') return val ? 'TRUE' : 'FALSE';
            if (typeof val === 'number') {
                if (Number.isInteger(val)) return val.toString();
                return val.toFixed(3);
            }
            return String(val);
        }

        function formatTimestamp(ts) {
            if (!ts) return '';
            try {
                const d = new Date(ts);
                return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 1 });
            } catch { return ts; }
        }

        function isNumericType(dt) {
            return ['Int16','UInt16','Int32','UInt32','Int64','UInt64','Float','Double','SByte','Byte'].includes(dt);
        }

        function isFloatType(dt) {
            return ['Float','Double'].includes(dt);
        }

        return {
            config, connectionStatus, rootNodes, selectedNode, selectedNodeId,
            currentValue, searchQuery, expandedIds, childrenMap, loadingIds,
            monitoredNodes, writeValueText, writeValueBool, writeStatus, breadcrumbs,
            filteredRootNodes,
            doConnect, doDisconnect, toggleNode, selectNode, selectNodeById, doWrite,
            addToMonitor, removeFromMonitor, isMonitored, clearMonitor, refreshMonitor,
            formatValue, formatTimestamp, isNumericType, isFloatType,
        };
    },
});

app.component('TreeNode', TreeNode);
app.mount('#app');
</script>
</body>
</html>"""
