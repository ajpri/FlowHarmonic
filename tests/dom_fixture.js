// Minimal test-only DOM used to execute the shipped vanilla JavaScript.
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.value = ''; this.textContent = ''; this.hidden = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  contains(element) { return this === element || this.children.some(child => child.contains(element)); }
  querySelectorAll(selector) {
    const selectors = selector.split(',').map(value => value.trim());
    return this.children.flatMap(child => [
      ...(selectors.some(value => value.startsWith('.') ? (child.className || '').split(' ').includes(value.slice(1)) : value === child.tag) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  async event(name) { await this.listeners[name]({preventDefault() {}}); }
}

module.exports = {Element};
