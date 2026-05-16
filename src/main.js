// The control-panel webview is set up with `transparent: true`, which on
// macOS 26 prevents the Tauri JS bridge (`window.__TAURI__`) from injecting
// reliably. So this script uses plain HTTP against the local API on
// 127.0.0.1:39213, exactly like the overlay does. No Tauri-specific code.
const API = "http://127.0.0.1:39213";

const dot = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const endpoint = document.getElementById("endpoint");
const posEl = document.getElementById("pos");
const btnPick = document.getElementById("btn-pick");
const btnCopy = document.getElementById("btn-copy");
const btnMin = document.getElementById("btn-min");
const btnClose = document.getElementById("btn-close");

endpoint.textContent = API;

async function refreshHealth() {
  try {
    const r = await fetch(API + "/health", { cache: "no-store" });
    if (r.ok) {
      const j = await r.json();
      dot.classList.remove("bad");
      dot.classList.add("ok");
      statusText.textContent = `online · v${j.version}`;
    } else throw new Error(r.statusText);
  } catch {
    dot.classList.remove("ok");
    dot.classList.add("bad");
    statusText.textContent = "offline";
  }
}

const compactPosEl = document.getElementById("compact-pos");
async function refreshCursor() {
  try {
    const r = await fetch(API + "/mouse/position", { cache: "no-store" });
    const j = await r.json();
    posEl.textContent = `(${j.x}, ${j.y})`;
    if (compactPosEl) compactPosEl.textContent = `${j.x}, ${j.y}`;
  } catch {
    posEl.textContent = "(?, ?)";
    if (compactPosEl) compactPosEl.textContent = "—, —";
  }
}

btnPick.addEventListener("click", async () => {
  btnPick.disabled = true;
  const original = btnPick.textContent;
  btnPick.textContent = "Move cursor, hold 1s…";
  try {
    await new Promise((r) => setTimeout(r, 1000));
    const r = await fetch(API + "/mouse/position", { cache: "no-store" });
    const j = await r.json();
    await fetch(API + "/mouse/click", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ x: j.x, y: j.y }),
    });
    btnPick.textContent = `Clicked (${j.x}, ${j.y})`;
  } catch (e) {
    btnPick.textContent = "Error";
    console.error(e);
  } finally {
    setTimeout(() => {
      btnPick.textContent = original;
      btnPick.disabled = false;
    }, 1200);
  }
});

// ---- OCR toggle ----
const btnOcr = document.getElementById("btn-ocr");
let ocrOn = false;
async function refreshOcr() {
  try {
    const r = await fetch(API + "/ocr/boxes", { cache: "no-store" });
    if (!r.ok) return;
    const j = await r.json();
    ocrOn = !!j.enabled;
    btnOcr.textContent = `OCR 标注 · ${ocrOn ? "ON" : "OFF"}`;
    btnOcr.style.background = ocrOn
      ? "linear-gradient(135deg, #ec4899, #f59e0b)"
      : "";
  } catch {}
}
btnOcr?.addEventListener("click", async () => {
  btnOcr.disabled = true;
  const original = btnOcr.textContent;
  btnOcr.textContent = "Running…";
  try {
    if (ocrOn) {
      // turn off + clear
      await fetch(API + "/ocr/clear", { method: "POST" });
    } else {
      // run OCR via spawned helper. We don't want to block the panel — fire-and-forget.
      await fetch(API + "/ocr/run", { method: "POST" }).catch(() => {
        // /ocr/run might not exist — fall back: just tell user to run the python helper
      });
    }
  } catch (e) {
    console.error(e);
  } finally {
    btnOcr.disabled = false;
    await refreshOcr();
  }
});
setInterval(refreshOcr, 1200);
refreshOcr();

btnCopy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(API);
    const t = btnCopy.textContent;
    btnCopy.textContent = "Copied!";
    setTimeout(() => (btnCopy.textContent = t), 900);
  } catch (e) {
    console.warn(e);
  }
});

// Minimise / close. Because the Tauri JS bridge is unreliable here, we ask
// the Rust side over HTTP — there's already a `quit_app` Tauri command, but
// without the bridge we can't call it directly. So we add a new HTTP endpoint
// for these window ops (see api.rs). Falls back to setting the body opacity
// if the endpoint isn't available yet.
// Sync CSS state to actual window dimensions so external resize (e.g.
// /_window/compact called by another process) still flips the layout.
// macOS WKWebView doesn't always fire `resize` for programmatic window
// resizes, so we poll as a fallback.
function applyCompact() {
  const compact = window.innerWidth < 230;
  document.body.classList.toggle("compact", compact);
}
window.addEventListener("resize", applyCompact);
setInterval(applyCompact, 150);
applyCompact();

btnMin.addEventListener("click", async () => {
  document.body.classList.add("compact");
  try {
    await fetch(API + "/_window/compact", { method: "POST" });
  } catch {}
});

// Expand on click in compact mode. Capture phase so it fires before any
// child element swallows the event.
document.addEventListener(
  "click",
  async (e) => {
    if (!document.body.classList.contains("compact")) return;
    if (e.target.closest("#btn-close")) return;
    e.preventDefault();
    e.stopPropagation();
    document.body.classList.remove("compact");
    try {
      await fetch(API + "/_window/expand", { method: "POST" });
    } catch {}
  },
  true,
);
btnClose.addEventListener("click", async () => {
  try {
    await fetch(API + "/_window/quit", { method: "POST" });
  } catch {
    window.close();
  }
});

refreshHealth();
refreshCursor();
setInterval(refreshHealth, 2000);
setInterval(refreshCursor, 250);
