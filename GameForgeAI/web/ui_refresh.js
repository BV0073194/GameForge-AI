/* Live-dashboard rendering utilities. No framework or external dependencies.
 * Never replace user-selected text or reset a locally edited form control.
 * Deferred data is applied by the next normal poll after interaction ends.
 */
(function (root) {
  'use strict';
  let rendered = new WeakMap();
  const dirtyFields = new Set();
  const settingIds = new Set();
  let editsBound = false;

  function hasSelectionInside(el) {
    if (!el || !root.document || typeof root.document.getSelection !== 'function') return false;
    const selection = root.document.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    try {
      return selection.getRangeAt(0).intersectsNode(el);
    } catch (_) {
      return Boolean(el.contains &&
        (el.contains(selection.anchorNode) || el.contains(selection.focusNode)));
    }
  }

  function hasFocusedEditorInside(el) {
    const active = root.document && root.document.activeElement;
    if (!el || !active || !el.contains || !el.contains(active)) return false;
    return Boolean(active.matches && active.matches('input, textarea, select, [contenteditable="true"]'));
  }

  function setText(el, next, options = {}) {
    if (!el) return false;
    const text = String(next == null ? '' : next);
    if (el.textContent === text) return false;
    if (!options.force && (hasSelectionInside(el) || hasFocusedEditorInside(el))) return false;
    el.textContent = text;
    return true;
  }

  function setHtml(el, next, options = {}) {
    if (!el) return false;
    const html = String(next == null ? '' : next);
    if (rendered.get(el) === html) return false;
    if (!options.force && (hasSelectionInside(el) || hasFocusedEditorInside(el))) return false;

    const openDetails = new Map();
    const scrolled = new Map();
    if (el.querySelectorAll) {
      el.querySelectorAll('details[data-preserve-key]').forEach(node => {
        openDetails.set(node.getAttribute('data-preserve-key'), node.open);
      });
      el.querySelectorAll('[data-preserve-scroll]').forEach(node => {
        scrolled.set(node.getAttribute('data-preserve-scroll'), {
          top: node.scrollTop, left: node.scrollLeft,
        });
      });
    }
    const top = el.scrollTop;
    const left = el.scrollLeft;
    el.innerHTML = html;
    if (el.querySelectorAll) {
      el.querySelectorAll('details[data-preserve-key]').forEach(node => {
        const key = node.getAttribute('data-preserve-key');
        if (openDetails.has(key)) node.open = openDetails.get(key);
      });
      el.querySelectorAll('[data-preserve-scroll]').forEach(node => {
        const position = scrolled.get(node.getAttribute('data-preserve-scroll'));
        if (position) {
          node.scrollTop = position.top;
          node.scrollLeft = position.left;
        }
      });
    }
    el.scrollTop = top;
    el.scrollLeft = left;
    rendered.set(el, html);
    return true;
  }

  function trackSettings(ids) {
    ids.forEach(id => settingIds.add(id));
    if (editsBound || !root.document) return;
    editsBound = true;
    const markDirty = event => {
      const target = event.target;
      if (target && settingIds.has(target.id)) dirtyFields.add(target.id);
    };
    // Capture changes before a refresh response can overwrite the user's choice.
    root.document.addEventListener('input', markDirty, true);
    root.document.addEventListener('change', markDirty, true);
  }

  function setField(el, next) {
    if (!el || dirtyFields.has(el.id) || (root.document && root.document.activeElement === el)) return false;
    if (el.type === 'checkbox') {
      const checked = Boolean(next);
      if (el.checked === checked) return false;
      el.checked = checked;
    } else {
      const value = String(next == null ? '' : next);
      if (el.value === value) return false;
      el.value = value;
    }
    return true;
  }

  // A save acknowledges only the value actually submitted, not edits typed
  // while the server request was in flight.
  function markSaved(values) {
    Object.entries(values || {}).forEach(([id, submitted]) => {
      const field = root.document && root.document.getElementById(id);
      if (!field) return;
      const current = field.type === 'checkbox' ? Boolean(field.checked) : field.value;
      if (current === submitted) dirtyFields.delete(id);
    });
  }

  function resetProject() {
    rendered = new WeakMap();
    dirtyFields.clear();
  }

  async function copyText(text) {
    const value = String(text == null ? '' : text);
    if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
      await root.navigator.clipboard.writeText(value);
      return;
    }
    // Older embedded browsers may lack Clipboard API even on localhost.
    const area = root.document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-10000px';
    root.document.body.appendChild(area);
    area.select();
    try {
      if (!root.document.execCommand('copy')) throw new Error('Clipboard access denied');
    } finally {
      area.remove();
    }
  }

  root.GameForgeUI = {
    setText, setHtml, setField, trackSettings, markSaved,
    resetProject, hasSelectionInside, copyText,
  };
})(window);
