CanvasEngine.prototype._renderLinks = function() {
    let html = '';
    let handlesHtml = '';

    this.connections.forEach(connection => {
        const from = this.nodes.find(node => node.id === connection.from);
        const to = this.nodes.find(node => node.id === connection.to);
        if (!from || !to) return;
        const start = this._getPortPoint(from, 'out');
        const end = this._getPortPoint(to, 'in', connection.fieldId||'');
        const curve = this._curveMeta(start, end);
        const selected = connection.id === this.selectedConnectionId ? ' is-selected' : '';
        const running = to.runState === 'running' ? ' is-running-target' : '';
        html += `
            <g class="connection-group${selected}" data-connection-id="${connection.id}">
                <path class="connection-hit" data-connection-id="${connection.id}" d="${curve.path}" />
                <path class="connection-line${selected}${running}" data-connection-id="${connection.id}" d="${curve.path}" />
            </g>
        `;
        handlesHtml += `
            <button
                class="connection-handle${selected}"
                data-connection-id="${connection.id}"
                data-connection-action="delete"
                style="left:${curve.midpoint.x}px;top:${curve.midpoint.y}px"
                title="连线操作"
            >
                <span class="connection-handle-dot"></span>
            </button>
        `;
    });

    if (this._linkFrom && this._tempPointer) {
        const from = this.nodes.find(node => node.id === this._linkFrom.nodeId);
        if (from) {
            const anchor = this._getPortPoint(from, this._linkFrom.portType);
            const start = this._linkFrom.portType === 'out' ? anchor : this._tempPointer;
            const end = this._linkFrom.portType === 'out' ? this._tempPointer : anchor;
            const curve = this._curveMeta(start, end);
            html += `<path class="temp-line" d="${curve.path}" />`;
        }
    }

    this.linksEl.innerHTML = html;
    if (this.handlesEl) this.handlesEl.innerHTML = handlesHtml;
};

