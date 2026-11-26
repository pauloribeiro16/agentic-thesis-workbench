/* nav.js — Standalone navigation shell isolated from second-brain.
   Exposes window.plat (area, setSub, search, setBrand, setSearchItems).
   If second-brain's /nav.js already mounted #plat-bar, this script yields cleanly. */
(function () {
  "use strict";
  if (document.getElementById("plat-bar")) return;

  const AREAS = [
    ["thesis", "Thesis", "#overview"],
    ["literature", "Literature", "#literature"],
    ["agents", "Agents", "#agents"],
    ["config", "Config", "#config"],
  ];

  const HASH_AREA = {
    overview: "thesis",
    manuscript: "thesis",
    decisions: "thesis",
    quality: "thesis",
    literature: "literature",
    agents: "agents",
    config: "config",
  };

  function active() {
    const h = location.hash.replace(/^#\/?/, "").split("?")[0].split("/")[0];
    return HASH_AREA[h] || "thesis";
  }

  const color = (k) => `var(--a-${k}, var(--accent))`;
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[c]));

  const KEY = "atw.theme";
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch (_) {}

  const css = `
:root{--plat-h:48px;--plat-sub-h:0px;--plat-w:1200px}
:root.plat-has-sub{--plat-sub-h:42px}
#plat-bar,#plat-sub{box-sizing:border-box;font-family:var(--sans);-webkit-font-smoothing:antialiased}
#plat-bar{position:sticky;top:0;z-index:50;height:var(--plat-h);display:flex;align-items:center;gap:20px;
  padding:0 20px;background:var(--surface);border-bottom:1px solid var(--line);color:var(--fg)}
#plat-bar .pb-brand{display:flex;align-items:center;gap:9px;font:600 15px/1 var(--sans);letter-spacing:-.01em;white-space:nowrap;color:var(--fg);text-decoration:none}
#plat-bar .pb-mark{width:24px;height:24px;border-radius:7px;display:grid;place-items:center;background:var(--fg);color:var(--bg);font:600 14px/1 var(--serif)}
#plat-bar nav{display:flex;gap:2px;flex:1;min-width:0;overflow-x:auto;scrollbar-width:none}
#plat-bar nav::-webkit-scrollbar{display:none}
#plat-bar nav a{position:relative;padding:8px 12px;border-radius:8px;color:var(--muted);text-decoration:none;white-space:nowrap;font:500 14px/1 var(--sans)}
#plat-bar nav a:hover{color:var(--fg);background:var(--surface-2)}
#plat-bar nav a.on{color:var(--fg);background:var(--accent-soft)}
#plat-bar nav a.on::after{content:"";position:absolute;left:12px;right:12px;bottom:2px;height:2px;border-radius:2px;background:var(--pb-c)}
#plat-bar .pb-search{display:flex;align-items:center;gap:10px;background:var(--surface-2);border:1px solid var(--line);border-radius:8px;height:30px;padding:0 8px 0 10px;color:var(--faint);cursor:pointer;flex:none;font:400 13px/1 var(--sans)}
#plat-bar .pb-search:hover{color:var(--fg);border-color:var(--line-2)}
#plat-bar kbd,#plat-pal kbd{font:500 11px/1 var(--mono);color:var(--muted);background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:3px 5px}
#plat-bar .pb-theme{background:none;border:1px solid var(--line);border-radius:8px;width:32px;height:30px;color:var(--muted);cursor:pointer;flex:none}
#plat-bar .pb-theme:hover{color:var(--fg);border-color:var(--line-2)}
#plat-sub{position:sticky;top:var(--plat-h);z-index:49;height:var(--plat-sub-h);background:var(--bg);border-bottom:1px solid var(--line);display:none}
:root.plat-has-sub #plat-sub{display:block}
#plat-sub .in{max-width:var(--plat-w);height:100%;margin:0 auto;padding:0 20px;display:flex;align-items:stretch;gap:22px}
#plat-sub .tabs{display:flex;gap:22px;flex:1;min-width:0;overflow-x:auto;scrollbar-width:none}
#plat-sub .tabs::-webkit-scrollbar{display:none}
#plat-sub .tabs a{display:flex;align-items:center;gap:7px;border-bottom:2px solid transparent;color:var(--muted);text-decoration:none;font:500 14px/1 var(--sans);white-space:nowrap}
#plat-sub .tabs a:hover{color:var(--fg)}
#plat-sub .tabs a.on{color:var(--fg);border-color:var(--pb-c,var(--accent))}
#plat-sub .badge{font:600 11px/1 var(--sans);padding:3px 7px;border-radius:99px;background:var(--st-espera-soft);color:var(--st-espera)}
#plat-sub .right{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);white-space:nowrap}
#plat-pal{position:fixed;inset:0;z-index:100;display:flex;justify-content:center;align-items:flex-start;padding:12vh 16px 0;background:rgba(10,14,22,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);font-family:var(--sans);-webkit-font-smoothing:antialiased}
#plat-pal[hidden]{display:none}
#plat-pal .pp-box{box-sizing:border-box;width:min(640px,100%);max-height:72vh;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line-2);border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.35);overflow:hidden;color:var(--fg)}
#plat-pal input{box-sizing:border-box;width:100%;border:none;border-bottom:1px solid var(--line);background:none;color:var(--fg);font:400 17px/1.3 var(--sans);padding:16px 18px;outline:none}
#plat-pal input::placeholder{color:var(--faint)}
#plat-pal .pp-list{overflow-y:auto;padding:6px}
#plat-pal .pp-g{font:600 11px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;color:var(--faint);padding:10px 12px 6px}
#plat-pal .pp-i{display:flex;align-items:baseline;gap:10px;padding:8px 12px;border-radius:8px;color:var(--fg);text-decoration:none;font:400 14px/1.4 var(--sans);cursor:pointer}
#plat-pal .pp-i.sel{background:var(--accent-soft)}
#plat-pal .pp-i .pp-d{width:8px;height:8px;border-radius:50%;flex:none;align-self:center;background:var(--pb-c,var(--line-2))}
#plat-pal .pp-i .pp-t{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:none;max-width:60%}
#plat-pal .pp-i .pp-s{color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}
#plat-pal .pp-i .pp-r{color:var(--faint);font-size:12px;white-space:nowrap;flex:none;margin-left:auto}
#plat-pal .pp-foot{display:flex;gap:16px;padding:9px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--faint)}
#plat-pal .pp-foot kbd{margin-right:3px}
#plat-pal .pp-none{padding:22px 12px;color:var(--muted);font-size:14px;text-align:center}
@media (max-width:900px){#plat-bar .pb-search span{display:none}}
@media (max-width:640px){#plat-bar .pb-search kbd{display:none}#plat-bar .pb-search::before{content:"⌕";font-size:17px;color:var(--muted)}#plat-bar{gap:8px;padding:0 10px}#plat-bar .pb-brand span:last-child{display:none}#plat-bar nav a{padding:8px 9px}#plat-sub .in{padding:0 12px}#plat-sub .right{display:none}}`;

  const st = document.createElement("style");
  st.textContent = css;
  document.head.appendChild(st);

  const bar = document.createElement("div");
  bar.id = "plat-bar";
  bar.innerHTML =
    `<a class="pb-brand" href="#overview"><span class="pb-mark">§</span><span class="pb-title">agentic thesis workbench</span></a>` +
    `<nav aria-label="Areas">` +
    AREAS.map(([k, t, u]) => `<a data-a="${k}" href="${u}" style="--pb-c:${color(k)}">${t}</a>`).join("") +
    `</nav>` +
    `<button class="pb-search" type="button" title="Quick jump (⌘K or /)"><span>Search…</span><kbd>⌘K</kbd></button>` +
    `<button class="pb-theme" type="button" aria-label="Toggle theme" title="Toggle theme">◐</button>`;

  const sub = document.createElement("div");
  sub.id = "plat-sub";
  document.body.prepend(sub);
  document.body.prepend(bar);

  bar.querySelector(".pb-theme").onclick = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme
      ? r.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem(KEY, r.dataset.theme); } catch (_) {}
  };

  const pal = document.createElement("div");
  pal.id = "plat-pal";
  pal.hidden = true;
  pal.innerHTML =
    `<div class="pp-box" role="dialog" aria-label="Quick jump">` +
    `<input type="text" placeholder="Jump to chapters, citations, decisions, areas…" autocomplete="off" spellcheck="false" aria-label="Search">` +
    `<div class="pp-list"></div>` +
    `<div class="pp-foot"><span><kbd>↑</kbd><kbd>↓</kbd>select</span><span><kbd>↵</kbd>open</span><span><kbd>esc</kbd>close</span></div>` +
    `</div>`;
  document.body.appendChild(pal);

  const pIn = pal.querySelector("input");
  const pList = pal.querySelector(".pp-list");
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  let extraItems = [];
  let pItems = [];
  let pSel = 0;

  function pDraw() {
    const nq = norm(pIn.value.trim());
    const out = [];
    AREAS.filter(([, t]) => !nq || norm(t).includes(nq)).forEach(([k, t, u]) =>
      out.push({ g: "Areas", t, href: u, c: color(k) })
    );
    extraItems
      .filter((it) => !nq || norm(`${it.t} ${it.s || ""} ${it.r || ""}`).includes(nq))
      .slice(0, 14)
      .forEach((it) => out.push(it));

    pItems = out;
    if (pSel >= out.length) pSel = 0;
    let g = "";
    pList.innerHTML =
      out
        .map(
          (it, i) =>
            (it.g !== g ? `<div class="pp-g">${esc((g = it.g))}</div>` : "") +
            `<a class="pp-i${i === pSel ? " sel" : ""}" data-i="${i}" href="${esc(it.href)}"${it.c ? ` style="--pb-c:${it.c}"` : ""}>` +
            `${it.c ? '<span class="pp-d"></span>' : ""}` +
            `<span class="pp-t">${esc(it.t)}</span>` +
            `<span class="pp-s">${esc(it.s || "")}</span>` +
            `${it.r ? `<span class="pp-r">${esc(it.r)}</span>` : ""}` +
            `</a>`
        )
        .join("") || `<div class="pp-none">Nothing found.</div>`;
    const el = pList.querySelector(".sel");
    if (el) el.scrollIntoView({ block: "nearest" });
  }

  function pGo(i) {
    const it = pItems[i];
    if (!it) return;
    pClose();
    location.hash = it.href;
  }
  function pOpen() {
    pal.hidden = false;
    pIn.value = "";
    pSel = 0;
    pDraw();
    pIn.focus();
  }
  function pClose() { pal.hidden = true; }

  pIn.addEventListener("input", () => { pSel = 0; pDraw(); });
  pIn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = pItems.length || 1;
      pSel = (pSel + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
      pDraw();
    } else if (e.key === "Enter") {
      e.preventDefault();
      pGo(pSel);
    }
  });
  pList.addEventListener("click", (e) => {
    const a = e.target.closest(".pp-i");
    if (a) { e.preventDefault(); pGo(+a.dataset.i); }
  });
  pList.addEventListener("mousemove", (e) => {
    const a = e.target.closest(".pp-i");
    if (a && +a.dataset.i !== pSel) {
      pSel = +a.dataset.i;
      pList.querySelectorAll(".pp-i").forEach((x) => x.classList.toggle("sel", x === a));
    }
  });
  pal.addEventListener("mousedown", (e) => { if (e.target === pal) pClose(); });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      pal.hidden ? pOpen() : pClose();
      return;
    }
    if (e.key === "Escape" && !pal.hidden) { e.preventDefault(); pClose(); return; }
    const t = e.target;
    if (
      e.key === "/" &&
      pal.hidden &&
      !e.metaKey && !e.ctrlKey && !e.altKey &&
      !(t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))
    ) {
      e.preventDefault();
      pOpen();
    }
  });
  bar.querySelector(".pb-search").onclick = pOpen;

  window.plat = {
    standalone: true,
    area: active,
    search: pOpen,
    setBrand(label) {
      const el = bar.querySelector(".pb-title");
      if (el && label) el.textContent = label;
    },
    setSearchItems(items) {
      extraItems = Array.isArray(items) ? items : [];
    },
    setSub(items, on, right) {
      const has = items && items.length;
      document.documentElement.classList.toggle("plat-has-sub", !!has);
      if (!has) { sub.innerHTML = ""; return; }
      sub.innerHTML =
        `<div class="in" style="--pb-c:${color(active())}">` +
        `<div class="tabs">${items
          .map(
            (i) =>
              `<a href="${esc(i.href)}" class="${i.k === on ? "on" : ""}">${esc(i.label)}` +
              `${i.badge ? `<span class="badge">${esc(i.badge)}</span>` : ""}</a>`
          )
          .join("")}</div>` +
        (right ? `<div class="right">${right}</div>` : "") +
        `</div>`;
    },
  };

  function mark() {
    const a = active();
    bar.querySelectorAll("nav a").forEach((el) => el.classList.toggle("on", el.dataset.a === a));
  }
  mark();
  window.addEventListener("hashchange", mark);
})();
