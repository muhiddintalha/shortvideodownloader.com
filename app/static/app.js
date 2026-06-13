"use strict";
/* Security notes:
   - No API data is ever set via innerHTML (textContent only) → XSS hygiene
   - Thumbnails are only shown if they start with https://
   - Live validation is debounced; server also enforces rate limits */

const input = document.getElementById("url-input");
const btn = document.getElementById("go-btn");
const statusEl = document.getElementById("status");
const preview = document.getElementById("preview");

let timer = null;
let lastValid = null;

function setStatus(kind, text) {
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.textContent = text;
  input.classList.remove("ok", "err");
  if (kind === "ok") input.classList.add("ok");
  if (kind === "err") input.classList.add("err");
}

function reset() {
  btn.disabled = true;
  lastValid = null;
  preview.classList.add("hidden");
  preview.textContent = "";
}

input.addEventListener("input", () => {
  clearTimeout(timer);
  reset();
  const value = input.value.trim();
  if (!value) { setStatus("", "Waiting for a link…"); return; }
  setStatus("checking", "Running security check…");
  timer = setTimeout(() => check(value), 350);
});

async function check(url) {
  try {
    const r = await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const d = await r.json();
    if (input.value.trim() !== url) return; // user changed input in the meantime
    if (d.valid) {
      lastValid = d;
      btn.disabled = false;
      setStatus("ok", "✓ " + d.message + " Press Download to continue.");
    } else {
      setStatus("err", d.message || "Link could not be verified.");
    }
  } catch {
    setStatus("err", "Could not reach server. Please try again.");
  }
}

btn.addEventListener("click", async () => {
  if (!lastValid) return;
  btn.disabled = true;
  setStatus("checking", "Fetching video info…");
  try {
    const r = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: lastValid.normalized_url }),
    });
    const d = await r.json();
    if (!r.ok || !d.valid) {
      setStatus("err", d.message || "Could not fetch video info.");
      btn.disabled = false;
      return;
    }
    renderPreview(d);
    setStatus("ok", "Video found. Choose a download format.");
  } catch {
    setStatus("err", "Could not reach server. Please try again.");
    btn.disabled = false;
  }
});

function renderPreview(d) {
  preview.textContent = "";

  if (typeof d.thumbnail === "string" && d.thumbnail.startsWith("https://")) {
    const img = document.createElement("img");
    img.src = d.thumbnail;
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    preview.appendChild(img);
  }

  const meta = document.createElement("div");
  meta.className = "meta";

  const title = document.createElement("h2");
  title.textContent = d.title || "Video";
  meta.appendChild(title);

  const sub = document.createElement("p");
  sub.textContent = [d.uploader, formatDuration(d.duration)]
    .filter(Boolean).join(" · ");
  meta.appendChild(sub);

  const formats = document.createElement("div");
  formats.className = "formats";
  (d.formats || []).forEach((f) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = f.label;
    b.addEventListener("click", () => startDownload(d.normalized_url, f.id));
    formats.appendChild(b);
  });
  meta.appendChild(formats);

  preview.appendChild(meta);
  preview.classList.remove("hidden");
}

function startDownload(url, formatId) {
  setStatus("checking",
    "Preparing download… This may take a few seconds depending on the video size.");
  // Uses the browser's own download manager: file arrives directly once ready,
  // no page navigation required.
  const a = document.createElement("a");
  a.href = "/api/download?u=" + encodeURIComponent(url) +
           "&f=" + encodeURIComponent(formatId);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => {
    setStatus("ok", "File is being prepared — it will appear in your browser's download list.");
  }, 1200);
}

function formatDuration(s) {
  if (!s) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

// UX touches: focus input on load, Enter = Download
input.focus();
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !btn.disabled) btn.click();
});
