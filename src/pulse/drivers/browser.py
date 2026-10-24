"""DOM-backed screen observation, guarded mouse input and text entry over local CDP."""
from __future__ import annotations

import hashlib
import base64
import json
import time
from typing import Any, Mapping

from .cdp import CdpTransport

# Text-like input types a caller may fill. Every other type is refused below.
FILLABLE_INPUT_TYPES = frozenset({
    "text", "email", "search", "tel", "url", "number",
    "date", "time", "datetime-local", "month", "week",
})
SENSITIVE_INPUT_TYPES = frozenset({"password", "file", "hidden"})
NON_FILLABLE_INPUT_TYPES = frozenset({"submit", "reset", "button", "image"})

# Codes returned by the page-side guard. The service turns each into a message.
FIELD_REJECTION_MESSAGES = {
    "no_field": "the mapped anchor is not a fillable field",
    "disabled": "the field is disabled",
    "readonly": "the field is read-only",
    "type_password": "password fields are not fillable",
    "type_file": "file fields are not fillable",
    "type_hidden": "hidden fields are not fillable",
    "type_checkbox": "checkbox fields are not fillable",
    "type_radio": "radio fields are not fillable",
    "not_fillable": "button-like inputs are not fillable and could submit the form",
    "unsupported": "the field type is not supported for text entry",
    "focus_refused": "the field refused focus",
    "focus_lost": "the field lost focus before the entry was confirmed",
    "fill_failed": "the browser did not confirm the text entry",
    "not_observed": "the field held the text, but no observation returned it",
    "mismatch": "the page changed the text as it accepted it",
}


def field_rejection(meta: Mapping[str, Any]) -> str | None:
    """Return a rejection code for a field inspection, or None when fillable."""
    tag = str(meta.get("tag", ""))
    kind = str(meta.get("type", "")).lower()
    if tag == "input" and kind in SENSITIVE_INPUT_TYPES:
        return f"type_{kind}"
    if tag == "input" and kind in {"checkbox", "radio"}:
        return f"type_{kind}"
    if tag == "input" and kind in NON_FILLABLE_INPUT_TYPES:
        return "not_fillable"
    if not meta.get("found"):
        # A named element that is not a field is a wrong target, not a missing one.
        return "no_field" if not tag else "not_fillable"
    if meta.get("disabled"):
        return "disabled"
    if meta.get("readonly"):
        return "readonly"
    if tag == "textarea" or meta.get("editable"):
        return None
    if tag == "input" and kind in FILLABLE_INPUT_TYPES:
        return None
    return "unsupported"

_OBSERVE = r"""(() => {
  const vw = innerWidth, vh = innerHeight;
  const counts = (window.__pulseCounts = window.__pulseCounts || Object.create(null));
  const selectors = 'button,a,input,select,textarea,h1,h2,h3,nav,main,aside,label[for],[role="heading"],[role="main"],[role="navigation"],[role="complementary"],[role="button"],[role="link"],[role="menuitem"],[role="tab"],[role="checkbox"],[role="radio"],[role="switch"],[role="textbox"],[contenteditable=""],[contenteditable="true"],[contenteditable="plaintext-only"],[tabindex]:not([tabindex="-1"])';
  const seen = new Set(), anchors = [], claimed = new Set(), allowHidden = new Set(), candidates = [];
  const useLabel = new Map();
  // A checkbox usually has a bare <label> beside it, and a styled one hides its
  // own box at opacity 0 while still owning the click. So the input takes its
  // label's text and the label is not mapped again on its own. TodoMVC hides its
  // per-item toggle this way. Keep such an input when its centre hit-tests to it.
  for (const el of document.querySelectorAll('input[type=checkbox],input[type=radio]')) {
    const near = el.nextElementSibling && el.nextElementSibling.tagName === 'LABEL'
      ? el.nextElementSibling
      : (el.previousElementSibling && el.previousElementSibling.tagName === 'LABEL'
         ? el.previousElementSibling : null);
    const lab = (el.labels && el.labels[0]) || near || null;
    if (lab) { claimed.add(lab); useLabel.set(el, lab); }
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    const hidden = r.width < 2 || r.height < 2 || s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0;
    if (!hidden) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= vw || cy >= vh) continue;
    const hit = document.elementFromPoint(cx, cy);
    if (hit === el || el.contains(hit)) allowHidden.add(el);
  }
  for (const el of document.querySelectorAll(selectors)) {
    if (seen.has(el) || claimed.has(el)) continue;
    candidates.push([el, useLabel.get(el) || null]);
  }
  for (const [el, lab] of candidates) {
    if (seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (!allowHidden.has(el) && (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw || s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0)) continue;
    if (allowHidden.has(el) && (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw)) continue;
    // A label is the click target for a control that its own styling may hide.
    // Reading the control's type keeps the label in the same role as the control.
    let tagged = el.tagName;
    if (tagged === 'LABEL') {
      const target = el.htmlFor ? document.getElementById(el.htmlFor) : el.querySelector('input,select,textarea');
      const kind = String((target && target.type) || '').toLowerCase();
      tagged = kind === 'checkbox' ? 'CHECKBOXLABEL' : kind === 'radio' ? 'RADIOLABEL' : 'BUTTONLABEL';
    }
    const role = el.getAttribute('role') || ({BUTTON:'button',A:'link',INPUT:el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : 'input',SELECT:'combobox',TEXTAREA:'textbox',H1:'heading',H2:'heading',H3:'heading',NAV:'navigation',MAIN:'main',ASIDE:'complementary',CHECKBOXLABEL:'checkbox',RADIOLABEL:'radio',BUTTONLABEL:'button'}[tagged] || 'control');
    const landmark = ['navigation','main','complementary'].includes(role);
    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || (landmark ? role : el.innerText || el.getAttribute('placeholder') || el.getAttribute('alt') || (lab ? lab.innerText : '')) || '').replace(/\s+/g,' ').trim().slice(0,160);
    if (!label && !['checkbox','radio','switch'].includes(role)) continue;
    const action = ['button','link','menuitem','tab','checkbox','radio','switch','input','combobox','textbox'].includes(role);
    // A label selects its control, so its state is the control's state.
    const control = el.tagName === 'LABEL'
      ? (el.htmlFor ? document.getElementById(el.htmlFor) : el.querySelector('input,select,textarea'))
      : el;
    const isOn = !!(control && (control.checked === true || control.getAttribute?.('aria-checked') === 'true'));
    // A control that marks itself chosen with a `selected` class or `aria-current`
    // changes no text and no bounds, so the state is the only evidence of the
    // click. The React App Lab component outline is set this way.
    const marked = (el.classList && el.classList.contains('selected'))
      || (el.getAttribute('aria-current') || 'false') !== 'false';
    const key = role + '\u0000' + (label || role);
    const n = (counts[key] = (counts[key] || 0) + 1);
    let hash1=2166136261, hash2=2246822519;
    for (const ch of new TextEncoder().encode(key + '\u0000' + n)) { hash1=Math.imul(hash1 ^ ch,16777619); hash2=Math.imul(hash2 ^ ch,3266489917); }
    const id='a-'+(hash1>>>0).toString(16).padStart(8,'0')+(hash2>>>0).toString(16).padStart(8,'0');
    anchors.push({id,role,label:label || role,bounds:{x:Math.max(0,r.left)/vw,y:Math.max(0,r.top)/vh,width:(Math.min(vw,r.right)-Math.max(0,r.left))/vw,height:(Math.min(vh,r.bottom)-Math.max(0,r.top))/vh},source:'dom',actionable:action,effect:action ? 'write' : 'read',selected:isOn || marked || el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-checked') === 'true' || el.checked === true || el.getAttribute('aria-pressed') === 'true'});
  }
  return {url:location.href,title:document.title,viewport:{width:vw,height:vh},
          scroll:{x:Math.round(scrollX),y:Math.round(scrollY)},anchors};
})()"""

_FIELD_SELECTOR = ('input,textarea,[contenteditable=""],[contenteditable="true"],'
                   '[contenteditable="plaintext-only"]')

_INSPECT_FIELD = r"""((x, y) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return {found: false};
  const field = el.closest ? el.closest('__SELECTOR__') : null;
  const node = field || el;
  const tag = (node.tagName || '').toLowerCase();
  return {found: !!field, tag, type: String(node.type || '').toLowerCase(),
          disabled: node.disabled === true, readonly: node.readOnly === true,
          editable: node.isContentEditable === true,
          multiline: tag === 'textarea' || node.isContentEditable === true};
})""".replace("__SELECTOR__", _FIELD_SELECTOR)

_FOCUS_FIELD = r"""((x, y) => {
  const el = document.elementFromPoint(x, y);
  const field = el && el.closest ? el.closest('__SELECTOR__') : null;
  if (!field) return false;
  field.focus();
  if (field.isContentEditable) {
    const range = document.createRange();
    range.selectNodeContents(field);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  } else if (typeof field.select === 'function') {
    field.select();
  }
  return document.activeElement === field;
})""".replace("__SELECTOR__", _FIELD_SELECTOR)

# Confirms the entry without handing the text back to the caller.
_CONFIRM_FIELD = r"""((expected) => {
  const el = document.activeElement;
  if (!el) return {found: false, filled: false};
  const current = el.isContentEditable ? (el.innerText || '') : String(el.value ?? '');
  if (current.length === expected) return {found: true, filled: true};
  const alive = typeof el.isConnected === 'function' ? el.isConnected : true;
  return {found: alive, filled: false, actual_length: current.length};
})"""

# Extends a confirmation with the name of the field that now holds focus, which
# is how an Enter that runs a page script is told apart from an Enter that
# lands nowhere. No value is read here.
_CONFIRM_NAMED = r"""((expected, tagName) => {
  const el = document.activeElement;
  if (!el) return {found: false, filled: false};
  const current = el.isContentEditable ? (el.innerText || '') : String(el.value ?? '');
  return {found: true, filled: current.length === expected,
          tag: String(el.tagName || '').toLowerCase(),
          matches: String(el.tagName || '').toLowerCase() === tagName};
})"""

# The focused element keeps its text, so the following observation returns it
# in an anchor label. Forgetting focus leaves the page as it was before the fill.
_BLUR_FIELD = """(() => {
  const el = document.activeElement;
  if (!el || typeof el.blur !== 'function') return true;
  el.blur();
  return document.activeElement === document.body || document.activeElement === null;
})()"""

_SCROLL_BY = """((dx, dy) => {
  const before = {x: window.scrollX, y: window.scrollY};
  window.scrollBy({left: dx, top: dy, behavior: 'instant'});
  const maxY = Math.max(0, document.documentElement.scrollHeight - innerHeight);
  const maxX = Math.max(0, document.documentElement.scrollWidth - innerWidth);
  return {before, after: {x: window.scrollX, y: window.scrollY}, max: {x: maxX, y: maxY}};
})"""

# Keys are an allowlist. Enter and Escape cover submission and dismissal on most
# forms, and neither needs a modifier. No printable key is sent this way.
KEY_NAMES = {
    "enter": ("Enter", 13, "\r"),
    "escape": ("Escape", 27, ""),
}


def _call(script: str, *args: Any) -> str:
    """Build one self-invoking expression. Arguments become JSON, not source text."""
    encoded = ", ".join(json.dumps(arg) for arg in args)
    return f"({script})({encoded})"


def redact(observation: Mapping[str, Any], secret: str) -> dict[str, Any]:
    """Strip a filled value from an observation before storage or return."""
    if not secret:
        return dict(observation)
    cleaned = dict(observation)
    anchors = []
    for anchor in observation.get("anchors", ()):
        item = dict(anchor)
        label = str(item.get("label", ""))
        if secret in label:
            item["label"] = " ".join(label.replace(secret, "[redacted]").split()) or "[redacted]"
        anchors.append(item)
    cleaned["anchors"] = anchors
    return cleaned


class BrowserDriver:
    def __init__(self, port: int = 9222, *, timeout: float = 5.0):
        self.cdp = CdpTransport(port, timeout=timeout)

    def evaluate(self, expression: str) -> Any:
        response = self.cdp.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        })
        if "exceptionDetails" in response:
            raise RuntimeError("browser evaluation failed")
        return response.get("result", {}).get("value")

    def observe(self, app_id: str, *, screenshot_digest: bool = True) -> dict[str, Any]:
        self.evaluate("window.__pulseCounts = Object.create(null)")
        raw = self.evaluate(_OBSERVE)
        if not isinstance(raw, dict):
            raise RuntimeError("browser did not return a document observation")
        # The digest supports comparing captures without persisting screenshot bytes.
        digest = None
        if screenshot_digest:
            shot = self.cdp.send("Page.captureScreenshot", {"format":"png","captureBeyondViewport":False})
            encoded = shot.get("data", "")
            digest = hashlib.sha256(base64.b64decode(encoded)).hexdigest() if encoded else None
        return {**raw, "app_id": app_id, "screenshot_sha256": digest, "observed_at": time.time()}

    def click(self, x: float, y: float) -> None:
        self.cdp.send("Input.dispatchMouseEvent", {"type":"mouseMoved","x":x,"y":y})
        self.cdp.send("Input.dispatchMouseEvent", {"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1})
        self.cdp.send("Input.dispatchMouseEvent", {"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1})

    def inspect_field(self, x: float, y: float) -> dict[str, Any]:
        """Describe the field at a viewport point without touching its value."""
        raw = self.evaluate(_call(_INSPECT_FIELD, x, y))
        if not isinstance(raw, dict):
            return {"found": False}
        # A single-line field drops a trailing newline, so the entry must too.
        # Reported here because multline-ness belongs to the page, not the caller.
        if raw.get("tag") in {"input", "textarea"} and not raw.get("multiline"):
            raw["type"] = str(raw.get("type") or "")
        return raw

    def entry_text(self, value: str) -> str:
        """Trim the text for a single-line field, as the page keeps only one line."""
        tag = str(getattr(self, "_last_field", {}).get("tag", ""))
        multiline = bool(getattr(self, "_last_field", {}).get("multiline")) or tag == "textarea"
        return value if multiline else value.strip("\r\n")

    def focus_field(self, x: float, y: float) -> bool:
        self._last_field = self.inspect_field(x, y)
        return self.evaluate(_call(_FOCUS_FIELD, x, y)) is True

    def entry_problem(self, value: str) -> str | None:
        """Read the focused value back and name a mismatch, without returning it."""
        raw = self.evaluate("(() => { const el = document.activeElement;"
                            " return el ? String(el.value ?? '') : null; })()")
        if not isinstance(raw, str):
            return "not_observed"
        if raw == value:
            return None
        return "mismatch" if len(raw) == len(value) else "fill_failed"

    def focused_tag(self) -> str:
        """Name the focused element's tag, so a lost focus can be told apart early."""
        raw = self.evaluate("(() => document.activeElement ? String(document.activeElement.tagName || '').toLowerCase() : '')()")
        return str(raw or "").lower()

    def insert_text(self, value: str) -> None:
        """Insert text into the focused element as a paste. No key events are sent."""
        self.cdp.send("Input.insertText", {"text": value})

    def confirm_entry(self, expected_length: int) -> dict[str, Any]:
        """Check the entry by length only, so the value never returns to the caller."""
        raw = self.evaluate(_call(_CONFIRM_FIELD, expected_length))
        if not isinstance(raw, dict):
            return {"found": False, "filled": False}
        return {"found": raw.get("found") is True, "filled": raw.get("filled") is True}

    def blur_field(self) -> None:
        """Remove focus so the field's text leaves the anchor labels of the next observation."""
        self.evaluate(_BLUR_FIELD)

    def press_key(self, name: str) -> None:
        """Send one allowlisted key at the currently focused element."""
        key, code, text = KEY_NAMES[name]
        common = {"key": key, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}
        raw = {"type": "rawKeyDown", **common}
        if text:
            raw["text"] = text
        self.cdp.send("Input.dispatchKeyEvent", raw)
        self.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **common})

    def scroll_by(self, dx: float, dy: float) -> dict[str, Any]:
        """Scroll the page viewport by pixel deltas and report the new offsets."""
        raw = self.evaluate(_call(_SCROLL_BY, dx, dy))
        if not isinstance(raw, dict):
            raise RuntimeError("browser did not report scroll offsets")
        return raw

    def close(self) -> None:
        self.cdp.close()
