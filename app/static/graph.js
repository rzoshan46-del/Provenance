/**
 * Provenance Graph visualization using Cytoscape.js
 */

const NODE_COLORS = {
  User: "#3b82f6",         // Blue
  Project: "#6366f1",      // Indigo
  Milestone: "#06b6d4",    // Cyan
  Contribution: "#10b981", // Emerald
  Review: "#f97316",       // Orange
  Skill: "#ec4899",        // Pink
  Credential: "#eab308",   // Yellow
  Node: "#64748b"          // Slate
};

const AI_BORDER_COLORS = {
  human: "#10b981",          // Green
  ai_assisted: "#f59e0b",    // Amber
  agent_generated: "#8b5cf6" // Violet
};

function initGraphViewer(containerId, apiUrl, options = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = `
    <div class="graph-wrapper" style="position: relative; width: 100%; min-height: 400px; height: 100%; border: 1px solid var(--border-color, #e2e8f0); border-radius: 8px; overflow: hidden; background: var(--bg-surface, #ffffff);">
      <div class="graph-header" style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(0,0,0,0.02); border-bottom: 1px solid var(--border-color, #e2e8f0); flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-weight: 600; font-size: 0.9rem;">Provenance Graph</span>
          <span id="${containerId}-badge" class="badge" style="font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; background: #e0f2fe; color: #0369a1;">Loading...</span>
        </div>
        <div style="display: flex; gap: 6px;">
          <button id="${containerId}-fit" style="padding: 4px 8px; font-size: 0.8rem; border-radius: 4px; border: 1px solid #cbd5e1; background: #fff; cursor: pointer;">Fit View</button>
        </div>
      </div>
      <div id="${containerId}-cy" style="width: 100%; height: calc(100% - 45px); min-height: 360px;"></div>
      <div id="${containerId}-empty" style="display: none; position: absolute; inset: 0; align-items: center; justify-content: center; background: rgba(255,255,255,0.9); color: #64748b; font-size: 0.9rem;">No graph elements found.</div>
      <div id="${containerId}-error" style="display: none; position: absolute; inset: 0; align-items: center; justify-content: center; background: rgba(255,255,255,0.9); color: #ef4444; font-size: 0.9rem;">Unable to load graph.</div>
      <div id="${containerId}-details" style="display: none; position: absolute; right: 0; top: 45px; bottom: 0; width: 280px; max-width: 80%; background: #ffffff; border-left: 1px solid #e2e8f0; padding: 12px; box-shadow: -2px 0 6px rgba(0,0,0,0.05); overflow-y: auto; z-index: 10;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <h4 id="${containerId}-details-title" style="margin: 0; font-size: 0.95rem;">Node Details</h4>
          <button id="${containerId}-details-close" style="border: none; background: transparent; cursor: pointer; font-size: 1.2rem;">&times;</button>
        </div>
        <div id="${containerId}-details-body" style="font-size: 0.85rem; color: #334155;"></div>
      </div>
    </div>
  `;

  const cyContainer = document.getElementById(`${containerId}-cy`);
  const badgeEl = document.getElementById(`${containerId}-badge`);
  const emptyEl = document.getElementById(`${containerId}-empty`);
  const errorEl = document.getElementById(`${containerId}-error`);
  const fitBtn = document.getElementById(`${containerId}-fit`);
  const detailsEl = document.getElementById(`${containerId}-details`);
  const detailsTitle = document.getElementById(`${containerId}-details-title`);
  const detailsBody = document.getElementById(`${containerId}-details-body`);
  const detailsClose = document.getElementById(`${containerId}-details-close`);

  detailsClose.onclick = () => { detailsEl.style.display = 'none'; };

  function ensureCytoscape(callback) {
    if (window.cytoscape) {
      callback();
    } else {
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js';
      script.onload = callback;
      script.onerror = () => {
        errorEl.style.display = 'flex';
        errorEl.textContent = 'Failed to load Cytoscape library.';
      };
      document.head.appendChild(script);
    }
  }

  ensureCytoscape(() => {
    fetch(apiUrl)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        const isNeo4j = data.source === 'neo4j';
        badgeEl.textContent = isNeo4j ? 'Powered by Neo4j' : 'Live from database';
        badgeEl.style.background = isNeo4j ? '#dcfce7' : '#e0f2fe';
        badgeEl.style.color = isNeo4j ? '#166534' : '#0369a1';

        const nodes = data.nodes || [];
        const edges = data.edges || [];

        if (nodes.length === 0) {
          emptyEl.style.display = 'flex';
          return;
        }

        const elements = [
          ...nodes.map(n => ({
            data: {
              id: n.id,
              label: n.label || n.id,
              type: n.type,
              ai: (n.props && n.props.ai_declaration) || '',
              props: n.props || {}
            }
          })),
          ...edges.map((e, idx) => ({
            data: {
              id: `edge_${idx}`,
              source: e.source,
              target: e.target,
              label: e.type || ''
            }
          }))
        ];

        const cy = cytoscape({
          container: cyContainer,
          elements: elements,
          style: [
            {
              selector: 'node',
              style: {
                'label': 'data(label)',
                'font-size': '10px',
                'text-valign': 'bottom',
                'text-margin-y': '4px',
                'background-color': ele => NODE_COLORS[ele.data('type')] || NODE_COLORS.Node,
                'width': 28,
                'height': 28,
                'color': '#1e293b',
                'border-width': ele => ele.data('type') === 'Contribution' ? 3 : 1,
                'border-color': ele => {
                  if (ele.data('type') === 'Contribution') {
                    return AI_BORDER_COLORS[ele.data('ai')] || '#10b981';
                  }
                  return '#94a3b8';
                }
              }
            },
            {
              selector: 'edge',
              style: {
                'width': 1.5,
                'line-color': '#cbd5e1',
                'target-arrow-color': '#94a3b8',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'arrow-scale': 0.8
              }
            },
            {
              selector: 'edge:hover',
              style: {
                'label': 'data(label)',
                'font-size': '8px',
                'line-color': '#64748b',
                'target-arrow-color': '#64748b',
                'width': 2
              }
            }
          ],
          layout: {
            name: 'cose',
            animate: false,
            fit: true,
            padding: 30
          }
        });

        fitBtn.onclick = () => { cy.fit(undefined, 30); };

        cy.on('tap', 'node', evt => {
          const node = evt.target;
          detailsTitle.textContent = `${node.data('type')}: ${node.data('label')}`;
          let html = `<p><strong>ID:</strong> ${node.data('id')}</p>`;
          const props = node.data('props') || {};
          for (const [k, v] of Object.entries(props)) {
            html += `<p style="margin: 4px 0;"><strong>${k}:</strong> ${v}</p>`;
          }
          detailsBody.innerHTML = html;
          detailsEl.style.display = 'block';
        });

      })
      .catch(err => {
        errorEl.style.display = 'flex';
        badgeEl.textContent = 'Error';
        badgeEl.style.background = '#fee2e2';
        badgeEl.style.color = '#991b1b';
      });
  });
}

// Auto-fill GRAPH_SLOT elements if present
document.addEventListener('DOMContentLoaded', () => {
  const slot = document.querySelector('[data-graph-slot]');
  if (slot) {
    const scope = slot.getAttribute('data-graph-scope') || 'platform';
    const id = slot.getAttribute('data-graph-id') || '0';
    initGraphViewer(slot.id, `/api/graph/${scope}/${id}`);
  }
});
