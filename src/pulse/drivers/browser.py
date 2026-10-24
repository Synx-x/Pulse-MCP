"""DOM-backed screen observation and guarded mouse input over local CDP."""
from __future__ import annotations

import hashlib
import base64
import time
from typing import Any

from .cdp import CdpTransport

_OBSERVE = r"""(() => {
  const vw = innerWidth, vh = innerHeight;
  const selectors = 'button,a,input,select,textarea,h1,h2,h3,nav,main,aside,[role="heading"],[role="main"],[role="navigation"],[role="complementary"],[role="button"],[role="link"],[role="menuitem"],[role="tab"],[role="checkbox"],[role="radio"],[role="switch"],[tabindex]:not([tabindex="-1"])';
  const seen = new Set(), anchors = [];
  for (const el of document.querySelectorAll(selectors)) {
    if (seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw || s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) continue;
    const role = el.getAttribute('role') || ({BUTTON:'button',A:'link',INPUT:el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : 'input',SELECT:'combobox',TEXTAREA:'textbox',H1:'heading',H2:'heading',H3:'heading',NAV:'navigation',MAIN:'main',ASIDE:'complementary'}[el.tagName] || 'control');
    const landmark = ['navigation','main','complementary'].includes(role);
    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || (landmark ? role : el.innerText || el.getAttribute('placeholder') || el.getAttribute('alt')) || '').replace(/\s+/g,' ').trim().slice(0,160);
    if (!label && !['checkbox','radio','switch'].includes(role)) continue;
    const action = ['button','link','menuitem','tab','checkbox','radio','switch','input','combobox','textbox'].includes(role);
    const key = role + '\u0000' + (label || role);
    const n = (window.__pulseCounts[key] = (window.__pulseCounts[key] || 0) + 1);
    let hash1=2166136261, hash2=2246822519;
    for (const ch of new TextEncoder().encode(key + '\u0000' + n)) { hash1=Math.imul(hash1 ^ ch,16777619); hash2=Math.imul(hash2 ^ ch,3266489917); }
    const id='a-'+(hash1>>>0).toString(16).padStart(8,'0')+(hash2>>>0).toString(16).padStart(8,'0');
    anchors.push({id,role,label:label || role,bounds:{x:Math.max(0,r.left)/vw,y:Math.max(0,r.top)/vh,width:(Math.min(vw,r.right)-Math.max(0,r.left))/vw,height:(Math.min(vh,r.bottom)-Math.max(0,r.top))/vh},source:'dom',actionable:action,effect:action ? 'write' : 'read',selected:el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-checked') === 'true'});
  }
  return {url:location.href,title:document.title,viewport:{width:vw,height:vh},anchors};
})()"""


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

    def close(self) -> None:
        self.cdp.close()
