# ruff: noqa: E501
"""FastAPI application for the PLC Analysis Server.

This module provides the main FastAPI application that serves:
- A landing page with navigation at /
- The MkDocs documentation site at /docs/ (when available)
- The I/O Tag Dependency Explorer at /explorer/
- The REST API at /api/
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes import analysis_router, blocks_router, config_router, tags_router, xref_router

# Create FastAPI app
app = FastAPI(
    title="PLC Analysis Server",
    description="Unified web interface for PLC documentation and I/O tag analysis",
    version="0.3.0",
)

# Add CORS middleware for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(blocks_router)
app.include_router(analysis_router)
app.include_router(config_router)
app.include_router(tags_router)
app.include_router(xref_router)

# Initialize app state defaults
app.state.docs_available = False
app.state.project_name = "PLC Analysis"


def _build_landing_html(project_name: str, docs_available: bool, sim_available: bool = False) -> str:
    """Build the landing page HTML."""
    docs_card = ""
    if docs_available:
        docs_card = """
            <a href="/docs/" class="card">
                <div class="card-icon">&#128214;</div>
                <h2>Documentation</h2>
                <p>Browse PLC block documentation, call graphs, type dependencies, and quality analysis reports.</p>
            </a>"""
    else:
        docs_card = """
            <div class="card disabled">
                <div class="card-icon">&#128214;</div>
                <h2>Documentation</h2>
                <p class="unavailable">Not available. Run <code>plc code docs &amp;&amp; mkdocs build</code> to generate.</p>
            </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1e1e2e; color: #cdd6f4; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .container {{ max-width: 720px; width: 100%; padding: 40px 20px; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; color: #cdd6f4; }}
        .subtitle {{ color: #6c7086; font-size: 14px; margin-bottom: 40px; }}
        .cards {{ display: flex; flex-direction: column; gap: 16px; }}
        .card {{ display: block; background: #313244; border-radius: 8px; padding: 24px; text-decoration: none; color: #cdd6f4; border: 1px solid #45475a; transition: border-color 0.15s, background 0.15s; }}
        a.card:hover {{ border-color: #89b4fa; background: #3b3b4f; }}
        .card.disabled {{ opacity: 0.5; cursor: default; }}
        .card-icon {{ font-size: 28px; margin-bottom: 12px; }}
        .card h2 {{ font-size: 18px; margin-bottom: 8px; }}
        .card p {{ font-size: 14px; color: #a6adc8; line-height: 1.5; }}
        .card .unavailable {{ color: #6c7086; }}
        .card code {{ background: #45475a; padding: 2px 6px; border-radius: 3px; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{project_name}</h1>
        <p class="subtitle">PLC Analysis Server</p>
        <div class="cards">{docs_card}
            <a href="/explorer/" class="card">
                <div class="card-icon">&#128268;</div>
                <h2>I/O Tag Explorer</h2>
                <p>Interactive dependency tracing for I/O tags. Trace outputs backward to inputs and inputs forward to outputs.</p>
            </a>
            <a href="/xref/" class="card">
                <div class="card-icon">&#128279;</div>
                <h2>Cross-Reference Explorer</h2>
                <p>Browse global data block variables. See who reads and writes each variable, with audit alerts and source code.</p>
            </a>{"" if not sim_available else '''
            <a href="/sim/" class="card">
                <div class="card-icon">&#9881;</div>
                <h2>PLC Simulation</h2>
                <p>Connect to a live PLC via OPC UA. Browse, read, and write variables in real time for testing and commissioning.</p>
            </a>'''}
        </div>
    </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    """Serve the unified landing page."""
    docs_available = getattr(app.state, "docs_available", False)
    sim_available = getattr(app.state, "sim_available", False)
    project_name = getattr(app.state, "project_name", "PLC Analysis")
    return HTMLResponse(content=_build_landing_html(project_name, docs_available, sim_available))


@app.get("/explorer", response_class=HTMLResponse)
@app.get("/explorer/", response_class=HTMLResponse)
async def explorer() -> HTMLResponse:
    """Serve the I/O Tag Dependency Explorer."""
    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PLC I/O Tag Dependency Explorer</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        .app { display: flex; height: 100vh; }
        .sidebar { width: 300px; background: #1e1e2e; color: #cdd6f4; overflow-y: auto; flex-shrink: 0; }
        .sidebar-header { padding: 16px; background: #313244; font-size: 14px; font-weight: 600; }
        .main { flex: 1; display: flex; flex-direction: column; background: #f5f5f5; min-width: 0; }
        .header { padding: 16px; background: white; border-bottom: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 20px; color: #333; }
        .content { flex: 1; display: flex; overflow: hidden; }
        .panel { flex: 1; padding: 16px; overflow-y: auto; }
        .search-box { padding: 12px; }
        .search-box input { width: 100%; padding: 8px 12px; border: none; border-radius: 4px; background: #313244; color: #cdd6f4; }
        .search-box input::placeholder { color: #6c7086; }
        .category-header { padding: 10px 16px; background: #313244; cursor: pointer; display: flex; align-items: center; justify-content: space-between; font-size: 13px; }
        .category-header:hover { background: #3b3b4f; }
        .category-badge { background: #45475a; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
        .category-output { border-left: 3px solid #4CAF50; }
        .category-input { border-left: 3px solid #2196F3; }
        .tag-item { padding: 8px 16px 8px 24px; cursor: pointer; border-bottom: 1px solid #2a2a3a; font-size: 13px; }
        .tag-item:hover { background: #313244; }
        .tag-item.selected { background: #45475a; }
        .tag-name { font-weight: 500; font-family: monospace; }
        .tag-meta { font-size: 11px; color: #6c7086; margin-top: 2px; }
        .empty-state { text-align: center; padding: 40px; color: #666; }
        .config-form { padding: 20px; background: white; border-radius: 8px; margin-bottom: 16px; }
        .config-form input { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; margin: 8px 0; }
        .config-form button { padding: 8px 16px; background: #1e66f5; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .config-form button:hover { background: #1558d6; }
        .loading { color: #666; font-style: italic; }
        .tag-detail { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .tag-detail h2 { font-size: 18px; margin-bottom: 12px; font-family: monospace; color: #1e66f5; }
        .tag-detail-row { display: flex; margin-bottom: 8px; font-size: 14px; }
        .tag-detail-label { width: 120px; color: #666; }
        .tag-detail-value { flex: 1; font-family: monospace; }
        .dep-tree { background: #f8f9fa; border-radius: 8px; padding: 16px; margin-top: 16px; }
        .dep-tree h3 { font-size: 14px; margin-bottom: 12px; color: #333; }
        .tree-node { padding: 4px 0; }
        .tree-node-content { display: flex; align-items: center; }
        .tree-indent { width: 20px; display: inline-block; }
        .tree-icon { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; margin-right: 6px; font-size: 10px; border-radius: 3px; }
        .tree-icon.io_tag { background: #4CAF50; color: white; }
        .tree-icon.state_var { background: #FF9800; color: white; }
        .tree-icon.field { background: #2196F3; color: white; }
        .tree-icon.local { background: #9E9E9E; color: white; }
        .tree-name { font-family: monospace; font-size: 13px; }
        .tree-block { font-size: 11px; color: #666; margin-left: 8px; }
        .tree-block-link { font-size: 11px; color: #1e66f5; margin-left: 8px; cursor: pointer; text-decoration: underline; }
        .tree-block-link:hover { color: #1558d6; }
        .tree-connector { display: inline-block; width: 20px; color: #ccc; font-family: monospace; user-select: none; }
        .blocks-list { margin-top: 16px; }
        .blocks-list h3 { font-size: 14px; margin-bottom: 8px; }
        .block-chip { display: inline-block; background: #e3f2fd; color: #1565c0; padding: 4px 10px; border-radius: 12px; margin: 4px; font-size: 12px; }
        .terminal-list { margin-top: 16px; }
        .terminal-chip { display: inline-block; padding: 4px 10px; border-radius: 12px; margin: 4px; font-size: 12px; }
        .terminal-chip.io_tag { background: #e8f5e9; color: #2e7d32; }
        .terminal-chip.state_var { background: #fff3e0; color: #e65100; }
        .tree-filters { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
        .tree-filters span.filter-label { font-size: 12px; color: #666; margin-right: 4px; }
        .filter-btn { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 22px; border: 2px solid transparent; border-radius: 4px; cursor: pointer; font-size: 10px; font-weight: 700; transition: opacity 0.15s, border-color 0.15s; }
        .filter-btn.active { opacity: 1; }
        .filter-btn.inactive { opacity: 0.3; border-color: #ccc; }
        .filter-btn.io_tag { background: #4CAF50; color: white; }
        .filter-btn.state_var { background: #FF9800; color: white; }
        .filter-btn.field { background: #2196F3; color: white; }
        .filter-btn.local { background: #9E9E9E; color: white; }
        .code-viewer { background: #1e1e2e; border-radius: 8px; margin-top: 12px; overflow: hidden; }
        .code-viewer-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #313244; color: #cdd6f4; font-size: 12px; }
        .code-viewer-header .block-title { font-family: monospace; font-weight: 600; }
        .code-viewer-close { background: none; border: none; color: #cdd6f4; cursor: pointer; font-size: 14px; padding: 2px 6px; border-radius: 4px; }
        .code-viewer-close:hover { background: #45475a; }
        .code-lines { padding: 8px 0; max-height: 320px; overflow-y: auto; font-family: monospace; font-size: 12px; line-height: 1.5; }
        .code-line { display: flex; padding: 0 12px; white-space: pre; }
        .code-line.highlight { background: rgba(30, 102, 245, 0.25); }
        .code-line-num { width: 40px; text-align: right; color: #6c7086; padding-right: 12px; user-select: none; flex-shrink: 0; }
        .code-line-text { color: #cdd6f4; }
    </style>
</head>
<body>
    <div id="app">
        <div class="app">
            <aside class="sidebar">
                <div class="sidebar-header">I/O Tags</div>
                <div class="search-box">
                    <input type="text" v-model="search" placeholder="Search tags...">
                </div>
                <div v-if="!config.has_config" style="padding: 16px; color: #fab387;">
                    Configure source path to load tags
                </div>
                <template v-else>
                    <!-- Outputs Section -->
                    <div class="category-header category-output" @click="toggleCategory('outputs')">
                        <span>Outputs</span>
                        <span class="category-badge">{{ outputCount }}</span>
                    </div>
                    <template v-if="expandedCategories.outputs">
                        <template v-for="cat in ['DO', 'SDO']" :key="cat">
                            <div class="category-header" style="padding-left: 24px;" @click="toggleCategory(cat)">
                                <span>{{ cat }}_ ({{ getCategoryCount(cat) }})</span>
                            </div>
                            <template v-if="expandedCategories[cat]">
                                <div v-for="tag in getFilteredTags(cat)" :key="tag.name"
                                     class="tag-item" :class="{ selected: selectedTag?.name === tag.name }"
                                     @click="selectTag(tag)">
                                    <div class="tag-name">{{ tag.name }}</div>
                                    <div class="tag-meta">{{ tag.comment || tag.address }}</div>
                                </div>
                            </template>
                        </template>
                    </template>
                    <!-- Inputs Section -->
                    <div class="category-header category-input" @click="toggleCategory('inputs')">
                        <span>Inputs</span>
                        <span class="category-badge">{{ inputCount }}</span>
                    </div>
                    <template v-if="expandedCategories.inputs">
                        <template v-for="cat in ['DI', 'SDI', 'AI', 'SAI']" :key="cat">
                            <div class="category-header" style="padding-left: 24px;" @click="toggleCategory(cat)">
                                <span>{{ cat }}_ ({{ getCategoryCount(cat) }})</span>
                            </div>
                            <template v-if="expandedCategories[cat]">
                                <div v-for="tag in getFilteredTags(cat)" :key="tag.name"
                                     class="tag-item" :class="{ selected: selectedTag?.name === tag.name }"
                                     @click="selectTag(tag)">
                                    <div class="tag-name">{{ tag.name }}</div>
                                    <div class="tag-meta">{{ tag.comment || tag.address }}</div>
                                </div>
                            </template>
                        </template>
                    </template>
                </template>
            </aside>
            <main class="main">
                <header class="header">
                    <h1>I/O Tag Dependency Explorer</h1>
                    <a href="/" style="font-size: 13px; color: #1e66f5; text-decoration: none;">Home</a>
                </header>
                <div class="content">
                    <div class="panel">
                        <div v-if="!config.has_config" class="config-form">
                            <h3>Configure Source Path</h3>
                            <p style="color: #666; margin: 8px 0;">Enter the path to your PLC program directory:</p>
                            <input type="text" v-model="sourcePath" placeholder="/path/to/plc-program">
                            <button @click="setSourcePath">Load Tags</button>
                        </div>
                        <div v-else-if="!selectedTag" class="empty-state">
                            <p>Select a tag from the sidebar to view its dependencies</p>
                            <p style="margin-top: 12px; font-size: 14px; color: #999;">
                                Output tags (DO_, SDO_) trace backward to inputs.<br>
                                Input tags (DI_, SDI_, AI_, SAI_) trace forward to outputs.
                            </p>
                        </div>
                        <div v-else>
                            <div class="tag-detail">
                                <h2>{{ selectedTag.name }}</h2>
                                <div class="tag-detail-row">
                                    <span class="tag-detail-label">Category:</span>
                                    <span class="tag-detail-value">{{ selectedTag.category }} ({{ selectedTag.direction }})</span>
                                </div>
                                <div class="tag-detail-row">
                                    <span class="tag-detail-label">Address:</span>
                                    <span class="tag-detail-value">{{ selectedTag.address }}</span>
                                </div>
                                <div class="tag-detail-row">
                                    <span class="tag-detail-label">Data Type:</span>
                                    <span class="tag-detail-value">{{ selectedTag.data_type }}</span>
                                </div>
                                <div class="tag-detail-row" v-if="selectedTag.comment">
                                    <span class="tag-detail-label">Comment:</span>
                                    <span class="tag-detail-value">{{ selectedTag.comment }}</span>
                                </div>
                                <!-- For output tags (DependencyChain - has dependency_tree) -->
                                <div class="tag-detail-row" v-if="chain?.assignment && chain?.dependency_tree">
                                    <span class="tag-detail-label">Mapped to:</span>
                                    <span class="tag-detail-value">{{ chain.assignment.mapped_field }}</span>
                                </div>
                                <div class="tag-detail-row" v-if="chain?.assignment && chain?.dependency_tree">
                                    <span class="tag-detail-label">In block:</span>
                                    <span class="tag-detail-value">
                                        <span class="tree-block-link" @click="loadSource(chain.assignment.block_name, chain.assignment.line_number)">{{ chain.assignment.block_name }}:{{ chain.assignment.line_number }}</span>
                                    </span>
                                </div>
                                <!-- For input tags (ForwardTrace - has resolved_field, no dependency_tree) -->
                                <div class="tag-detail-row" v-if="chain?.resolved_field && !chain?.dependency_tree">
                                    <span class="tag-detail-label">Mapped to:</span>
                                    <span class="tag-detail-value">{{ chain.resolved_field }}</span>
                                </div>
                                <div class="tag-detail-row" v-if="chain?.assignment && chain?.resolved_field && !chain?.dependency_tree">
                                    <span class="tag-detail-label">In block:</span>
                                    <span class="tag-detail-value">
                                        <span class="tree-block-link" @click="loadSource(chain.assignment.block_name, chain.assignment.line_number)">{{ chain.assignment.block_name }}:{{ chain.assignment.line_number }}</span>
                                    </span>
                                </div>
                            </div>
                            <p v-if="loading" class="loading">Loading dependencies...</p>
                            <template v-else-if="chain">
                                <div class="blocks-list" v-if="chain.blocks_involved.length">
                                    <h3>Blocks Involved ({{ chain.blocks_involved.length }})</h3>
                                    <span v-for="block in chain.blocks_involved" :key="block" class="block-chip">{{ block }}</span>
                                </div>
                                <div class="terminal-list" v-if="getTerminalNodes().length">
                                    <h3>Terminal Points ({{ getTerminalNodes().length }})</h3>
                                    <span v-for="node in getTerminalNodes()" :key="node"
                                          class="terminal-chip" :class="getNodeType(node)">{{ formatTerminal(node) }}</span>
                                </div>
                                <!-- Tree filters -->
                                <div class="tree-filters" v-if="chain.dependency_tree || chain.dataflow_tree">
                                    <span class="filter-label">Show:</span>
                                    <span v-for="ft in filterTypes" :key="ft.type"
                                          class="filter-btn" :class="[ft.type, treeFilters[ft.type] ? 'active' : 'inactive']"
                                          @click="treeFilters[ft.type] = !treeFilters[ft.type]"
                                          :title="ft.label">{{ ft.icon }}</span>
                                </div>
                                <!-- Tree view for output tags (has dependency_tree) -->
                                <div class="dep-tree" v-if="chain.dependency_tree">
                                    <h3>Dependency Tree (traces inputs)</h3>
                                    <div class="tree-node" v-for="(node, i) in flattenTree(chain.dependency_tree)" :key="i">
                                        <div class="tree-node-content" :style="{ paddingLeft: (node.depth * 20) + 'px' }">
                                            <span class="tree-icon" :class="node.node_type">{{ getNodeIcon(node.node_type) }}</span>
                                            <span class="tree-name">{{ node.name }}</span>
                                            <span class="tree-block-link" v-if="node.block_name" @click="loadSource(node.block_name, node.line_number)">{{ node.block_name }}{{ node.line_number ? ':' + node.line_number : '' }}</span>
                                        </div>
                                    </div>
                                </div>
                                <!-- Hierarchical data flow tree for input tags -->
                                <div class="dep-tree" v-if="chain.dataflow_tree">
                                    <h3>Data Flow Path (traces outputs)</h3>
                                    <div class="tree-node" v-for="(node, i) in flattenDataflowTree(chain.dataflow_tree)" :key="i">
                                        <div class="tree-node-content" :style="{ paddingLeft: (node.depth * 20) + 'px' }">
                                            <span class="tree-icon" :class="node.node_type">{{ getNodeIcon(node.node_type) }}</span>
                                            <span class="tree-name">{{ node.field_path }}</span>
                                            <span class="tree-block-link" v-if="node.block_name" @click="loadSource(node.block_name, node.line_number)">{{ node.block_name }}:{{ node.line_number }}</span>
                                        </div>
                                    </div>
                                </div>
                                <!-- Fallback: flat trace path if no tree -->
                                <div class="dep-tree" v-else-if="chain.trace_path">
                                    <h3>Data Flow Path (traces outputs)</h3>
                                    <div class="tree-node" v-for="(field, i) in chain.trace_path" :key="i">
                                        <div class="tree-node-content">
                                            <span class="tree-icon" :class="getFieldType(field, i)">{{ getNodeIcon(getFieldType(field, i)) }}</span>
                                            <span class="tree-name">{{ field }}</span>
                                            <span class="tree-block" v-if="getFieldBlock(field)">{{ getFieldBlock(field) }}</span>
                                        </div>
                                    </div>
                                </div>
                                <!-- Code Viewer -->
                                <div class="code-viewer" v-if="codeViewer.visible">
                                    <div class="code-viewer-header">
                                        <span class="block-title">{{ codeViewer.blockName }} (line {{ codeViewer.highlightLine }})</span>
                                        <button class="code-viewer-close" @click="codeViewer.visible = false">x</button>
                                    </div>
                                    <div class="code-lines" ref="codeContainer">
                                        <div v-for="(line, i) in codeViewer.lines" :key="i"
                                             class="code-line" :class="{ highlight: codeViewer.startLine + i === codeViewer.highlightLine }"
                                             :data-line="codeViewer.startLine + i">
                                            <span class="code-line-num">{{ codeViewer.startLine + i }}</span>
                                            <span class="code-line-text">{{ line }}</span>
                                        </div>
                                    </div>
                                </div>
                            </template>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>
    <script>
        const { createApp, ref, computed, watch, onMounted, nextTick } = Vue;

        createApp({
            setup() {
                const config = ref({ has_config: false });
                const sourcePath = ref('');
                const tags = ref([]);
                const categories = ref([]);
                const search = ref('');
                const selectedTag = ref(null);
                const chain = ref(null);
                const loading = ref(false);
                const expandedCategories = ref({ outputs: true, inputs: true, DO: false, SDO: false, DI: false, SDI: false, AI: false, SAI: false });
                const codeViewer = ref({ visible: false, blockName: '', lines: [], startLine: 1, highlightLine: 0 });
                const codeContainer = ref(null);
                const treeFilters = ref({ io_tag: true, field: true, local: true, state_var: true });
                const filterTypes = [
                    { type: 'io_tag', icon: 'IO', label: 'I/O Tags' },
                    { type: 'field', icon: 'F', label: 'Fields' },
                    { type: 'local', icon: 'L', label: 'Local Variables' },
                    { type: 'state_var', icon: 'S', label: 'State Variables' },
                ];

                const outputCount = computed(() => {
                    return categories.value.filter(c => ['DO', 'SDO'].includes(c.category)).reduce((sum, c) => sum + c.count, 0);
                });

                const inputCount = computed(() => {
                    return categories.value.filter(c => ['DI', 'SDI', 'AI', 'SAI'].includes(c.category)).reduce((sum, c) => sum + c.count, 0);
                });

                function getCategoryCount(cat) {
                    const c = categories.value.find(x => x.category === cat);
                    return c ? c.count : 0;
                }

                function getFilteredTags(category) {
                    let filtered = tags.value.filter(t => t.category === category);
                    if (search.value) {
                        const s = search.value.toLowerCase();
                        filtered = filtered.filter(t => t.name.toLowerCase().includes(s) || (t.comment && t.comment.toLowerCase().includes(s)));
                    }
                    return filtered;
                }

                function toggleCategory(cat) {
                    expandedCategories.value[cat] = !expandedCategories.value[cat];
                }

                async function loadConfig() {
                    try {
                        const res = await fetch('/api/config');
                        config.value = await res.json();
                        if (config.value.has_config) {
                            sourcePath.value = config.value.source_path;
                            loadTags();
                        }
                    } catch (e) { console.error(e); }
                }

                async function setSourcePath() {
                    try {
                        const res = await fetch('/api/config', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source_path: sourcePath.value })
                        });
                        if (res.ok) {
                            config.value = await res.json();
                            loadTags();
                        } else {
                            const err = await res.json();
                            alert(err.detail);
                        }
                    } catch (e) { console.error(e); }
                }

                async function loadTags() {
                    try {
                        const res = await fetch('/api/tags');
                        const data = await res.json();
                        tags.value = data.tags;
                        categories.value = data.categories;
                    } catch (e) { console.error(e); }
                }

                async function selectTag(tag) {
                    selectedTag.value = tag;
                    chain.value = null;
                    loading.value = true;
                    codeViewer.value = { visible: false, blockName: '', lines: [], startLine: 1, highlightLine: 0 };
                    try {
                        const res = await fetch(`/api/tags/${encodeURIComponent(tag.name)}/trace`);
                        if (res.ok) {
                            chain.value = await res.json();
                        }
                    } catch (e) { console.error(e); }
                    loading.value = false;
                }

                function flattenTree(node, depth = 0) {
                    const visible = treeFilters.value[node.node_type] !== false;
                    const result = [];
                    if (visible) {
                        result.push({ ...node, depth });
                    }
                    if (node.children) {
                        const childDepth = visible ? depth + 1 : depth;
                        for (const child of node.children) {
                            result.push(...flattenTree(child, childDepth));
                        }
                    }
                    return result;
                }

                function flattenDataflowTree(node, depth = 0) {
                    const visible = treeFilters.value[node.node_type] !== false;
                    const result = [];
                    if (visible) {
                        result.push({ ...node, depth });
                    }
                    if (node.children) {
                        const childDepth = visible ? depth + 1 : depth;
                        for (const child of node.children) {
                            result.push(...flattenDataflowTree(child, childDepth));
                        }
                    }
                    return result;
                }

                async function loadSource(blockName, lineNumber) {
                    if (!blockName) return;
                    try {
                        const ctx = 20;
                        const res = await fetch(`/api/blocks/${encodeURIComponent(blockName)}/source?line=${lineNumber}&context=${ctx}`);
                        if (res.ok) {
                            const data = await res.json();
                            codeViewer.value = {
                                visible: true,
                                blockName: data.block_name,
                                lines: data.source.split('\\n'),
                                startLine: data.start_line,
                                highlightLine: data.highlight_line,
                            };
                            await nextTick();
                            // Scroll to highlighted line
                            if (codeContainer.value) {
                                const highlighted = codeContainer.value.querySelector('.highlight');
                                if (highlighted) {
                                    highlighted.scrollIntoView({ block: 'center', behavior: 'smooth' });
                                }
                            }
                        }
                    } catch (e) { console.error(e); }
                }

                function getNodeIcon(type) {
                    const icons = { io_tag: 'IO', state_var: 'S', field: 'F', local: 'L' };
                    return icons[type] || '?';
                }

                function getNodeType(name) {
                    if (name.match(/^(DO_|SDO_|DI_|SDI_|AI_|SAI_)/)) return 'io_tag';
                    if (name.includes('-> DO_') || name.includes('-> SDO_')) return 'io_tag';
                    if (name.includes('State') || name.includes('Mode') || name.includes('.status.')) return 'state_var';
                    if (name.includes('[STATE_VAR]')) return 'state_var';
                    return 'field';
                }

                function getTerminalNodes() {
                    if (!chain.value) return [];
                    // ForwardTrace has terminal_fields
                    if (chain.value.terminal_fields) return chain.value.terminal_fields;
                    // DependencyChain has terminal_nodes
                    if (chain.value.terminal_nodes) return chain.value.terminal_nodes;
                    return [];
                }

                function formatTerminal(node) {
                    // Clean up display: "field -> TAG" -> "field -> TAG"
                    return node;
                }

                function getFieldType(field, index) {
                    // First field is input from tag
                    if (index === 0) return 'io_tag';
                    // Check if terminal
                    const terminals = chain.value?.terminal_fields || [];
                    if (terminals.some(t => t.includes(field))) return 'io_tag';
                    // Check if state var
                    if (field.includes('State') || field.includes('Mode')) return 'state_var';
                    return 'field';
                }

                function getFieldBlock(field) {
                    // Find the block where this field is used
                    if (!chain.value?.nodes) return '';
                    const node = chain.value.nodes.find(n => n.field_path.includes(field) || field.includes(n.field_path.split('[')[0]));
                    if (node) return `${node.block_name}:${node.line_number}`;
                    return '';
                }

                onMounted(loadConfig);

                return {
                    config, sourcePath, tags, categories, search, selectedTag, chain,
                    loading, expandedCategories, codeViewer, codeContainer,
                    treeFilters, filterTypes,
                    outputCount, inputCount, getCategoryCount, getFilteredTags, toggleCategory,
                    setSourcePath, selectTag, flattenTree, flattenDataflowTree, getNodeIcon, getNodeType,
                    getTerminalNodes, formatTerminal, getFieldType, getFieldBlock, loadSource
                };
            }
        }).mount('#app');
    </script>
</body>
</html>
""",
        status_code=200,
    )


@app.get("/xref", response_class=HTMLResponse)
@app.get("/xref/", response_class=HTMLResponse)
async def xref_explorer() -> HTMLResponse:
    """Serve the Cross-Reference Explorer."""
    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cross-Reference Explorer</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        .app { display: flex; height: 100vh; }
        .sidebar { width: 320px; background: #1e1e2e; color: #cdd6f4; overflow-y: auto; flex-shrink: 0; display: flex; flex-direction: column; }
        .sidebar-header { padding: 16px; background: #313244; font-size: 14px; font-weight: 600; flex-shrink: 0; }
        .sidebar-content { flex: 1; overflow-y: auto; }
        .main { flex: 1; display: flex; flex-direction: column; background: #f5f5f5; min-width: 0; }
        .header { padding: 16px; background: white; border-bottom: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
        .header h1 { font-size: 20px; color: #333; }
        .panel { flex: 1; padding: 16px; overflow-y: auto; }
        .search-box { padding: 12px; flex-shrink: 0; }
        .search-box input { width: 100%; padding: 8px 12px; border: none; border-radius: 4px; background: #313244; color: #cdd6f4; font-size: 13px; }
        .search-box input::placeholder { color: #6c7086; }

        /* DB tree */
        .db-section { border-bottom: 1px solid #2a2a3a; }
        .db-header { padding: 10px 16px; background: #313244; cursor: pointer; display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 600; }
        .db-header:hover { background: #3b3b4f; }
        .db-badge { background: #45475a; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
        .tree-row { padding: 5px 8px; cursor: pointer; font-size: 13px; display: flex; align-items: center; border-bottom: 1px solid #2a2a3a; }
        .tree-row:hover { background: #313244; }
        .tree-row.selected { background: #45475a; }
        .tree-row.is-branch { color: #a6adc8; }
        .tree-label { flex: 1; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .tree-chevron { width: 16px; text-align: center; color: #6c7086; font-size: 10px; margin-right: 4px; flex-shrink: 0; }
        .access-badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; margin-left: 6px; flex-shrink: 0; }
        .access-badge.R { background: #1e66f5; color: white; }
        .access-badge.W { background: #fe640b; color: white; }
        .access-badge.RW { background: #8839ef; color: white; }
        .violation-dot { width: 8px; height: 8px; border-radius: 50%; background: #e64553; margin-left: 6px; flex-shrink: 0; }

        /* Audit summary */
        .audit-summary { padding: 12px 16px; background: #313244; border-top: 1px solid #45475a; flex-shrink: 0; font-size: 12px; cursor: pointer; }
        .audit-summary:hover { background: #3b3b4f; }
        .audit-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .audit-row:last-child { margin-bottom: 0; }
        .audit-icon-err { color: #e64553; }
        .audit-icon-warn { color: #fe640b; }

        /* Main panel */
        .empty-state { text-align: center; padding: 40px; color: #666; }
        .config-form { padding: 20px; background: white; border-radius: 8px; margin-bottom: 16px; }
        .config-form input { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; margin: 8px 0; }
        .config-form button { padding: 8px 16px; background: #1e66f5; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .config-form button:hover { background: #1558d6; }

        /* Variable detail */
        .var-detail { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .var-detail h2 { font-size: 16px; margin-bottom: 12px; font-family: monospace; color: #1e66f5; word-break: break-all; }
        .var-meta { display: flex; gap: 12px; margin-bottom: 16px; font-size: 13px; }
        .var-meta-item { display: flex; align-items: center; gap: 4px; }
        .var-meta-label { color: #666; }

        /* Reference tables */
        .ref-section { margin-bottom: 16px; }
        .ref-section h3 { font-size: 14px; margin-bottom: 8px; color: #333; display: flex; align-items: center; gap: 6px; }
        .ref-count { background: #e3e3e3; padding: 1px 8px; border-radius: 10px; font-size: 11px; color: #666; }
        .ref-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .ref-table th { text-align: left; padding: 8px 12px; background: #f8f9fa; border-bottom: 2px solid #ddd; color: #666; font-weight: 600; }
        .ref-table td { padding: 8px 12px; border-bottom: 1px solid #eee; }
        .ref-table tr:hover { background: #f8f9fa; }
        .block-link { color: #1e66f5; cursor: pointer; text-decoration: underline; font-family: monospace; }
        .block-link:hover { color: #1558d6; }
        .indices { font-family: monospace; font-size: 12px; color: #888; }

        /* Index filter */
        .index-filter { display: flex; align-items: center; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; }
        .index-filter-label { font-size: 13px; color: #666; margin-right: 4px; }
        .index-chip { padding: 4px 12px; border-radius: 16px; font-size: 12px; cursor: pointer; border: 1px solid #ddd; background: white; font-family: monospace; transition: background 0.15s, border-color 0.15s; }
        .index-chip:hover { border-color: #89b4fa; }
        .index-chip.active { background: #1e66f5; color: white; border-color: #1e66f5; }

        /* Audit alerts */
        .alert { padding: 12px 16px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; display: flex; align-items: flex-start; gap: 8px; }
        .alert-error { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; }
        .alert-warning { background: #fffbeb; border: 1px solid #fed7aa; color: #92400e; }
        .alert-icon { font-size: 16px; flex-shrink: 0; }
        .alert-body { flex: 1; }
        .alert-rule { font-weight: 600; }

        /* Code viewer */
        .code-viewer { background: #1e1e2e; border-radius: 8px; margin-top: 12px; overflow: hidden; }
        .code-viewer-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #313244; color: #cdd6f4; font-size: 12px; }
        .code-viewer-header .block-title { font-family: monospace; font-weight: 600; }
        .code-viewer-close { background: none; border: none; color: #cdd6f4; cursor: pointer; font-size: 14px; padding: 2px 6px; border-radius: 4px; }
        .code-viewer-close:hover { background: #45475a; }
        .code-lines { padding: 8px 0; max-height: 320px; overflow-y: auto; font-family: monospace; font-size: 12px; line-height: 1.5; }
        .code-line { display: flex; padding: 0 12px; white-space: pre; }
        .code-line.highlight { background: rgba(30, 102, 245, 0.25); }
        .code-line-num { width: 40px; text-align: right; color: #6c7086; padding-right: 12px; user-select: none; flex-shrink: 0; }
        .code-line-text { color: #cdd6f4; }

        /* DB overview */
        .db-overview { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .db-overview h2 { font-size: 18px; margin-bottom: 12px; font-family: monospace; color: #333; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .stat-card { background: #f8f9fa; border-radius: 6px; padding: 12px; text-align: center; }
        .stat-value { font-size: 24px; font-weight: 700; color: #333; }
        .stat-label { font-size: 11px; color: #888; margin-top: 4px; }
        .var-list-item { padding: 8px 12px; border-bottom: 1px solid #eee; display: flex; align-items: center; cursor: pointer; font-size: 13px; }
        .var-list-item:hover { background: #f8f9fa; }
        .var-list-path { flex: 1; font-family: monospace; }

        /* Audit view */
        .audit-view { background: white; border-radius: 8px; padding: 20px; }
        .audit-view h2 { font-size: 18px; margin-bottom: 16px; }
        .audit-filter-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
        .filter-chip { padding: 4px 12px; border-radius: 16px; font-size: 12px; cursor: pointer; border: 1px solid #ddd; background: white; }
        .filter-chip.active { background: #1e66f5; color: white; border-color: #1e66f5; }
        .audit-item { padding: 12px; border-bottom: 1px solid #eee; cursor: pointer; }
        .audit-item:hover { background: #f8f9fa; }
        .audit-item-header { display: flex; align-items: center; gap: 8px; font-size: 13px; }
        .audit-item-ref { font-family: monospace; color: #1e66f5; flex: 1; }
        .severity-badge { padding: 1px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; }
        .severity-badge.error { background: #fef2f2; color: #991b1b; }
        .severity-badge.warning { background: #fffbeb; color: #92400e; }
        .audit-item-msg { font-size: 12px; color: #666; margin-top: 4px; }

        .loading { color: #666; font-style: italic; padding: 20px; }
    </style>
</head>
<body>
    <div id="app">
        <div class="app">
            <!-- Sidebar -->
            <aside class="sidebar">
                <div class="sidebar-header">Global Data Blocks</div>
                <div class="search-box">
                    <input type="text" v-model="search" placeholder="Search variables...">
                </div>
                <div class="sidebar-content">
                    <div v-if="!config.has_config" style="padding: 16px; color: #fab387;">
                        Configure source path to load data
                    </div>
                    <div v-else-if="loadingTree" style="padding: 16px; color: #6c7086;">Loading...</div>
                    <template v-else>
                        <!-- Search results -->
                        <template v-if="search">
                            <div v-for="v in searchResults" :key="v.full_reference"
                                 class="tree-row" :class="{ selected: selectedVar === v.full_reference }"
                                 @click="selectVariable(v.full_reference)">
                                <span class="tree-label">{{ v.normalized_path }}</span>
                                <span class="access-badge" :class="v.access_type.replace('/', '')">{{ v.access_type }}</span>
                                <span v-if="v.violation_count" class="violation-dot"></span>
                            </div>
                        </template>
                        <!-- DB tree -->
                        <template v-else>
                            <div v-for="db in dbList" :key="db.name" class="db-section">
                                <div class="db-header" @click="toggleDB(db.name)">
                                    <span>{{ db.name }}</span>
                                    <span class="db-badge">{{ db.variable_count }}</span>
                                </div>
                                <template v-if="expandedDBs[db.name] && dbTrees[db.name]">
                                    <template v-for="node in flattenedTree(db.name)" :key="node.path">
                                        <div class="tree-row"
                                             :class="{ selected: selectedVar === node.full_reference, 'is-branch': !node.is_leaf }"
                                             :style="{ paddingLeft: (12 + node.depth * 16) + 'px' }"
                                             @click="node.is_leaf ? selectVariable(node.full_reference) : toggleNode(db.name, node.path)">
                                            <span class="tree-chevron">{{ node.is_leaf ? '' : (expandedNodes[db.name + '/' + node.path] ? '&#9660;' : '&#9654;') }}</span>
                                            <span class="tree-label">{{ node.name }}</span>
                                            <span v-if="node.is_leaf" class="access-badge" :class="node.access_type.replace('/', '')">{{ node.access_type }}</span>
                                            <span v-if="node.violation_count" class="violation-dot"></span>
                                        </div>
                                    </template>
                                </template>
                            </div>
                        </template>
                    </template>
                </div>
                <!-- Audit summary -->
                <div v-if="config.has_config && auditStats" class="audit-summary" @click="showAuditView">
                    <div class="audit-row" v-if="auditStats.errors">
                        <span class="audit-icon-err">&#9888;</span>
                        <span>{{ auditStats.errors }} error{{ auditStats.errors > 1 ? 's' : '' }}</span>
                    </div>
                    <div class="audit-row" v-if="auditStats.warnings">
                        <span class="audit-icon-warn">&#9888;</span>
                        <span>{{ auditStats.warnings }} warning{{ auditStats.warnings > 1 ? 's' : '' }}</span>
                    </div>
                    <div v-if="!auditStats.errors && !auditStats.warnings" style="color: #a6e3a1;">No issues found</div>
                </div>
            </aside>

            <!-- Main panel -->
            <main class="main">
                <header class="header">
                    <h1>Cross-Reference Explorer</h1>
                    <a href="/" style="font-size: 13px; color: #1e66f5; text-decoration: none;">Home</a>
                </header>
                <div class="panel">
                    <!-- Config form -->
                    <div v-if="!config.has_config" class="config-form">
                        <h3>Configure Source Path</h3>
                        <p style="color: #666; margin: 8px 0;">Enter the path to your PLC program directory:</p>
                        <input type="text" v-model="sourcePath" placeholder="/path/to/plc-program">
                        <button @click="setSourcePath">Load</button>
                    </div>

                    <!-- Audit view -->
                    <div v-else-if="viewMode === 'audit'" class="audit-view">
                        <h2>Audit Report</h2>
                        <div class="audit-filter-bar">
                            <span class="filter-chip" :class="{ active: auditFilter === null }" @click="auditFilter = null">All ({{ auditViolations.length }})</span>
                            <span class="filter-chip" :class="{ active: auditFilter === 'error' }" @click="auditFilter = 'error'">Errors ({{ auditStats.errors }})</span>
                            <span class="filter-chip" :class="{ active: auditFilter === 'warning' }" @click="auditFilter = 'warning'">Warnings ({{ auditStats.warnings }})</span>
                        </div>
                        <div v-for="v in filteredAuditViolations" :key="v.full_reference + v.rule_id" class="audit-item" @click="selectVariable(v.full_reference)">
                            <div class="audit-item-header">
                                <span class="severity-badge" :class="v.severity">{{ v.severity }}</span>
                                <span style="font-weight:600; font-size:12px; color:#666;">{{ v.rule_id }}</span>
                                <span class="audit-item-ref">{{ v.full_reference }}</span>
                            </div>
                            <div class="audit-item-msg">{{ v.message }}</div>
                        </div>
                    </div>

                    <!-- DB overview -->
                    <div v-else-if="viewMode === 'db'" class="db-overview">
                        <h2>{{ selectedDB }}</h2>
                        <div class="stats-grid">
                            <div class="stat-card"><div class="stat-value">{{ dbOverview.variable_count }}</div><div class="stat-label">Variables</div></div>
                            <div class="stat-card"><div class="stat-value">{{ dbOverview.reader_blocks }}</div><div class="stat-label">Reader Blocks</div></div>
                            <div class="stat-card"><div class="stat-value">{{ dbOverview.writer_blocks }}</div><div class="stat-label">Writer Blocks</div></div>
                            <div class="stat-card"><div class="stat-value">{{ dbOverview.violation_count }}</div><div class="stat-label">Violations</div></div>
                        </div>
                        <h3 style="font-size: 14px; margin-bottom: 8px;">Variables</h3>
                        <div v-for="v in dbVariables" :key="v.full_reference" class="var-list-item" @click="selectVariable(v.full_reference)">
                            <span class="var-list-path">{{ v.normalized_path }}</span>
                            <span class="access-badge" :class="v.access_type.replace('/', '')">{{ v.access_type }}</span>
                            <span v-if="v.violation_count" class="violation-dot"></span>
                        </div>
                    </div>

                    <!-- Variable detail -->
                    <div v-else-if="viewMode === 'variable' && varDetail">
                        <div class="var-detail">
                            <h2>{{ varDetail.full_reference }}</h2>
                            <div class="var-meta">
                                <div class="var-meta-item">
                                    <span class="var-meta-label">DB:</span>
                                    <span style="font-family: monospace; cursor: pointer; color: #1e66f5;" @click="selectDB(varDetail.db_name)">{{ varDetail.db_name }}</span>
                                </div>
                                <div class="var-meta-item">
                                    <span class="var-meta-label">Access:</span>
                                    <span class="access-badge" :class="varDetail.access_type.replace('/', '')">{{ varDetail.access_type }}</span>
                                </div>
                            </div>

                            <!-- Index filter -->
                            <div v-if="availableIndices.length > 1" class="index-filter">
                                <span class="index-filter-label">Index:</span>
                                <span class="index-chip" :class="{ active: selectedIndex === null }" @click="selectedIndex = null">All</span>
                                <span v-for="idx in availableIndices" :key="idx"
                                      class="index-chip" :class="{ active: selectedIndex === idx }"
                                      @click="selectedIndex = idx">{{ idx }}</span>
                            </div>

                            <!-- Writers -->
                            <div class="ref-section">
                                <h3><span style="color: #fe640b;">Writers</span> <span class="ref-count">{{ filteredWriters.length }}</span></h3>
                                <table class="ref-table" v-if="filteredWriters.length">
                                    <thead><tr><th>Block</th><th>Index</th><th>Source</th></tr></thead>
                                    <tbody>
                                        <tr v-for="(w, i) in filteredWriters" :key="w.block_name + ':' + w.line_number + ':' + i">
                                            <td><span class="block-link" @click="loadSource(w.block_name, w.line_number)">{{ w.block_name }}</span></td>
                                            <td><span class="indices">{{ w.original_indices.join(', ') || '-' }}</span></td>
                                            <td><span class="block-link" v-if="w.line_number" @click="loadSource(w.block_name, w.line_number)">:{{ w.line_number }}</span></td>
                                        </tr>
                                    </tbody>
                                </table>
                                <p v-else style="font-size: 13px; color: #999;">No writers</p>
                            </div>

                            <!-- Readers -->
                            <div class="ref-section">
                                <h3><span style="color: #1e66f5;">Readers</span> <span class="ref-count">{{ filteredReaders.length }}</span></h3>
                                <table class="ref-table" v-if="filteredReaders.length">
                                    <thead><tr><th>Block</th><th>Index</th><th>Source</th></tr></thead>
                                    <tbody>
                                        <tr v-for="(r, i) in filteredReaders" :key="r.block_name + ':' + r.line_number + ':' + i">
                                            <td><span class="block-link" @click="loadSource(r.block_name, r.line_number)">{{ r.block_name }}</span></td>
                                            <td><span class="indices">{{ r.original_indices.join(', ') || '-' }}</span></td>
                                            <td><span class="block-link" v-if="r.line_number" @click="loadSource(r.block_name, r.line_number)">:{{ r.line_number }}</span></td>
                                        </tr>
                                    </tbody>
                                </table>
                                <p v-else style="font-size: 13px; color: #999;">No readers</p>
                            </div>
                        </div>

                        <!-- Audit alerts -->
                        <div v-if="varDetail.violations.length">
                            <div v-for="v in varDetail.violations" :key="v.rule_id"
                                 class="alert" :class="'alert-' + v.severity">
                                <span class="alert-icon">{{ v.severity === 'error' ? '&#10060;' : '&#9888;' }}</span>
                                <div class="alert-body">
                                    <span class="alert-rule">{{ v.rule_id }}</span> {{ v.message }}
                                </div>
                            </div>
                        </div>

                        <!-- Code viewers -->
                        <div v-for="(cv, i) in codeViewers" :key="i" class="code-viewer">
                            <div class="code-viewer-header">
                                <span class="block-title">{{ cv.blockName }} (line {{ cv.highlightLine }})</span>
                                <button class="code-viewer-close" @click="codeViewers.splice(i, 1)">x</button>
                            </div>
                            <div class="code-lines" :ref="el => codeRefs[i] = el">
                                <div v-for="(line, j) in cv.lines" :key="j"
                                     class="code-line" :class="{ highlight: cv.startLine + j === cv.highlightLine }">
                                    <span class="code-line-num">{{ cv.startLine + j }}</span>
                                    <span class="code-line-text">{{ line }}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Default empty state -->
                    <div v-else class="empty-state">
                        <p style="font-size: 16px; color: #333;">Select a variable from the sidebar</p>
                        <p style="margin-top: 12px; font-size: 14px; color: #999;">
                            Browse the data block tree on the left to view cross-references.<br>
                            Click the audit summary to see all violations.
                        </p>
                    </div>
                </div>
            </main>
        </div>
    </div>
    <script>
        const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;

        createApp({
            setup() {
                const config = ref({ has_config: false });
                const sourcePath = ref('');
                const search = ref('');
                const loadingTree = ref(false);
                const viewMode = ref('empty'); // empty, variable, db, audit
                const selectedVar = ref(null);
                const selectedDB = ref(null);
                const varDetail = ref(null);
                const dbOverview = ref(null);
                const dbVariables = ref([]);
                const dbList = ref([]);
                const dbTrees = reactive({});
                const expandedDBs = reactive({});
                const expandedNodes = reactive({});
                const allVariables = ref([]);
                const auditStats = ref(null);
                const auditViolations = ref([]);
                const auditFilter = ref(null);
                const codeViewers = ref([]);
                const codeRefs = ref({});
                const selectedIndex = ref(null);

                const searchResults = computed(() => {
                    if (!search.value) return [];
                    const s = search.value.toLowerCase();
                    return allVariables.value.filter(v =>
                        v.full_reference.toLowerCase().includes(s) ||
                        v.normalized_path.toLowerCase().includes(s)
                    ).slice(0, 50);
                });

                const filteredAuditViolations = computed(() => {
                    if (!auditFilter.value) return auditViolations.value;
                    return auditViolations.value.filter(v => v.severity === auditFilter.value);
                });

                const availableIndices = computed(() => {
                    if (!varDetail.value) return [];
                    const indices = new Set();
                    for (const ref of [...varDetail.value.writers, ...varDetail.value.readers]) {
                        for (const idx of ref.original_indices) {
                            indices.add(idx);
                        }
                    }
                    // Sort: numeric first (ascending), then strings
                    return [...indices].sort((a, b) => {
                        const na = Number(a), nb = Number(b);
                        const aNum = !isNaN(na), bNum = !isNaN(nb);
                        if (aNum && bNum) return na - nb;
                        if (aNum) return -1;
                        if (bNum) return 1;
                        return a.localeCompare(b);
                    });
                });

                function filterByIndex(refs) {
                    if (selectedIndex.value === null) return refs;
                    return refs.filter(r => r.original_indices.includes(selectedIndex.value));
                }

                const filteredWriters = computed(() => {
                    if (!varDetail.value) return [];
                    return filterByIndex(varDetail.value.writers);
                });

                const filteredReaders = computed(() => {
                    if (!varDetail.value) return [];
                    return filterByIndex(varDetail.value.readers);
                });

                function flattenedTree(dbName) {
                    const tree = dbTrees[dbName];
                    if (!tree) return [];
                    const result = [];
                    function walk(nodes, depth, parentPath) {
                        for (const node of nodes) {
                            const path = parentPath ? parentPath + '.' + node.name : node.name;
                            const expanded = expandedNodes[dbName + '/' + path] !== false;
                            result.push({ ...node, depth, path });
                            if (!node.is_leaf && expanded && node.children) {
                                walk(node.children, depth + 1, path);
                            }
                        }
                    }
                    if (tree.children) walk(tree.children, 0, '');
                    return result;
                }

                function toggleDB(name) {
                    expandedDBs[name] = !expandedDBs[name];
                    if (expandedDBs[name] && !dbTrees[name]) {
                        loadDBTree(name);
                    }
                }

                function toggleNode(dbName, path) {
                    const key = dbName + '/' + path;
                    expandedNodes[key] = expandedNodes[key] === false ? true : false;
                }

                async function loadConfig() {
                    try {
                        const res = await fetch('/api/config');
                        config.value = await res.json();
                        if (config.value.has_config) {
                            sourcePath.value = config.value.source_path;
                            loadData();
                        }
                    } catch (e) { console.error(e); }
                }

                async function setSourcePath() {
                    try {
                        const res = await fetch('/api/config', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source_path: sourcePath.value })
                        });
                        if (res.ok) {
                            config.value = await res.json();
                            loadData();
                        }
                    } catch (e) { console.error(e); }
                }

                async function loadData() {
                    loadingTree.value = true;
                    try {
                        const [dbRes, varRes, auditRes] = await Promise.all([
                            fetch('/api/xref/dbs'),
                            fetch('/api/xref/variables'),
                            fetch('/api/xref/audit'),
                        ]);
                        const dbData = await dbRes.json();
                        const varData = await varRes.json();
                        const auditData = await auditRes.json();
                        dbList.value = dbData.dbs;
                        allVariables.value = varData.variables;
                        auditStats.value = auditData.statistics;
                        auditViolations.value = auditData.violations;
                    } catch (e) { console.error(e); }
                    loadingTree.value = false;
                }

                async function loadDBTree(name) {
                    try {
                        const res = await fetch(`/api/xref/dbs/${encodeURIComponent(name)}/tree`);
                        if (res.ok) {
                            const data = await res.json();
                            dbTrees[name] = data.tree;
                        }
                    } catch (e) { console.error(e); }
                }

                async function selectVariable(fullRef) {
                    selectedVar.value = fullRef;
                    viewMode.value = 'variable';
                    codeViewers.value = [];
                    selectedIndex.value = null;
                    try {
                        const res = await fetch(`/api/xref/variables/${encodeURIComponent(fullRef)}`);
                        if (res.ok) {
                            varDetail.value = await res.json();
                        }
                    } catch (e) { console.error(e); }
                }

                function selectDB(name) {
                    selectedDB.value = name;
                    viewMode.value = 'db';
                    const db = dbList.value.find(d => d.name === name);
                    dbOverview.value = db || { variable_count: 0, reader_blocks: 0, writer_blocks: 0, violation_count: 0 };
                    dbVariables.value = allVariables.value.filter(v => v.db_name === name);
                }

                function showAuditView() {
                    viewMode.value = 'audit';
                    auditFilter.value = null;
                }

                async function loadSource(blockName, lineNumber) {
                    if (!blockName) return;
                    try {
                        const ctx = 20;
                        const ln = lineNumber || 1;
                        const res = await fetch(`/api/blocks/${encodeURIComponent(blockName)}/source?line=${ln}&context=${ctx}`);
                        if (res.ok) {
                            const data = await res.json();
                            codeViewers.value.push({
                                blockName: data.block_name,
                                lines: data.source.split('\\n'),
                                startLine: data.start_line,
                                highlightLine: data.highlight_line,
                            });
                            await nextTick();
                            const idx = codeViewers.value.length - 1;
                            const container = codeRefs.value[idx];
                            if (container) {
                                const hl = container.querySelector('.highlight');
                                if (hl) hl.scrollIntoView({ block: 'center', behavior: 'smooth' });
                            }
                        }
                    } catch (e) { console.error(e); }
                }

                onMounted(loadConfig);

                return {
                    config, sourcePath, search, loadingTree, viewMode,
                    selectedVar, selectedDB, varDetail, dbOverview, dbVariables,
                    dbList, dbTrees, expandedDBs, expandedNodes,
                    allVariables, auditStats, auditViolations, auditFilter,
                    codeViewers, codeRefs, selectedIndex,
                    searchResults, filteredAuditViolations,
                    availableIndices, filteredWriters, filteredReaders,
                    flattenedTree, toggleDB, toggleNode,
                    setSourcePath, selectVariable, selectDB, showAuditView, loadSource,
                };
            }
        }).mount('#app');
    </script>
</body>
</html>
""",
        status_code=200,
    )


def create_app(
    source_path: Path | None = None,
    docs_site_path: Path | None = None,
    project_name: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    source_path : Path | None
        Initial source path for PLC programs.
    docs_site_path : Path | None
        Path to pre-built MkDocs site directory. When provided,
        the documentation is served at /docs/.
    project_name : str | None
        Project name shown on the landing page.

    Returns
    -------
    FastAPI
        Configured FastAPI application.
    """
    if source_path:
        from .services import set_source_path

        set_source_path(source_path)

    if project_name:
        app.state.project_name = project_name

    if docs_site_path and docs_site_path.exists():
        app.mount("/docs", StaticFiles(directory=docs_site_path, html=True), name="docs")
        app.state.docs_available = True

    # Mount plc-sim routes if the package is installed
    try:
        from plc_sim.core.config import load_sim_config
        from plc_sim.web import sim_router
        from plc_sim.web.page import register_sim_page
        from plc_sim.web.services import get_sim_service

        # Load sim config from the same plc.yaml
        try:
            sim_config = load_sim_config()
            get_sim_service().set_config(sim_config)
        except (FileNotFoundError, KeyError):
            pass  # No sim: section — service will use defaults

        app.include_router(sim_router)
        register_sim_page(app)
        app.state.sim_available = True
    except ImportError:
        app.state.sim_available = False

    return app
