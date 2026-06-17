// <ui-icon> Web Component — SVG sprite icon via Shadow DOM
// Usage: <ui-icon name="sparkle" size="20"></ui-icon>
// Renders a <svg> referencing /static/img/sprite.svg with stroke="currentColor"
// The icon inherits color from parent element, auto-adapting to light/dark themes.

class UIIcon extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  static get observedAttributes() {
    return ['name', 'size'];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (oldVal !== newVal) this._render();
  }

  _render() {
    const name = this.getAttribute('name') || '';
    const size = parseInt(this.getAttribute('size')) || 18;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: ${size}px;
          height: ${size}px;
          flex-shrink: 0;
        }
        svg {
          width: 100%;
          height: 100%;
          display: block;
        }
      </style>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
           aria-hidden="true" role="img">
        <use href="/static/img/sprite.svg#${name}"></use>
      </svg>
    `;
  }
}

customElements.define('ui-icon', UIIcon);
