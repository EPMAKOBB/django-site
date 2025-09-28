const SVG_NS = 'http://www.w3.org/2000/svg';

const gradientStops = [
  { offset: '0%', color: 'rgba(0,255,156,0.9)' },
  { offset: '100%', color: 'rgba(156,107,255,0.85)' },
];

function createGradient(svg, id) {
  const defs = svg.querySelector('defs') || document.createElementNS(SVG_NS, 'defs');
  const gradient = document.createElementNS(SVG_NS, 'linearGradient');
  gradient.setAttribute('id', id);
  gradient.setAttribute('gradientUnits', 'userSpaceOnUse');
  gradientStops.forEach(({ offset, color }) => {
    const stop = document.createElementNS(SVG_NS, 'stop');
    stop.setAttribute('offset', offset);
    stop.setAttribute('stop-color', color);
    gradient.appendChild(stop);
  });
  defs.appendChild(gradient);
  if (!defs.parentNode) {
    svg.appendChild(defs);
  }
  return gradient;
}

function updateGradientDirection(gradient, x1, y1, x2, y2) {
  gradient.setAttribute('x1', String(x1));
  gradient.setAttribute('y1', String(y1));
  gradient.setAttribute('x2', String(x2));
  gradient.setAttribute('y2', String(y2));
}

function initGraph(graphEl) {
  if (!graphEl || graphEl.dataset.graphReady === 'true') {
    return;
  }

  const svg = graphEl.querySelector('.course-graph__edges');
  const hiddenEdges = Array.from(graphEl.querySelectorAll('[data-edge]'));
  const nodeElements = Array.from(graphEl.querySelectorAll('[data-node]'));

  if (!svg || nodeElements.length === 0) {
    graphEl.dataset.graphReady = 'true';
    return;
  }

  svg.textContent = '';
  const uuid = (window.crypto && typeof window.crypto.randomUUID === 'function')
    ? window.crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  const baseGradientId = `course-graph-gradient-${graphEl.dataset.courseId || uuid}`;

  const nodeMap = new Map();
  nodeElements.forEach((node) => {
    nodeMap.set(node.dataset.nodeId, node);
  });

  const edgeGradients = new Map();
  const edgeElements = hiddenEdges.map((edgeData, index) => {
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('course-graph__edge-line');
    if (edgeData.dataset.locked === 'true') {
      line.classList.add('course-graph__edge-line--locked');
      line.removeAttribute('stroke');
    } else {
      const gradientId = `${baseGradientId}-${index}`;
      const gradient = createGradient(svg, gradientId);
      edgeGradients.set(line, gradient);
      line.setAttribute('stroke', `url(#${gradientId})`);
    }
    line.dataset.edgeId = edgeData.dataset.edgeId || '';
    line.dataset.src = edgeData.dataset.src || '';
    line.dataset.dst = edgeData.dataset.dst || '';
    line.dataset.locked = edgeData.dataset.locked || 'false';
    svg.appendChild(line);
    return line;
  });

  const nodesWrapper = graphEl.querySelector('.course-graph__nodes');

  const updateSizeFromNodes = () => {
    if (!nodesWrapper) return;
    const rect = graphEl.getBoundingClientRect();
    let maxBottom = 0;
    let maxRight = 0;
    nodeElements.forEach((node) => {
      const r = node.getBoundingClientRect();
      const bottom = r.bottom - rect.top; // relative to graph
      const right = r.right - rect.left;
      if (bottom > maxBottom) maxBottom = bottom;
      if (right > maxRight) maxRight = right;
    });
    // Add a small safety padding so shadows aren't clipped
    const extra = 24;
    if (maxBottom > 0) {
      nodesWrapper.style.minHeight = `${Math.ceil(maxBottom + extra)}px`;
    }
    // If width exceeds container, allow horizontal scroll instead of clipping
    if (maxRight > rect.width) {
      graphEl.style.overflowX = 'auto';
    }
  };

  const updateEdges = () => {
    updateSizeFromNodes();
    const rect = graphEl.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);

    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

    edgeElements.forEach((line) => {
      const srcNode = nodeMap.get(line.dataset.src);
      const dstNode = nodeMap.get(line.dataset.dst);
      if (!srcNode || !dstNode) {
        line.setAttribute('opacity', '0');
        return;
      }

      const srcRect = srcNode.getBoundingClientRect();
      const dstRect = dstNode.getBoundingClientRect();

      const x1 = srcRect.left + srcRect.width / 2 - rect.left;
      const y1 = srcRect.top + srcRect.height / 2 - rect.top;
      const x2 = dstRect.left + dstRect.width / 2 - rect.left;
      const y2 = dstRect.top + dstRect.height / 2 - rect.top;

      line.setAttribute('x1', String(x1));
      line.setAttribute('y1', String(y1));
      line.setAttribute('x2', String(x2));
      line.setAttribute('y2', String(y2));
      line.setAttribute('opacity', line.dataset.locked === 'true' ? '0.4' : '0.85');

      const gradient = edgeGradients.get(line);
      if (gradient && line.dataset.locked !== 'true') {
        updateGradientDirection(gradient, x1, y1, x2, y2);
      }
    });
  };

  const highlightConnected = (nodeId, active) => {
    edgeElements.forEach((line) => {
      if (line.dataset.locked === 'true') {
        return;
      }
      const connects = line.dataset.src === nodeId || line.dataset.dst === nodeId;
      if (connects) {
        line.classList.toggle('course-graph__edge-line--highlighted', active);
        const otherId = line.dataset.src === nodeId ? line.dataset.dst : line.dataset.src;
        const otherNode = nodeMap.get(otherId);
        if (otherNode) {
          otherNode.classList.toggle('course-graph__node--highlighted', active);
        }
      }
    });
  };

  const unlockNode = (node) => {
    if (!node || node.dataset.locked !== 'true') return;
    node.dataset.locked = 'false';
    node.classList.remove('course-graph__node--locked');
    node.classList.add('course-graph__node--active', 'course-graph__node--just-unlocked');
    node.disabled = false;
    node.addEventListener(
      'animationend',
      () => {
        node.classList.remove('course-graph__node--just-unlocked');
      },
      { once: true }
    );
    updateEdges();
  };

  nodeElements.forEach((node) => {
    const nodeId = node.dataset.nodeId;
    if (!nodeId) return;

    node.addEventListener('mouseenter', () => highlightConnected(nodeId, true));
    node.addEventListener('mouseleave', () => highlightConnected(nodeId, false));
    node.addEventListener('focus', () => highlightConnected(nodeId, true));
    node.addEventListener('blur', () => highlightConnected(nodeId, false));
    node.addEventListener('click', () => {
      if (node.dataset.locked === 'true') return;
      const url = node.dataset.url;
      if (url) {
        window.location.assign(url);
      }
    });
  });

  graphEl.addEventListener('courseGraph:unlock', (event) => {
    const detail = event.detail || {};
    if (!detail.nodeId) return;
    const node = nodeMap.get(String(detail.nodeId));
    if (node) {
      unlockNode(node);
    }
  });

  const resizeObserver = window.ResizeObserver
    ? new ResizeObserver(() => updateEdges())
    : null;

  if (resizeObserver) {
    resizeObserver.observe(graphEl);
  } else {
    window.addEventListener('resize', updateEdges);
  }

  requestAnimationFrame(updateEdges);

  graphEl.dataset.graphReady = 'true';
}

function initGraphs() {
  const graphs = document.querySelectorAll('[data-course-graph]');
  graphs.forEach((graph) => initGraph(graph));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initGraphs);
} else {
  initGraphs();
}

export { initGraphs };
