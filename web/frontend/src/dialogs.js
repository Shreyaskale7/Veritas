// Gives every modal (the app's .modal-backdrop / .modal markup) real dialog behaviour without touching each page:
// role="dialog", aria-modal, a name from its title, focus moved in and trapped, Escape closes, focus returns to the opener.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
let counter = 0;
const openers = new WeakMap();

function enhance(backdrop) {
  const modal = backdrop.querySelector('.modal');
  if (!modal || modal.dataset.dialog) return;
  modal.dataset.dialog = '1';
  const title = modal.querySelector('.modal-title');
  if (title) { title.id = title.id || `dlg-title-${++counter}`; modal.setAttribute('aria-labelledby', title.id); }
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.querySelectorAll('.modal-header button').forEach(b => { if (!b.getAttribute('aria-label') && b.textContent.trim().length <= 2) b.setAttribute('aria-label', 'Close'); });
  openers.set(backdrop, document.activeElement);
  const first = modal.querySelector('input:not([type=hidden]), select, textarea') || modal.querySelector('.btn-primary') || modal.querySelector(FOCUSABLE);
  setTimeout(() => first && first.focus(), 0);
}

function onKey(e) {
  const backdrop = document.querySelector('.modal-backdrop:last-of-type') || [...document.querySelectorAll('.modal-backdrop')].pop();
  if (!backdrop) return;
  if (e.key === 'Escape') { e.stopPropagation(); backdrop.click(); return; }   // the backdrop's own handler closes the dialog
  if (e.key !== 'Tab') return;
  const items = [...backdrop.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null);
  if (!items.length) return;
  const firstEl = items[0], lastEl = items[items.length - 1];
  if (e.shiftKey && document.activeElement === firstEl) { e.preventDefault(); lastEl.focus(); }
  else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); firstEl.focus(); }
  else if (!backdrop.contains(document.activeElement)) { e.preventDefault(); firstEl.focus(); }
}

// Wide tables scroll sideways on small screens: make each one a focusable, named region so keyboard users can scroll it.
function enhanceScrollers(root = document) {
  root.querySelectorAll('.table-wrap, .chain-row').forEach(el => {
    if (el.dataset.scroller) return;
    el.dataset.scroller = '1';
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'region');
    const cap = el.querySelector('caption');
    const prev = el.previousElementSibling;
    el.setAttribute('aria-label', (cap && cap.textContent.trim()) || (prev && /section-title|page-title/.test(prev.className) && prev.textContent.trim()) || (el.matches('.chain-row') ? 'Revision chain' : 'Table'));
  });
}

export function installDialogEnhancer() {
  enhanceScrollers();
  const obs = new MutationObserver(muts => {
    enhanceScrollers();
    for (const m of muts) {
      m.addedNodes.forEach(n => { if (n.nodeType === 1) (n.matches?.('.modal-backdrop') ? [n] : [...(n.querySelectorAll?.('.modal-backdrop') || [])]).forEach(enhance); });
      m.removedNodes.forEach(n => {
        if (n.nodeType === 1 && n.matches?.('.modal-backdrop')) {
          const opener = openers.get(n);
          if (opener && document.contains(opener)) opener.focus();
        }
      });
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('keydown', onKey, true);
  return () => { obs.disconnect(); document.removeEventListener('keydown', onKey, true); };
}
