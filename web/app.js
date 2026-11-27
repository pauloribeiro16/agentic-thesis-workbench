/* Agentic Thesis Workbench — single-page app (vanilla JS, no build).
   All API calls are relative ("api/...") so the app works at "/" and behind a host prefix like "/tese/".
   UI strings come from i18n/<locale>.json; data and code stay in English. */
(function () {
  "use strict";

  const S = {
    state: null, dict: {}, fallback: {}, chapter: {}, activeChapter: null, filter: "all",
    sel: null, queue: null, qi: 0, quality: null, qlOnly: true, qlChapter: null, agents: null,
    literature: null, litFilter: { status: "all", q: "" }, activeThread: null, view: "overview",
    etag: "", busy: false,
  };
  const THESIS_TABS = ["overview", "manuscript", "queue", "decisions", "quality"];
  const VIEWS = [...THESIS_TABS, "literature", "agents", "config"];
  const CLOSED = new Set(["resolved", "wontfix"]);

  // ---------- helpers ----------
  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const t = (k, vars) => {
    let s = S.dict[k] ?? S.fallback[k] ?? k;
    for (const [a, b] of Object.entries(vars || {})) s = s.replaceAll(`{${a}}`, b);
    return s;
  };
  const fmt = (n) => Number(n || 0).toLocaleString(S.state?.config?.ui?.locale === "pt" ? "pt-PT" : "en-GB");
  const norm = (s) => String(s || "").replace(/[*`|]/g, "").replace(/\s+/g, " ").trim();

  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(path, opts);
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  function toast(msg, ms) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), ms || 2800);
  }

  function pill(kind, label) { return `<span class="st" data-st="${esc(kind)}">${esc(label)}</span>`; }
  const COMMENT_ST = { open: "aberto", addressed: "espera", approved: "curso", applied: "espera", resolved: "fechado", wontfix: "aberto" };
  const Q_ST = { OPEN: "aberto", AGENT_CONSENSUS: "curso", AUTHOR_RESERVED: "espera", SINGLE_PROPOSAL: "espera", APPROVED: "fechado", AGENT_DEADLOCK: "bloqueado", REJECTED: "aberto" };
  const QL_ST = { ok: "fechado", warn: "espera", bad: "bloqueado", na: "aberto", error: "bloqueado" };
  const qPill = (st) => pill(Q_ST[st] || "aberto", t(`dec.state.${st}`));
  const cPill = (st) => pill(COMMENT_ST[st] || "aberto", t(`st.${st}`));
  const qlPill = (st) => pill(QL_ST[st] || "aberto", t(`ql.state.${st}`));
  const who = (name, slot) => `<span class="who who-${esc(slot || "0")}"><span class="dot"></span>${esc(name || "?")}</span>`;

  function modal(html, onMount) {
    closeModal();
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.innerHTML = `<div class="modal" role="dialog">${html}</div>`;
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) closeModal(); });
    document.body.appendChild(wrap);
    if (onMount) onMount(wrap.firstElementChild);
    const first = wrap.querySelector("textarea, input, select");
    if (first) first.focus();
  }
  function closeModal() { $$(".modal-wrap").forEach((m) => m.remove()); }

  // ---------- Markdown rendering (subset; text preserved so comment anchors can be found) ----------
  function inline(s) {
    return esc(s)
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
      .replace(/\[@([\w:.\-]+)\]/g, '<span class="cite-pill">@$1</span>')
      .replace(/\(([A-ZÀ-Ý][^()]*?(?:19|20)\d{2}[a-z]?[^()]*)\)/g, '(<span class="cite-pill">$1</span>)');
  }
  function renderMd(raw) {
    const lines = String(raw || "").replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, "")).split("\n");
    const out = [];
    let para = [], list = null, table = null, fence = null, fenceLang = "";
    const flushPara = () => { if (para.length) out.push(`<p>${inline(para.join(" "))}</p>`); para = []; };
    const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
    const flushTable = () => {
      if (table) out.push(`<table class="md-table">${table.map((r, i) => `<tr>${r.map((c) => i === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</table>`);
      table = null;
    };
    const flushAll = () => { flushPara(); flushList(); flushTable(); };
    for (const line of lines) {
      if (fence !== null) {
        if (line.trim().startsWith("```")) {
          out.push(fenceLang === "mermaid"
            ? `<figure class="mermaid-fig cmt-ui" data-src="${esc(fence.join("\n"))}"><pre>${esc(fence.join("\n"))}</pre></figure>`
            : `<pre>${esc(fence.join("\n"))}</pre>`);
          fence = null;
        } else fence.push(line);
        continue;
      }
      const s = line.trim();
      if (s.startsWith("```")) { flushAll(); fence = []; fenceLang = s.slice(3).trim().toLowerCase(); continue; }
      if (!s) { flushAll(); continue; }
      let m;
      if ((m = s.match(/^(#{1,6})\s+(.*)$/))) { flushAll(); const n = Math.min(m[1].length + 1, 5); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
      if (s.startsWith("|")) {
        flushPara(); flushList();
        if (/^\|[\s:|-]+\|$/.test(s)) continue;
        (table = table || []).push(s.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
        continue;
      }
      if ((m = s.match(/^([-*+]|\d+\.)\s+(.*)$/))) {
        flushPara(); flushTable();
        const tag = /\d/.test(m[1]) ? "ol" : "ul";
        if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
        list.items.push(m[2]);
        continue;
      }
      if ((m = s.match(/^!\[([^\]]*)\]\(([^)]+)\)/))) { flushAll(); out.push(`<p class="img-ph">[${esc(m[1] || "figure")}]</p>`); continue; }
      if (s.startsWith(">")) { flushAll(); out.push(`<blockquote>${inline(s.replace(/^>\s?/, ""))}</blockquote>`); continue; }
      if (list) { list.items[list.items.length - 1] += " " + s; continue; }
      flushTable();
      para.push(s);
    }
    if (fence !== null) out.push(`<pre>${esc(fence.join("\n"))}</pre>`);
    flushAll();
    return out.join("\n");
  }

  // ---------- Mermaid diagrams (vendored library, loaded only when a page has one) ----------
  let mermaidReady = null;
  function loadMermaid() {
    if (!mermaidReady) {
      mermaidReady = new Promise((resolve, reject) => {
        const sc = document.createElement("script");
        sc.src = "vendor/mermaid.min.js";
        sc.onload = () => resolve(window.mermaid);
        sc.onerror = () => reject(new Error("mermaid not available"));
        document.head.appendChild(sc);
      });
    }
    return mermaidReady;
  }

  async function renderMermaid(root) {
    const figs = $$(".mermaid-fig:not(.done)", root);
    if (!figs.length) return;
    let mermaid;
    try { mermaid = await loadMermaid(); } catch (_) { return; }
    const dark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral" });
    let i = 0;
    for (const fig of figs) {
      fig.classList.add("done");
      try {
        const { svg } = await mermaid.render(`mmd-${Date.now()}-${i++}`, fig.dataset.src);
        fig.innerHTML = svg;
        fig.title = "⤢";
        fig.onclick = () => modal(`<div class="mermaid-big">${svg}</div><div class="modal-actions"><button class="btn" id="m-cancel">${t("close")}</button></div>`,
          (m) => { $("#m-cancel", m).onclick = closeModal; });
      } catch (e) {
        fig.insertAdjacentHTML("beforeend", `<div class="sub bad">${esc(String(e.message || e).slice(0, 200))}</div>`);
      }
    }
  }

  // ---------- text mapping for highlights and selections ----------
  const BLOCK = "p,li,td,th,h1,h2,h3,h4,h5,h6,pre,blockquote";
  function textMap(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let text = "", map = [], prevBlock = null, node;
    while ((node = walker.nextNode())) {
      if (node.parentElement.closest(".cmt-ui")) continue;
      const block = node.parentElement.closest(BLOCK);
      if (prevBlock && block !== prevBlock && text && text[text.length - 1] !== " ") { text += " "; map.push(null); }
      prevBlock = block;
      const v = node.nodeValue;
      for (let i = 0; i < v.length; i++) {
        const ch = v[i];
        if (/\s/.test(ch)) {
          if (text && text[text.length - 1] !== " ") { text += " "; map.push([node, i]); }
        } else if (!"*`|".includes(ch)) { text += ch; map.push([node, i]); }
      }
    }
    return { text, map };
  }

  function highlight(root, plain, id, cls) {
    const q = norm(plain);
    if (!q) return false;
    const { text, map } = textMap(root);
    let at = text.indexOf(q);
    if (at < 0) at = text.indexOf(q.slice(0, Math.min(80, q.length)));
    if (at < 0) return false;
    const end = Math.min(at + q.length, map.length);
    const segs = new Map();
    for (let i = at; i < end; i++) {
      const m = map[i];
      if (!m) continue;
      const [node, off] = m;
      const seg = segs.get(node) || [off, off];
      seg[0] = Math.min(seg[0], off); seg[1] = Math.max(seg[1], off);
      segs.set(node, seg);
    }
    for (const [node, [a, b]] of segs) {
      const range = document.createRange();
      range.setStart(node, a); range.setEnd(node, b + 1);
      const mark = document.createElement("mark");
      mark.className = `cmt ${cls}`;
      mark.dataset.id = id;
      try { range.surroundContents(mark); } catch (_) {}
    }
    return true;
  }

  // Highlight many passages in one pass: one text map per section, then wrap from the end backwards so the
  // node offsets of earlier passages stay valid. Returns the set of ids that were found.
  function highlightMany(root, items) {
    const found = new Set();
    if (!items.length) return found;
    const { text, map } = textMap(root);
    const segs = [];
    for (const it of items) {
      const q = norm(it.plain);
      if (!q) continue;
      let at = text.indexOf(q);
      if (at < 0) at = text.indexOf(q.slice(0, Math.min(80, q.length)));
      if (at < 0) continue;
      found.add(it.id);
      const end = Math.min(at + q.length, map.length);
      const per = new Map();
      for (let i = at; i < end; i++) {
        const m = map[i];
        if (!m) continue;
        const seg = per.get(m[0]) || [m[1], m[1]];
        seg[0] = Math.min(seg[0], m[1]); seg[1] = Math.max(seg[1], m[1]);
        per.set(m[0], seg);
      }
      for (const [node, [a, b]] of per) segs.push({ node, a, b, id: it.id, cls: it.cls, order: at });
    }
    // later text first; within a node, larger offsets first
    const nodeIndex = new Map();
    map.forEach((m) => { if (m && !nodeIndex.has(m[0])) nodeIndex.set(m[0], nodeIndex.size); });
    segs.sort((x, y) => (nodeIndex.get(y.node) - nodeIndex.get(x.node)) || (y.a - x.a));
    const used = new Map();
    for (const sg of segs) {
      const u = used.get(sg.node) || [];
      if (u.some(([a, b]) => sg.a <= b && sg.b >= a)) continue;   // overlapping passages: keep the first wrapped
      u.push([sg.a, sg.b]); used.set(sg.node, u);
      const range = document.createRange();
      try {
        range.setStart(sg.node, sg.a); range.setEnd(sg.node, sg.b + 1);
        const mark = document.createElement("mark");
        mark.className = `cmt ${sg.cls}`;
        mark.dataset.id = sg.id;
        range.surroundContents(mark);
      } catch (_) {}
    }
    return found;
  }

  // ---------- navigation ----------
  function route() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, qs] = raw.split("?");
    const [view, param] = (path || "overview").split("/");
    return { view: VIEWS.includes(view) ? view : "overview", param: param || "", params: new URLSearchParams(qs || "") };
  }

  function syncSub(view) {
    if (!window.plat) return;
    if (!THESIS_TABS.includes(view)) { window.plat.setSub([]); return; }
    const st = S.state?.stats || {};
    const badges = { decisions: st.questions_waiting || 0, queue: st.comments_to_close || 0 };
    window.plat.setSub(THESIS_TABS.map((k) => ({ k, label: t(`tab.${k}`), href: "#" + k, badge: badges[k] || 0 })), view,
      `${fmt(st.total_words)} ${t("words")}`);
  }

  async function loadI18n(locale) {
    try { S.fallback = await (await fetch("i18n/en.json")).json(); } catch (_) {}
    if (locale && locale !== "en") {
      try { S.dict = await (await fetch(`i18n/${locale}.json`)).json(); } catch (_) { S.dict = {}; }
    } else S.dict = {};
    document.documentElement.lang = locale || "en";
    if (window.plat?.setAreaLabels) window.plat.setAreaLabels({ thesis: t("area.thesis"), literature: t("area.literature"), agents: t("area.agents"), config: t("area.config") });
  }

  async function refreshState() {
    const first = !S.state;
    S.state = await api("api/state");
    S.etag = S.state.etag;
    if (first) await loadI18n(S.state.config.ui.locale);
    if (window.plat?.setBrand) window.plat.setBrand(S.state.config.project.title);
    if (window.plat?.setSearchItems) {
      window.plat.setSearchItems([
        ...S.state.chapters.map((c) => ({ g: t("tab.manuscript"), t: `${t("ch")} ${c.number} — ${c.title}`, s: `${fmt(c.words)} ${t("words")}`, href: `#manuscript/${c.number}` })),
        ...S.state.threads.flatMap((th) => th.questions.map((q) => ({ g: t("tab.decisions"), t: `${q.id} — ${q.title}`, s: t(`dec.state.${q.state}`), r: th.file, href: `#decisions?thread=${encodeURIComponent(th.file)}` }))),
      ]);
    }
  }

  async function render() {
    closeModal();
    const { view, param, params } = route();
    S.view = view;
    $$(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
    syncSub(view);
    const sg = S.state.signing || {};
    let banner = $("#sign-banner");
    if (!banner) { banner = document.createElement("div"); banner.id = "sign-banner"; $("#app").prepend(banner); }
    banner.innerHTML = sg.enabled && !sg.key_exists && ["overview", "queue", "decisions", "manuscript"].includes(view)
      ? `<div class="card alert banner"><b>${t("sign.missing")}</b> ${t("sign.missing_h", { p: `<code class="mono">${esc(sg.key_path)}</code>` })}</div>` : "";
    const fn = { overview: renderOverview, manuscript: renderManuscript, queue: renderQueue, decisions: renderDecisions,
      quality: renderQuality, literature: renderLiterature, agents: renderAgents, config: renderConfig }[view];
    try { await fn(param, params); } catch (err) { $(`#view-${view}`).innerHTML = `<div class="card"><h2>${t("error")}</h2><p>${esc(err.message)}</p></div>`; }
  }

  // ---------- Overview ----------
  const num1 = (x) => (x == null ? "—" : Number(x).toLocaleString(S.state?.config?.ui?.locale === "pt" ? "pt-PT" : "en-GB", { maximumFractionDigits: 1 }));

  function budgetCells(c) {
    const b = c.budget || {};
    if (!b.target) return `<td class="mono">${fmt(c.words)}</td><td></td><td></td>`;
    const hi = b.target[1];
    if (!b.pdf_pages) return `<td class="muted">${t("pg.compile_first")}</td><td class="mono">${fmt(c.words)}</td><td></td>`;
    const est = b.estimate_now, pct = Math.min(100, Math.round((est / hi) * 100));
    const cls = est > hi ? "over" : est < b.target[0] ? "under" : "";
    return `<td class="mono"><b>${num1(est)}</b> / ${hi}<div class="sub">${t("pg.pdf_with", { n: b.pdf_pages })}${b.stale ? " · " + t("pg.stale") : ""}</div></td>
      <td class="mono">${fmt(c.words)}<div class="sub">${t("pg.fit", { n: fmt(b.words_fit) })}${b.draft ? " · " + t("pg.draft") : ""}</div></td>
      <td style="min-width:110px"><div class="bar ${cls}"><i style="width:${pct}%"></i></div></td>`;
  }

  function renderOverview() {
    const st = S.state, s = st.stats, el = $("#view-overview"), chg = s.changes || {};
    const waiting = st.threads.flatMap((th) => th.questions.filter((q) => q.needs_author).map((q) => ({ ...q, file: th.file })));
    el.innerHTML = `
      <div class="page-head"><div><h1>${esc(st.config.project.title)}</h1>
        <div class="sub">${esc(st.config.project.author)} · <span class="mono">${esc(st.config.format.adapter)}</span> · <span class="mono">${esc(st.config.citations.provider)}</span></div></div></div>
      <div class="stats">
        <a class="stat" href="#queue"><div class="k">${t("ov.to_close")}</div><div class="v">${fmt(s.comments_to_close)}</div><div class="h">${t("ov.to_close_h", { c: chg.pending || 0, r: chg.review || 0 })}</div></a>
        <a class="stat" href="#queue"><div class="k">${t("ov.to_register")}</div><div class="v">${fmt(chg.to_register || 0)}</div><div class="h">${t("ov.to_register_h", { a: chg.to_apply || 0 })}</div></a>
        <a class="stat" href="#decisions"><div class="k">${t("ov.waiting")}</div><div class="v">${fmt(s.questions_waiting)}</div><div class="h">${t("ov.questions_total", { n: s.questions_total })}</div></a>
        <a class="stat ${s.unauthorised_claims ? "alert" : ""}" href="#decisions"><div class="k">${t("ov.unauth")}</div><div class="v">${fmt(s.unauthorised_claims)}</div><div class="h">${t("ov.unauth_h")}</div></a>
        <a class="stat" href="#agents"><div class="k">${t("ov.tasks")}</div><div class="v">${fmt(s.tasks_open)}</div><div class="h">${t("ov.tasks_h")}</div></a>
      </div>
      <div class="grid-2 wide-left">
        <div class="card"><h2>${t("ov.chapters")}</h2><div class="sub" style="margin:-6px 0 10px">${t("pg.explain")}</div>
          ${st.chapters.length ? `<table class="table"><thead><tr><th>${t("ch")}</th><th>${t("title")}</th><th>${t("pg.pages")}</th><th>${t("words")}</th><th></th></tr></thead><tbody>
            ${st.chapters.map((c) => `<tr><td class="mono">${String(c.number).padStart(2, "0")}</td><td><a href="#manuscript/${c.number}">${esc(c.title)}</a></td>${budgetCells(c)}</tr>`).join("")}
          </tbody></table>` : `<div class="empty">${t("ov.no_chapters")} <code class="mono">${esc(st.config.format.chapters_glob)}</code></div>`}
        </div>
        <div class="card"><h2>${t("ov.waiting_author")}</h2>
          ${waiting.length ? `<table class="table"><tbody>${waiting.slice(0, 12).map((q) => `<tr><td class="mono">${esc(q.id)}</td>
            <td><a href="#decisions?thread=${encodeURIComponent(q.file)}">${esc(q.title)}</a><div class="sub">${esc(q.file)}</div></td><td>${qPill(q.state)}</td></tr>`).join("")}</tbody></table>`
            : `<div class="empty">${t("ov.none_waiting")}</div>`}
        </div>
      </div>`;
  }

  // ---------- Manuscript ----------
  async function loadChapter(n, force) {
    if (force || !S.chapter[n]) S.chapter[n] = await api(`api/chapter/${n}`);
    return S.chapter[n];
  }

  const OPEN_CHANGE = (it) => !it.registered && (it.verdict === "pending" || it.verdict === "review" || (it.verdict === "approved" && it.status === "approved"));
  const CHG_ST = { pending: "espera", review: "bloqueado", approved: "fechado", rejected: "aberto" };
  const chPill = (it) => pill(CHG_ST[it.verdict] || "aberto", t(`chg.${it.verdict === "approved" && it.status === "approved" ? "to_apply" : it.verdict}`));

  function budgetLine(b) {
    if (!b || !b.target) return "";
    if (!b.pdf_pages) return ` · ${t("pg.compile_first")}`;
    return ` · <b>≈ ${num1(b.estimate_now)} / ${b.target[1]}</b> ${t("pg.sans")} · ${t("pg.pdf_with", { n: b.pdf_pages })} · ${t("pg.fit", { n: fmt(b.words_fit) })}`;
  }

  async function renderManuscript(param) {
    const el = $("#view-manuscript");
    const chapters = S.state.chapters;
    if (!chapters.length) { el.innerHTML = `<div class="card"><div class="empty">${t("ov.no_chapters")}</div></div>`; return; }
    const n = Number(param) || S.activeChapter || chapters[0].number;
    S.activeChapter = n;
    const scroll = window.scrollY;
    const ch = await loadChapter(n);
    const comments = ch.comments || [], changes = (ch.changes || []).filter((i) => !i.parent);
    const showClosed = S.filter !== "active";
    const shownC = comments.filter((c) => showClosed || !CLOSED.has(c.status));
    const shownX = changes.filter((i) => showClosed || OPEN_CHANGE(i));
    const pdfMode = S.msMode === "pdf";
    const plan = (S.state.config.plan?.chapters || {})[String(n)] || {};
    const openC = comments.filter((c) => !CLOSED.has(c.status)).length, openX = changes.filter(OPEN_CHANGE).length;
    const head = `
      <div class="page-head"><div><h1>${esc(t("ms.title", { n: ch.number, t: ch.title }))}</h1>
        <div class="sub">${fmt(ch.words)} ${t("words")}${budgetLine(ch.budget)}</div>
        ${plan.narrative ? `<details class="narrative"><summary>${t("ms.narrative")}${plan.part ? ` · ${esc(plan.part)}` : ""}</summary><p>${esc(plan.narrative)}</p>
          <div class="sub">${t("ms.narrative_src", { f: esc(S.state.config.plan.file) })}</div></details>` : ""}</div>
        <div class="toolbar">
          <select id="ms-ch">${chapters.map((c) => `<option value="${c.number}"${c.number === n ? " selected" : ""}>${t("ch")} ${c.number} — ${esc(c.title)}</option>`).join("")}</select>
          <div class="seg big">${["text", "pdf", "context"].map((m) => `<button class="${(S.msMode || "text") === m ? "on" : ""}" data-mode="${m}">${t("ms.mode_" + m)}</button>`).join("")}</div>
          <div class="seg big"><button class="${showClosed ? "" : "on"}" data-f="active">${t("ms.filter_active")}</button><button class="${showClosed ? "on" : ""}" data-f="all">${t("ms.filter_all")}</button></div>
          <details class="menu"><summary class="btn">${t("ms.agents_menu")} ▾</summary><div class="menu-list">
            <button class="btn" data-task="close-comments">${t("ms.ask_agents")}</button>
            <button class="btn" data-task="apply-approved">${t("ms.apply_approved")}</button>
            <button class="btn" data-task="chapter-review">${t("ms.full_review")}</button></div></details>
        </div></div>
      <div class="ms-counts sub">${t("ms.counts", { c: openC, x: openX, tc: comments.length, tx: changes.length })} · ${t("ms.select_hint")}</div>`;

    if (S.msMode === "context") {
      el.innerHTML = head + `<div class="card ctx-card" id="ctx-card"><div class="empty">${t("loading")}</div></div>`;
      renderContext(el, n);
    } else if (pdfMode) {
      el.innerHTML = head + `<div class="ms-grid">${pdfPanel(ch)}
        <aside class="ms-side"><div class="card sticky"><div class="sub" style="margin-bottom:8px">${t("ms.pdf_comments_hint")}</div>
          ${[...shownC.map(commentCard), ...shownX.map(changeCard)].join("") || `<div class="empty">${t("ms.no_comments")}</div>`}</div></aside></div>`;
      bindPdf(el, ch);
    } else {
      el.innerHTML = head + `
        <div class="ms-flow" id="ms-flow">
          <article class="card prose" id="ms-text">
            ${ch.sections.map((s) => `<section class="ms-sec" data-file="${esc(s.path)}"><div class="ms-file mono">${esc(s.path)} · ${fmt(s.words)} ${t("words")}</div>${renderMd(s.content)}</section>`).join("")}
          </article>
          <aside class="ms-margin" id="ms-margin"></aside>
        </div>
        <div class="sel-pop cmt-ui" id="sel-bar" hidden><button class="btn primary" data-act="new-comment">${t("ms.comment")} <kbd>C</kbd></button><button class="btn" data-act="new-suggest">${t("ms.suggest")} <kbd>S</kbd></button></div>`;
      const notes = [], bySec = new Map();
      const want = (file, item) => { if (!bySec.has(file)) bySec.set(file, []); bySec.get(file).push(item); };
      for (const it of shownX) {
        const meta = { who: it.id, snip: it.desc || it.new || it.old || "", cls: `v-${it.verdict}` };
        const n0 = { id: it.id, html: changeCard(it), closed: !OPEN_CHANGE(it), ...meta };
        notes.push(n0);
        if (it.anchor?.state === "exact" && it.anchor.plain) want(it.file, { id: it.id, plain: it.anchor.plain, cls: `chg v-${it.verdict}${n0.closed ? " closed" : ""}` });
      }
      for (const c of shownC) {
        const closed = CLOSED.has(c.status);
        notes.push({ id: c.id, html: commentCard(c), closed, who: (c.author || "").split(" ")[0], snip: c.text || c.quote || "", cls: `k-${c.kind || "note"}` });
        if (c.anchor && c.anchor.state !== "orphan") want(c.file, { id: c.id, plain: c.anchor.plain, cls: `k-${c.kind || "note"} s-${c.status}${closed ? " closed" : ""}` });
      }
      const found = new Set();
      for (const [file, items] of bySec) {
        const sec = $(`.ms-sec[data-file="${CSS.escape(file)}"]`, el);
        if (sec) highlightMany(sec, items).forEach((id) => found.add(id));
      }
      notes.forEach((x) => { x.orphan = !found.has(x.id); });
      S.msNotes = notes;
      layoutMargin(el);
      renderMermaid(el).then(() => { if (S.view === "manuscript" && S.msNotes === notes) layoutMargin(el); });
      $("#ms-text").addEventListener("mouseup", (e) => setTimeout(() => captureSelection(e), 0));
      $$("mark.cmt", el).forEach((m) => (m.onclick = (e) => { e.stopPropagation(); openNote(m.dataset.id, true); }));
    }
    window.scrollTo(0, scroll);
    $("#ms-ch").onchange = (e) => { location.hash = `#manuscript/${e.target.value}`; };
    $$("[data-f]", el).forEach((b) => (b.onclick = () => { S.filter = b.dataset.f; renderManuscript(String(n)); }));
    $$("[data-mode]", el).forEach((b) => (b.onclick = () => { S.msMode = b.dataset.mode; renderManuscript(String(n)); }));
    $$("[data-task]", el).forEach((b) => (b.onclick = () => createTask({ workflow: b.dataset.task, chapter: n })));
    const nc = $('[data-act="new-comment"]', el), ns = $('[data-act="new-suggest"]', el);
    if (nc) nc.onclick = () => openComposer("comment");
    if (ns) ns.onclick = () => openComposer("suggest");
    bindCommentActions(el, n);
    bindChangeActions(el);
  }

  // Margin notes: one quiet line per note next to the text it refers to (click to open the full card).
  // On narrow screens, a small marker under each paragraph opens that paragraph's notes.
  function noteHtml(x) {
    const open = S.openNotes.has(x.id);
    return `<div class="mnote ${open ? "open" : "collapsed"} ${x.closed ? "is-closed" : ""}" data-note="${esc(x.id)}">
      ${open ? x.html : `<div class="mline"><span class="mdot ${esc(x.cls)}"></span><b>${esc(x.who)}</b><span class="msnip">${esc(x.snip.slice(0, 140))}</span></div>`}</div>`;
  }

  function layoutMargin(el) {
    const flow = $("#ms-flow", el), margin = $("#ms-margin", el), text = $("#ms-text", el);
    if (!flow || !margin) return;
    S.openNotes = S.openNotes || new Set();
    S.openBlocks = S.openBlocks || new Set();
    $$(".inline-notes", el).forEach((x) => x.remove());
    const narrow = flow.clientWidth < 900;
    flow.classList.toggle("narrow", narrow);
    margin.innerHTML = "";
    const orphans = S.msNotes.filter((x) => x.orphan);
    const placed = S.msNotes.filter((x) => !x.orphan).map((x) => {
      const m = $(`mark.cmt[data-id="${CSS.escape(x.id)}"]`, text);
      return { ...x, mark: m, top: m ? m.getBoundingClientRect().top - flow.getBoundingClientRect().top : 0 };
    }).sort((a, b) => a.top - b.top);
    if (narrow) {
      const groups = new Map();
      for (const x of placed) {
        const block = x.mark?.closest("p,li,table,blockquote,h1,h2,h3,h4,h5,figure") || x.mark;
        if (!block) continue;
        if (!groups.has(block)) groups.set(block, []);
        groups.get(block).push(x);
      }
      let gi = 0;
      for (const [block, list] of groups) {
        const key = `${S.activeChapter}:${gi++}`;
        const open = S.openBlocks.has(key) || list.some((x) => S.openNotes.has(x.id));
        const nOpen = list.filter((x) => !x.closed).length;
        block.insertAdjacentHTML("afterend", `<div class="inline-notes cmt-ui ${open ? "open" : ""}" data-block="${key}">
          <button class="note-chip" data-chip="${key}">💬 ${nOpen}${list.length > nOpen ? ` <span class="muted">+${list.length - nOpen}</span>` : ""}</button>
          ${open ? `<div class="inline-list">${list.map(noteHtml).join("")}</div>` : ""}</div>`);
      }
      if (orphans.length) text.insertAdjacentHTML("afterbegin", `<div class="inline-notes cmt-ui open"><div class="k">${t("ms.orphans")}</div><div class="inline-list">${orphans.map(noteHtml).join("")}</div></div>`);
      $$("[data-chip]", el).forEach((b) => (b.onclick = () => {
        const k = b.dataset.chip;
        if (S.openBlocks.has(k)) S.openBlocks.delete(k); else S.openBlocks.add(k);
        layoutMargin(el);
      }));
    } else {
      margin.innerHTML = (orphans.length ? `<div class="m-orphans"><div class="k">${t("ms.orphans")}</div>${orphans.map(noteHtml).join("")}</div>` : "")
        + placed.map((x) => noteHtml(x).replace('class="mnote', `style="top:${Math.round(x.top)}px" class="placed mnote`)).join("");
      let bottom = orphans.length ? $(".m-orphans", margin).offsetHeight + 12 : 0;
      for (const node of $$(".mnote.placed", margin)) {
        const top = Math.max(parseFloat(node.style.top), bottom);
        node.style.top = `${top}px`;
        bottom = top + node.offsetHeight + 4;
      }
      margin.style.minHeight = `${Math.max(bottom, text.offsetHeight)}px`;
    }
    $$(".mnote", el).forEach((node) => {
      node.addEventListener("click", (e) => {
        if (e.target.closest("button, a, textarea, input, select")) return;
        openNote(node.dataset.note, !S.openNotes.has(node.dataset.note));
      });
      node.addEventListener("mouseenter", () => $$(`mark.cmt[data-id="${CSS.escape(node.dataset.note)}"]`, el).forEach((m) => m.classList.add("hot")));
      node.addEventListener("mouseleave", () => $$("mark.cmt.hot", el).forEach((m) => m.classList.remove("hot")));
    });
    bindCommentActions(el, S.activeChapter);
    bindChangeActions(el);
  }

  // ---------- Context: instructions, memories and constraints of the chapter ----------
  async function renderContext(el, n) {
    const box = $("#ctx-card", el);
    S.ctx = S.ctx || {};
    if (!S.ctx[n]) S.ctx[n] = await api(`api/context/${n}`);
    const docs = S.ctx[n].docs;
    if (!docs.length) { box.innerHTML = `<div class="empty">${t("ctx.none")}</div>`; return; }
    const pick = Math.min(S.ctxPick?.[n] ?? 0, docs.length - 1);
    const group = { plan: t("ctx.plan"), chapter: t("ctx.chapter"), memory: t("ctx.memory"), thesis: t("ctx.thesis") };
    let last = "";
    box.innerHTML = `<div class="ctx-grid"><nav class="ctx-nav">${docs.map((d, i) => {
      const g = d.kind !== last ? `<div class="k">${group[d.kind] || d.kind}</div>` : "";
      last = d.kind;
      return `${g}<button class="${i === pick ? "on" : ""}" data-doc="${i}">${esc(d.title)}</button>`;
    }).join("")}</nav>
      <div class="ctx-doc"><div class="sub mono">${esc(docs[pick].path || "")}</div><div class="prose small">${renderMd(docs[pick].content)}</div></div></div>`;
    $$("[data-doc]", box).forEach((b) => (b.onclick = () => { S.ctxPick = { ...(S.ctxPick || {}), [n]: Number(b.dataset.doc) }; renderContext(el, n); }));
    renderMermaid(box);
  }

  function openNote(id, open) {
    const el = $("#view-manuscript");
    S.openNotes = S.openNotes || new Set();
    if (open) S.openNotes.add(id); else S.openNotes.delete(id);
    layoutMargin(el);
    const node = $(`.mnote[data-note="${CSS.escape(id)}"]`, el);
    if (node && open) {
      node.classList.add("focus");
      const r = node.getBoundingClientRect();
      if (r.top < 80 || r.bottom > window.innerHeight) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function changeCard(it) {
    const v = it.verdict, inText = it.status === "applied";
    const acts = [];
    if (!it.registered) {
      if (v === "pending") acts.push(["approved", t("chg.approve"), "primary"], ["rejected", t("chg.reject")]);
      else if (it.status === "approved" && !it.sealed) acts.push(["approved", t("chg.reseal"), "primary"], ["pending", t("chg.undo")]);
      else if (v === "review") acts.push(["kept", t("chg.keep"), "primary"], ["contested", t("chg.contest")]);
      else if (inText) acts.push(["undo", t("chg.undo")]);
      else acts.push(["pending", t("chg.undo")]);
    }
    const lost = it.anchor?.state === "missing" ? `<span class="tag bad">${t("chg.lost")}</span>` : it.anchor?.state === "ambiguous" ? `<span class="tag">${t("chg.ambiguous")}</span>` : "";
    return `<div class="cmt-card chg-card v-${esc(v)}" id="card-${esc(it.id)}" data-id="${esc(it.id)}" data-applied="${inText ? 1 : 0}">
      <div class="cmt-head"><span class="tag mono">${esc(it.id)}</span>${chPill(it)}${lost}${it.q ? `<span class="tag">${esc(it.q)}</span>` : ""}
        <span class="cmt-meta">${esc(it.topic_title || "")}</span></div>
      <div class="cmt-snip">${esc((it.desc || it.new || it.old || "").slice(0, 110))}</div>
      ${it.desc ? `<div class="cmt-text">${esc(it.desc)}</div>` : ""}
      <div class="cmt-prop">${diffHtml(it.old, it.new)}</div>
      <div class="sub">${inText ? t("chg.in_text", { d: esc(it.applied || "") }) : ""}${it.by ? " · " + esc(it.by) : ""}${it.task ? " · " + esc(it.task) : ""}${it.registered ? " · " + t("chg.registered", { d: esc(it.registered) }) : ""}${it.status === "approved" ? " · " + (it.sealed ? t("dec.sealed") : t("dec.unsealed")) : ""}</div>
      <div class="cmt-actions">${acts.map(([k, l, cls]) => `<button class="btn sm ${cls || ""}" data-chg="${k}">${esc(l)}</button>`).join("")}</div>
    </div>`;
  }

  async function changeAction(id, decision, applied) {
    const action = applied && ["kept", "contested", "undo"].includes(decision) ? "review" : "decide";
    return api("api/changes", { action, ids: [id], decision });
  }

  function bindChangeActions(root) {
    $$("[data-chg]", root).forEach((b) => (b.onclick = async () => {
      const card = b.closest("[data-id]");
      try { await changeAction(card.dataset.id, b.dataset.chg, card.dataset.applied === "1"); await afterChange(); }
      catch (e) { toast(e.message); }
    }));
  }

  // ---------- PDF (read-only view; comments stay on the text) ----------
  function pdfPanel(ch) {
    const p = ch.pdf || {}, job = p.job || {}, b = p.build || {};
    const running = job.running;
    const when = p.mtime ? new Date(p.mtime * 1000).toLocaleString(S.state.config.ui.locale === "pt" ? "pt-PT" : "en-GB") : "";
    const src = b.source === "tex" ? `<span class="tag bad">${t("pdf.from_tex")}</span>` : b.source === "markdown" ? `<span class="tag">${t("pdf.from_md")}</span>` : "";
    const notes = [
      b.tex_file_in_sync === false ? t("pdf.tex_out_of_sync") : "",
      (b.undefined_citations || []).length ? t("pdf.undef", { n: b.undefined_citations.length, k: b.undefined_citations.slice(0, 5).join(", ") }) : "",
      job.ok === false && !running ? t("pdf.failed") : "",
    ].filter(Boolean);
    return `<div class="card pdf-card" id="pdf-card">
      <div class="pdf-bar">
        ${p.can_compile ? `<button class="btn primary" id="pdf-compile" ${running ? "disabled" : ""}>${running ? t("pdf.compiling") : t("pdf.compile")}</button>` : `<span class="sub">${t("pdf.no_command")}</span>`}
        <span class="sub">${p.exists ? t("pdf.last", { d: when }) : t("pdf.none")}</span>${src}
        ${ch.budget?.stale && p.exists ? `<span class="tag bad">${t("pg.stale")}</span>` : ""}
        ${p.exists ? `<a class="btn sm" href="api/pdf/${ch.number}?v=${p.mtime}" target="_blank" rel="noopener">${t("pdf.open")}</a>` : ""}
      </div>
      ${notes.length ? `<div class="sub bad">${notes.map(esc).join("<br>")}</div>` : ""}
      ${job.ok === false && job.log ? `<pre class="pre mono small">${esc(job.log.slice(-1500))}</pre>` : ""}
      ${p.exists ? `<iframe class="pdf-frame" src="api/pdf/${ch.number}?v=${p.mtime}#view=FitH" title="PDF"></iframe>` : `<div class="empty">${t("pdf.none_hint")}</div>`}
    </div>`;
  }

  function bindPdf(el, ch) {
    const btn = $("#pdf-compile", el);
    if (btn) btn.onclick = () => compileChapter(ch.number);
    if (ch.pdf?.job?.running) watchCompile(ch.number);
  }

  async function compileChapter(n) {
    try { await api("api/compile", { chapter: n }); S.chapter[n] = null; await renderManuscript(String(n)); watchCompile(n); }
    catch (e) { toast(e.message); }
  }

  async function watchCompile(n) {
    if (S.watching === n) return;
    S.watching = n;
    const t0 = Date.now();
    while (true) {
      await new Promise((r) => setTimeout(r, 1500));
      let info;
      try { info = await api(`api/compile?chapter=${n}`); } catch (_) { break; }
      const b = $("#pdf-compile");
      if (b) b.textContent = `${t("pdf.compiling")} ${Math.round((Date.now() - t0) / 1000)} s`;
      if (!info.job?.running) {
        S.watching = null; S.chapter[n] = null;
        toast(info.job?.ok ? t("pdf.done") : t("pdf.failed"));
        await refreshState();
        if (S.view === "manuscript" && S.activeChapter === n) await renderManuscript(String(n));
        return;
      }
    }
    S.watching = null;
  }

  function commentCard(c) {
    const a = c.anchor || {};
    const p = c.proposal;
    const anchorNote = a.state === "orphan" ? `<span class="tag bad">${t("ms.orphan")}</span>` : a.state === "fuzzy" ? `<span class="tag">${t("ms.fuzzy")}</span>` : "";
    const actions = [];
    if (c.status === "addressed") actions.push(["accept", t("act.accept"), "primary"], ["reopen", t("act.reopen")]);
    if (c.status === "applied") actions.push(["confirm", t("act.confirm"), "primary"], ["reopen", t("act.reopen")]);
    if (c.status === "open") actions.push(["resolve", t("act.resolve")]);
    if (!CLOSED.has(c.status)) actions.push(["wontfix", t("act.wontfix")]);
    if (CLOSED.has(c.status)) actions.push(["reopen", t("act.reopen")]);
    actions.push(["reply", t("ms.reply")]);
    if (a.state === "orphan") actions.push(["reattach", t("ms.reattach")]);
    if (c.author === S.state.config.agents.moderator_name) actions.push(["delete", t("act.delete")]);
    return `<div class="cmt-card s-${esc(c.status)}" id="card-${esc(c.id)}" data-id="${esc(c.id)}">
      <div class="cmt-head"><span class="tag k-${esc(c.kind || "note")}">${t(`kind.${c.kind || "note"}`)}</span>${cPill(c.status)}${anchorNote}
        <span class="cmt-meta">${esc(c.author || "")} · ${esc((c.date || "").slice(0, 10))}</span></div>
      <div class="cmt-snip">${esc((c.text || c.quote || "").slice(0, 110))}</div>
      <blockquote class="cmt-quote">${esc((c.quote || "").slice(0, 220))}${(c.quote || "").length > 220 ? "…" : ""}</blockquote>
      ${c.text ? `<div class="cmt-text">${esc(c.text)}</div>` : ""}
      ${(c.replies || []).map((r) => `<div class="cmt-reply"><b>${esc(r.author)}</b> ${esc(r.text)}</div>`).join("")}
      ${p ? `<div class="cmt-prop">${diffHtml(p.quote, p.replacement)}${p.rationale && p.rationale !== c.text ? `<div class="sub">${esc(p.rationale)}</div>` : ""}<div class="sub">${esc(p.by || "")}${p.task ? " · " + esc(p.task) : ""}${p.approved_at ? " · " + (p.sealed ? t("dec.sealed") : t("dec.unsealed")) : ""}</div></div>` : ""}
      <div class="cmt-actions">${actions.map(([k, l, cls]) => `<button class="btn sm ${cls || ""}" data-cact="${k}">${esc(l)}</button>`).join("")}</div>
    </div>`;
  }

  function focusCard(id) {
    const card = $(`#card-${CSS.escape(id)}`);
    if (!card) return;
    $$(".cmt-card.focus").forEach((x) => x.classList.remove("focus"));
    card.classList.add("focus");
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function commentAction(ch, id, act) {
    const base = { ch, id };
    if (act === "accept") return api("api/comments", { ...base, action: "accept" });
    if (act === "confirm" || act === "resolve") return api("api/comments", { ...base, action: "status", status: "resolved" });
    if (act === "wontfix") return api("api/comments", { ...base, action: "status", status: "wontfix" });
    if (act === "delete") return api("api/comments", { ...base, action: "delete" });
    if (act === "reattach") {
      if (!S.sel) throw new Error(t("ms.need_selection"));
      return api("api/comments", { ...base, action: "reattach", file: S.sel.file, quote: S.sel.quote, prefix: S.sel.prefix });
    }
    if (act === "reopen" || act === "reply") {
      return new Promise((resolve, reject) => {
        modal(`<h2>${act === "reopen" ? t("act.reopen") : t("ms.reply")}</h2>
          <textarea class="input" id="m-text" rows="4" placeholder="${esc(act === "reopen" ? t("q.reopen_prompt") : "")}"></textarea>
          <div class="modal-actions"><button class="btn" id="m-cancel">${t("cancel")}</button><button class="btn primary" id="m-ok">${t("save")}</button></div>`, (m) => {
          $("#m-cancel", m).onclick = () => { closeModal(); resolve(null); };
          const ok = async () => {
            const text = $("#m-text", m).value.trim();
            try {
              const r = act === "reopen" ? await api("api/comments", { ...base, action: "status", status: "open", text })
                : await api("api/comments", { ...base, action: "reply", text });
              closeModal(); resolve(r);
            } catch (e) { reject(e); }
          };
          $("#m-ok", m).onclick = ok;
          $("#m-text", m).addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ok(); });
        });
      });
    }
  }

  function bindCommentActions(root, ch) {
    $$("[data-cact]", root).forEach((b) => (b.onclick = async () => {
      const card = b.closest("[data-id]");
      try {
        const r = await commentAction(card.dataset.ch ? Number(card.dataset.ch) : ch, card.dataset.id, b.dataset.cact);
        if (r === null) return;
        await afterChange();
      } catch (e) { toast(e.message); }
    }));
  }

  async function afterChange() {
    S.chapter = {};
    S.quality = null;
    S.queue = null;
    await refreshState();
    await render();
  }

  function captureSelection(ev) {
    const sel = window.getSelection();
    const bar = $("#sel-bar");
    if (!sel || sel.isCollapsed || !sel.rangeCount) { if (bar) bar.hidden = true; return; }
    const range = sel.getRangeAt(0);
    const sec = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer.closest(".ms-sec") : range.commonAncestorContainer.parentElement?.closest(".ms-sec");
    const quote = sel.toString().trim();
    if (!sec || !quote) { if (bar) bar.hidden = true; return; }
    const pre = document.createRange();
    pre.setStart(sec, 0);
    pre.setEnd(range.startContainer, range.startOffset);
    S.sel = { file: sec.dataset.file, quote, prefix: pre.toString().slice(-80) };
    if (bar) {
      const r = range.getBoundingClientRect();
      bar.style.top = `${window.scrollY + r.bottom + 6}px`;
      bar.style.left = `${Math.max(8, window.scrollX + r.left)}px`;
      bar.hidden = false;
    }
  }

  function openComposer(mode) {
    if (!S.sel) { toast(t("ms.need_selection")); return; }
    const sel = S.sel, ch = S.activeChapter;
    const kinds = ["fix", "question", "cite", "style", "note"];
    modal(`<h2>${mode === "suggest" ? t("ms.suggest") : t("ms.comment")}</h2>
      <blockquote class="cmt-quote">${esc(sel.quote.slice(0, 400))}</blockquote>
      ${mode === "suggest" ? `<label>${t("ms.replacement")}</label><textarea class="input" id="m-rep" rows="5">${esc(sel.quote)}</textarea>
        <label>${t("ms.rationale")}</label><textarea class="input" id="m-text" rows="2"></textarea>`
        : `<label>${t("ms.kind")}</label><div class="seg kinds">${kinds.map((k, i) => `<button type="button" data-k="${k}" class="${i === 0 ? "on" : ""}">${t(`kind.${k}`)}</button>`).join("")}</div>
        <label>${t("ms.text")}</label><textarea class="input" id="m-text" rows="4"></textarea>`}
      <div class="modal-actions"><span class="sub">⌘/Ctrl + Enter</span><button class="btn" id="m-cancel">${t("cancel")}</button><button class="btn primary" id="m-ok">${t("save")}</button></div>`, (m) => {
      let kind = "fix";
      $$("[data-k]", m).forEach((b) => (b.onclick = () => { kind = b.dataset.k; $$("[data-k]", m).forEach((x) => x.classList.toggle("on", x === b)); }));
      $("#m-cancel", m).onclick = closeModal;
      const ok = async () => {
        const body = { ch, action: "add", file: sel.file, quote: sel.quote, prefix: sel.prefix, text: $("#m-text", m).value.trim(),
          kind: mode === "suggest" ? "suggest" : kind };
        if (mode === "suggest") body.replacement = $("#m-rep", m).value;
        try { await api("api/comments", body); closeModal(); window.getSelection().removeAllRanges(); S.sel = null; await afterChange(); }
        catch (e) { toast(e.message); }
      };
      $("#m-ok", m).onclick = ok;
      m.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ok(); if (e.key === "Escape") closeModal(); });
      if (mode === "suggest") { const r = $("#m-rep", m); setTimeout(() => { r.focus(); r.select(); }, 0); }
    });
  }

  // ---------- word diff ----------
  function diffHtml(a, b) {
    const A = String(a || "").split(/(\s+)/), B = String(b || "").split(/(\s+)/);
    if (A.length * B.length > 250000) return `<div class="diff"><del>${esc(a)}</del> <ins>${esc(b)}</ins></div>`;
    const n = A.length, m = B.length, L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0, out = "";
    while (i < n && j < m) {
      if (A[i] === B[j]) { out += esc(A[i]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) { out += `<del>${esc(A[i])}</del>`; i++; }
      else { out += `<ins>${esc(B[j])}</ins>`; j++; }
    }
    while (i < n) out += `<del>${esc(A[i++])}</del>`;
    while (j < m) out += `<ins>${esc(B[j++])}</ins>`;
    return `<div class="diff">${out}</div>`;
  }

  // ---------- Queue ("To close") ----------
  // Grouped by chapter and section; the open item expands in place with the full surrounding text.
  function inContext(ctx, middle, cls) {
    if (!ctx) return `<div class="q-box">${esc(middle)}</div>`;
    const html = renderMd(`${ctx.pre}\u0001${middle || " "}\u0002${ctx.post}`)
      .replace(/\u0001/g, `<mark class="q-mark ${cls}">`).replace(/\u0002/g, "</mark>");
    return `<div class="q-ctx prose small">${html}</div>`;
  }

  function queueKey(it) { return `${it.chapter || 0}|${it.context?.section || it.file || ""}`; }

  async function renderQueue() {
    const el = $("#view-queue");
    if (!S.queue) S.queue = await api("api/queue");
    const items = S.queue.items, c = S.queue.counts, x = S.queue.changes || {};
    S.qi = Math.max(0, Math.min(S.qi, items.length - 1));
    const order = items.map((it, k) => ({ it, k })).sort((a, b) => (a.it.chapter || 99) - (b.it.chapter || 99) || queueKey(a.it).localeCompare(queueKey(b.it)) || a.k - b.k);
    S.qOrder = order.map((o) => o.k);
    let html = "", lastCh = null, lastSec = null;
    for (const { it, k } of order) {
      const ch = it.chapter || 0, sec = it.context?.section || it.file || "";
      if (ch !== lastCh) {
        const n = order.filter((o) => (o.it.chapter || 0) === ch).length;
        html += `<h2 class="q-ch">${ch ? `${t("ch")} ${ch} — ${esc((S.state.chapters.find((y) => y.number === ch) || {}).title || "")}` : "—"} <span class="muted">(${n})</span></h2>`;
        lastCh = ch; lastSec = null;
      }
      if (sec !== lastSec) { html += `<div class="q-sec mono">${esc(sec)}</div>`; lastSec = sec; }
      const open = k === S.qi;
      const pillHtml = it.source === "change" ? chPill(it) : cPill(it.status);
      const what = it.source === "change" ? (it.desc || it.old || "") : (it.text || it.quote || "");
      html += `<div class="q-row ${open ? "open" : ""}" id="q-${k}">
        <button class="q-item" data-k="${k}">${pillHtml}<span class="q-snip">${esc(what.slice(0, 140))}</span><span class="mono muted">${esc(it.id)}</span></button>
        ${open ? `<div class="q-detail">${queueFocus(it)}</div>` : ""}</div>`;
    }
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("q.title")}</h1><div class="sub">${t("q.sub")}</div></div>
        <div class="toolbar"><span class="sub">${t("q.counts", { o: c.open, a: (c.approved || 0) + (x.to_apply || 0) })}</span>
          ${x.to_register ? `<button class="btn" id="q-register">${t("q.register", { n: x.to_register })}</button>` : ""}</div></div>
      ${items.length ? `<div class="card q-list">${html}</div>` : `<div class="card"><div class="empty">${t("q.empty")}</div></div>`}`;
    $$(".q-item", el).forEach((b) => (b.onclick = () => {
      const k = Number(b.dataset.k);
      S.qi = S.qi === k && $(`#q-${k}.open`) ? -1 : k;
      renderQueue().then(() => scrollToItem());
    }));
    bindQueueButtons(el);
    const reg = $("#q-register", el);
    if (reg) reg.onclick = registerDecisions;
  }

  function scrollToItem() {
    const row = $(`#q-${S.qi}`);
    if (row) row.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function queueFocus(it) {
    if (it.source === "change") {
      const review = it.verdict === "review";
      return `<div class="q-head"><b>${review ? t("q.change_review") : t("q.change_pending")}</b>
          ${it.q ? `<span class="tag">${esc(it.q)}</span>` : ""}<span class="muted">${esc(it.topic_title || "")}</span>
          <a class="btn sm" href="#manuscript/${it.chapter || ""}">${t("q.see_in_ms")}</a></div>
        ${it.desc ? `<div class="cmt-text big">${esc(it.desc)}</div>` : ""}
        ${it.anchor?.state === "missing" ? `<div class="tag bad">${t("chg.lost")}</div>` : ""}
        <div class="q-cols"><div><div class="k">${t("q.before_full")}</div>${inContext(it.context, it.old, "del")}</div>
          <div><div class="k">${t("q.after_full")}</div>${inContext(it.context, it.new, "ins")}</div></div>
        <details class="q-diff"><summary class="k">${t("q.diff")}</summary>${diffHtml(it.old, it.new)}</details>
        <div class="sub">${esc(it.file)}${it.by ? " · " + esc(it.by) : ""}${it.applied ? " · " + t("chg.in_text", { d: esc(it.applied) }) : ""}</div>
        <div class="cmt-actions">
          <button class="btn primary" data-qact="accept">${review ? t("chg.keep") : t("chg.approve")} (A)</button>
          <button class="btn" data-qact="reopen">${review ? t("chg.contest") : t("chg.reject")} (R)</button></div>`;
    }
    const p = it.proposal || {};
    const before = p.quote || it.quote, after = p.replacement || "";
    return `<div class="q-head"><b>${it.status === "addressed" ? t("q.addressed") : t("q.applied")}</b>
        <a class="btn sm" href="#manuscript/${it.chapter}">${t("q.see_in_ms")}</a></div>
      ${it.text ? `<div class="cmt-text big">${esc(it.text)}</div>` : ""}
      ${(it.replies || []).map((r) => `<div class="cmt-reply"><b>${esc(r.author)}</b> ${esc(r.text)}</div>`).join("")}
      <div class="q-cols"><div><div class="k">${t("q.before_full")}</div>${inContext(it.status === "applied" ? null : it.context, before, "del")}</div>
        <div><div class="k">${t("q.after_full")}</div>${inContext(it.status === "applied" ? it.context : it.context, after, "ins")}</div></div>
      <details class="q-diff"><summary class="k">${t("q.diff")}</summary>${diffHtml(before, after)}</details>
      ${p.rationale ? `<p class="sub">${esc(p.rationale)}</p>` : ""}
      <div class="sub">${esc(it.file)}${p.by ? " · " + esc(p.by) : ""}${p.task ? " · " + esc(p.task) : ""}</div>
      <div class="cmt-actions">
        <button class="btn primary" data-qact="${it.status === "addressed" ? "accept" : "confirm"}">${it.status === "addressed" ? t("act.accept") : t("act.confirm")}</button>
        <button class="btn" data-qact="reopen">${t("act.reopen")}</button><button class="btn" data-qact="wontfix">${t("act.wontfix")}</button></div>`;
  }

  function queueStep(delta) {
    const ord = S.qOrder || [];
    const pos = ord.indexOf(S.qi);
    const next = ord[Math.max(0, Math.min(ord.length - 1, (pos < 0 ? 0 : pos + delta)))];
    if (next !== undefined) { S.qi = next; renderQueue().then(scrollToItem); }
  }

  async function queueAct(act) {
    const it = S.queue?.items?.[S.qi];
    if (!it) return;
    try {
      if (it.source === "change") {
        const review = it.verdict === "review";
        const yes = act === "accept" || act === "confirm";
        await changeAction(it.id, review ? (yes ? "kept" : "contested") : (yes ? "approved" : "rejected"), review);
      } else {
        const r = await commentAction(it.chapter, it.id, act);
        if (r === null) return;
      }
      // keep the reading position: the next item in the same order opens
      const ord = S.qOrder || [], pos = ord.indexOf(S.qi);
      const nextId = S.queue.items[ord[pos + 1]]?.id;
      S.queue = null;
      await refreshState();
      S.queue = await api("api/queue");
      S.qi = Math.max(0, S.queue.items.findIndex((x) => x.id === nextId));
      await renderQueue();
      scrollToItem();
      syncSub("queue");
    } catch (e) { toast(e.message); }
  }
  function bindQueueButtons(el) { $$("[data-qact]", el).forEach((b) => (b.onclick = () => queueAct(b.dataset.qact))); }

  async function registerDecisions() {
    try {
      const pv = await api("api/changes", { action: "register", preview: true });
      modal(`<h2>${t("q.register_title")}</h2><div class="sub">${t("q.register_sub")}</div>
        ${Object.entries(pv.preview).map(([th, txt]) => `<div class="k">${esc(th)}</div><pre class="pre mono small">${esc(txt)}</pre>`).join("")}
        <div class="modal-actions"><button class="btn" id="m-cancel">${t("cancel")}</button><button class="btn primary" id="m-ok">${t("q.register_ok")}</button></div>`, (m) => {
        $("#m-cancel", m).onclick = closeModal;
        $("#m-ok", m).onclick = async () => {
          try { await api("api/changes", { action: "register" }); closeModal(); toast(t("q.registered")); await afterChange(); }
          catch (e) { toast(e.message); }
        };
      });
    } catch (e) { toast(e.message); }
  }

  // ---------- Decisions ----------
  function renderDecisions(_, params) {
    const el = $("#view-decisions");
    const threads = S.state.threads;
    if (!threads.length) { el.innerHTML = `<div class="card"><div class="empty">${t("dec.none")} <code class="mono">${esc(S.state.config.agents.dialogue_dir)}</code></div></div>`; return; }
    if (params?.get("thread")) S.activeThread = params.get("thread");
    const th = threads.find((x) => x.file === S.activeThread) || threads.find((x) => x.questions.some((q) => q.needs_author)) || threads[0];
    S.activeThread = th.file;
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("dec.title")}</h1><div class="sub">${t("dec.sub")}</div></div>
        <div class="toolbar"><select id="th-sel">${threads.map((x) => {
          const w = x.questions.filter((q) => q.needs_author).length;
          return `<option value="${esc(x.file)}"${x.file === th.file ? " selected" : ""}>${esc(x.file)}${w ? ` (${w})` : ""}</option>`;
        }).join("")}</select></div></div>
      <div class="grid-2">
        <div class="card"><h2>${t("dec.questions")} (${th.questions.length})</h2>
          <table class="table"><tbody>${th.questions.map((q) => `<tr>
            <td class="mono">${esc(q.id)}</td>
            <td>${esc(q.title)}${q.summary ? `<div class="sub">${esc(q.summary)}</div>` : ""}
              ${q.verdicts.length ? `<div class="sub">${q.verdicts.map((v) => `${esc(v.agent)}: ${esc(v.verdict)}`).join(" · ")}</div>` : ""}
              ${q.unauthorized_claims.length ? `<div class="tag bad">${t("dec.claims", { n: q.unauthorized_claims.length })}</div>` : ""}</td>
            <td>${qPill(q.state)}${q.state === "APPROVED" ? `<div class="sub">${q.authenticated ? t("dec.sealed") : t("dec.unsealed")}</div>` : ""}</td>
            <td class="nowrap">${q.state !== "APPROVED" ? `<button class="btn sm primary" data-dec="APPROVED" data-q="${esc(q.id)}">${t("dec.approve")}</button>
              <button class="btn sm" data-dec="REJECTED" data-q="${esc(q.id)}">${t("dec.reject")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="card"><h2>${t("dec.turns")} (${th.turns.length})</h2>
          ${th.turns.slice().reverse().map((x) => `<details class="turn" ${x.idx === th.turns.length - 1 ? "open" : ""}>
            <summary class="turn-head">${who(x.agent || x.heading, x.slot)} <span>${esc(x.date)}</span>
              ${x.kind === "moderator" ? (x.sealed ? pill("fechado", t("dec.sealed")) : pill("bloqueado", t("dec.unsealed"))) : ""}</summary>
            <div class="turn-body prose small">${renderMd(x.md.slice(0, 6000))}</div></details>`).join("")}</div>
      </div>`;
    $("#th-sel").onchange = (e) => { S.activeThread = e.target.value; renderDecisions(); };
    $$("[data-dec]", el).forEach((b) => (b.onclick = async () => {
      try {
        await api("api/decide", { file: th.file, sha: th.sha, decisions: [{ id: b.dataset.q, state: b.dataset.dec }] });
        toast(t("dec.recorded", { q: b.dataset.q }));
        await refreshState(); renderDecisions(); syncSub("decisions");
      } catch (e) { toast(e.message); }
    }));
  }

  // ---------- Quality: three levels — thesis (macro), chapter, section (micro) ----------
  function qlRows(list, chNum) {
    const shown = list.filter((c) => !S.qlOnly || c.state !== "ok");
    if (!shown.length) return `<div class="empty">✓</div>`;
    return `<table class="table ql"><thead><tr><th>${t("ql.group")}</th><th>${t("ql.check")}</th><th>${t("ql.status")}</th><th>${t("ql.count")}</th><th></th></tr></thead><tbody>
      ${shown.map((c) => `<tr class="ql-row" data-id="${esc(c.id)}"><td class="muted">${esc(c.group)}</td>
        <td><b>${esc(S.dict[`check.${c.id}`] || c.label)}</b><div class="sub">${esc(c.rule)}${c.note ? ` — ${esc(c.note)}` : ""}</div></td>
        <td>${qlPill(c.state)}</td><td class="mono">${c.state === "na" && !c.count ? "—" : fmt(c.count)}</td>
        <td class="nowrap">${c.state === "na" && (c.pack === "agent-review" || c.id === "thesis_narrative") ? `<button class="btn sm" data-review="${esc(c.id)}">${t("ql.request")}</button>` : ""}</td></tr>
        ${c.items.length ? `<tr class="ql-items" hidden><td colspan="5">${c.items.map((it) => `<div class="ql-item"><span class="mono">${esc(it.file)}${it.line ? ":" + it.line : ""}</span>
          ${it.detail ? `<b>${esc(it.detail)}</b>` : ""}<div class="sub">${esc(it.text)}</div></div>`).join("")}</td></tr>` : ""}`).join("")}
    </tbody></table>`;
  }

  async function renderQuality(param) {
    const el = $("#view-quality");
    if (!S.quality || param === "refresh") { el.innerHTML = `<div class="empty">${t("loading")}</div>`; S.quality = await api("api/quality"); }
    const q = S.quality, chs = q.chapters;
    const level = S.qlLevel || "thesis";
    const pick = Number(param) || S.qlChapter || (chs[0] && chs[0].chapter);
    S.qlChapter = pick;
    const ch = chs.find((c) => c.chapter === pick);
    const budgets = Object.fromEntries(S.state.chapters.map((c) => [c.number, c.budget || {}]));
    const levels = ["thesis", "chapter", "section"].map((l) => `<button class="${level === l ? "on" : ""}" data-level="${l}">${t("ql.level." + l)}</button>`).join("");
    let body = "";
    if (level === "thesis") {
      body = `<div class="card"><h2>${t("ql.level.thesis")}</h2><div class="sub" style="margin:-6px 0 10px">${t("ql.thesis_h")}</div>${qlRows(q.thesis_checks)}</div>
        <div class="card"><h2>${t("ql.by_chapter")}</h2><table class="table"><thead><tr><th>${t("ch")}</th><th>${t("title")}</th><th>${t("pg.pages")}</th>
          <th>${t("ql.state.bad")}</th><th>${t("ql.state.warn")}</th><th>${t("ql.state.na")}</th></tr></thead><tbody>
          ${chs.map((c) => { const b = budgets[c.chapter] || {};
            return `<tr class="ql-ch" data-ch="${c.chapter}"><td class="mono">${c.chapter}</td><td><a href="#quality/${c.chapter}">${esc(c.title)}</a></td>
              <td class="mono">${b.estimate_now != null ? `${num1(b.estimate_now)} / ${b.target ? b.target[1] : "—"}` : "—"}</td>
              <td>${c.summary.bad ? pill("bloqueado", c.summary.bad) : "0"}</td><td>${c.summary.warn ? pill("espera", c.summary.warn) : "0"}</td><td class="muted">${c.summary.na}</td></tr>`; }).join("")}
          </tbody></table></div>`;
    } else if (level === "chapter" && ch) {
      body = `<div class="card"><h2>${t("ql.chapter")} ${ch.chapter}: ${esc(ch.title)} <span class="muted mono">${fmt(ch.words)} ${t("words")}</span></h2>${qlRows(ch.checks, ch.chapter)}</div>`;
    } else if (ch) {
      const groups = [...new Set(ch.checks.map((c) => c.group))].filter((g) => ch.sections.some((s) => s.problems[g]));
      body = `<div class="card"><h2>${t("ql.level.section")} — ${t("ch")} ${ch.chapter}: ${esc(ch.title)}</h2><div class="sub" style="margin:-6px 0 10px">${t("ql.section_h")}</div>
        <table class="table ql-sec"><thead><tr><th>${t("ql.section")}</th><th>${t("words")}</th><th>%</th><th>${t("ql.cites_k")}</th>
          ${groups.map((g) => `<th>${esc(g)}</th>`).join("")}</tr></thead><tbody>
          ${ch.sections.map((s) => `<tr class="ql-srow" data-path="${esc(s.path)}"><td><b>${esc(s.title)}</b><div class="sub mono">${esc(s.path.split("/").pop())}</div></td>
            <td class="mono">${fmt(s.words)}</td><td class="mono">${Math.round(s.share * 100)}%<div class="bar"><i style="width:${Math.min(100, Math.round(s.share * 100 * 2))}%"></i></div></td>
            <td class="mono">${s.citations_per_1000}</td>
            ${groups.map((g) => { const x = s.problems[g]; return `<td>${!x ? "·" : x.bad ? pill("bloqueado", x.bad + (x.warn ? ` +${x.warn}` : "")) : pill("espera", x.warn)}</td>`; }).join("")}</tr>
            <tr class="ql-sitems" hidden><td colspan="${4 + groups.length}">${ch.checks.filter((c) => c.state === "warn" || c.state === "bad").map((c) => {
              const its = c.items.filter((i) => i.file === s.path);
              return its.length ? `<div class="ql-item"><b>${esc(S.dict[`check.${c.id}`] || c.label)}</b> ${qlPill(c.state)}${its.slice(0, 12).map((i) => `<div class="sub"><span class="mono">:${i.line}</span> ${esc(i.detail || "")} — ${esc(i.text)}</div>`).join("")}</div>` : "";
            }).join("")}</td></tr>`).join("")}
        </tbody></table></div>`;
    }
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("ql.title")}</h1><div class="sub">${t("ql.sub")}</div></div>
        <div class="toolbar"><div class="seg big">${levels}</div>
          ${level !== "thesis" ? `<select id="ql-ch">${chs.map((c) => `<option value="${c.chapter}"${c.chapter === pick ? " selected" : ""}>${t("ch")} ${c.chapter} — ${esc(c.title)} (${c.summary.bad}✕ ${c.summary.warn}!)</option>`).join("")}</select>` : ""}
          ${level !== "section" ? `<label class="chk"><input type="checkbox" id="ql-only" ${S.qlOnly ? "checked" : ""}> ${t("ql.only_problems")}</label>` : ""}
          <button class="btn sm" id="ql-refresh">↻</button></div></div>
      ${q.plugin_errors.length ? `<div class="card alert"><h2>${t("ql.plugin_errors")}</h2>${q.plugin_errors.map((e) => `<div class="mono">${esc(e)}</div>`).join("")}</div>` : ""}
      ${body}`;
    $$("[data-level]", el).forEach((b) => (b.onclick = () => { S.qlLevel = b.dataset.level; renderQuality(String(pick)); }));
    const sel = $("#ql-ch", el); if (sel) sel.onchange = (e) => { S.qlChapter = Number(e.target.value); renderQuality(e.target.value); };
    const only = $("#ql-only", el); if (only) only.onchange = (e) => { S.qlOnly = e.target.checked; renderQuality(String(pick)); };
    $("#ql-refresh", el).onclick = () => renderQuality("refresh");
    $$(".ql-ch", el).forEach((r) => (r.onclick = (e) => { e.preventDefault(); S.qlLevel = "chapter"; S.qlChapter = Number(r.dataset.ch); renderQuality(r.dataset.ch); }));
    $$(".ql-row, .ql-srow", el).forEach((r) => (r.onclick = (e) => {
      if (e.target.closest("button")) return;
      const nxt = r.nextElementSibling;
      if (nxt && (nxt.classList.contains("ql-items") || nxt.classList.contains("ql-sitems"))) nxt.hidden = !nxt.hidden;
    }));
    $$("[data-review]", el).forEach((b) => (b.onclick = () => {
      const role = { narrative: "narrative-reviewer", tone: "tone-reviewer", consistency: "consistency-checker", thesis_narrative: "thesis-narrative-reviewer" }[b.dataset.review];
      createTask(b.dataset.review === "thesis_narrative" ? { role } : { role, chapter: pick });
    }));
  }

  // ---------- Literature ----------
  // Three different verifications, never merged into one number: the seal (files unchanged since sealing),
  // the source match (the archived source is the work of the entry) and verified passages (sentence by sentence).
  async function renderLiterature(_, params) {
    const el = $("#view-literature");
    if (params?.get("q")) S.litFilter.q = params.get("q");
    if (!S.literature) { el.innerHTML = `<div class="empty">${t("loading")}</div>`; S.literature = await api("api/literature"); }
    const d = S.literature, sm = d.summary || {}, q = S.litFilter.q.toLowerCase(), stf = S.litFilter.status;
    const keep = (e) => stf === "all" || e.match === stf || e.seal === stf || (stf === "passages" && e.verified_passages) || (stf === "no_passages" && !e.verified_passages);
    const rows = d.entries.filter((e) => keep(e) && (!q || `${e.key} ${e.title} ${e.author} ${e.year} ${e.venue}`.toLowerCase().includes(q)));
    const M = { confirmed: "fechado", doubtful: "espera", mismatch: "bloqueado", no_text: "aberto", no_source: "aberto" };
    const SE = { intact: "fechado", changed: "bloqueado", not_sealed: "aberto" };
    const opts = [["all", t("lit.all")], ["confirmed", t("lit.m.confirmed")], ["doubtful", t("lit.m.doubtful")], ["mismatch", t("lit.m.mismatch")],
      ["no_text", t("lit.m.no_text")], ["no_source", t("lit.m.no_source")], ["changed", t("lit.s.changed")], ["passages", t("lit.with_passages")], ["no_passages", t("lit.without_passages")]];
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("lit.title")}</h1><div class="sub"><span class="mono">${esc(d.provider)}</span> · <span class="mono">${esc(d.syntax)}</span> · ${d.total} ${t("lit.works")}</div></div></div>
      <div class="stats">
        ${sm.seal ? `<div class="stat"><div class="k">${t("lit.seal")}</div><div class="v">${fmt(sm.seal.intact)} / ${fmt(d.total)}</div><div class="h">${t("lit.seal_h", { c: sm.seal.changed, n: sm.seal.not_sealed })}</div></div>` : ""}
        <div class="stat"><div class="k">${t("lit.match")}</div><div class="v">${fmt(sm.match?.confirmed)} / ${fmt(d.total)}</div><div class="h">${t("lit.match_h", { d: sm.match?.doubtful || 0, m: sm.match?.mismatch || 0, x: sm.match?.no_text || 0, s: sm.match?.no_source || 0 })}</div></div>
        <div class="stat"><div class="k">${t("lit.passages")}</div><div class="v">${fmt(sm.passages)} / ${fmt(d.total)}</div><div class="h">${t("lit.passages_h")}</div></div>
      </div>
      <div class="toolbar"><input class="input" id="lit-q" placeholder="${esc(t("lit.filter"))}" value="${esc(S.litFilter.q)}" style="min-width:280px">
        <select id="lit-st">${opts.map(([k, l]) => `<option value="${k}"${stf === k ? " selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="card">${rows.length ? `<table class="table"><thead><tr><th>${t("lit.key")}</th><th>${t("title")}</th><th>${t("lit.seal")}</th><th>${t("lit.match")}</th><th>${t("lit.passages")}</th></tr></thead><tbody>
        ${rows.slice(0, 400).map((e) => `<tr><td class="mono">${esc(e.key)}<div class="sub">${esc(e.author || "—")} (${esc(e.year || "n.d.")})</div></td>
          <td>${esc(e.title || "—")}<div class="sub">${esc(e.venue || "")}</div></td>
          <td>${e.seal ? pill(SE[e.seal], t(`lit.s.${e.seal}`)) : "—"}</td>
          <td>${pill(M[e.match] || "aberto", t(`lit.m.${e.match}`))}${e.match_score != null ? `<div class="sub mono">${e.match_score}</div>` : ""}</td>
          <td class="mono">${e.verified_passages || 0}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">—</div>`}</div>`;
    $("#lit-q").oninput = (e) => { S.litFilter.q = e.target.value; renderLiterature().then(() => { const n = $("#lit-q"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }); };
    $("#lit-st").onchange = (e) => { S.litFilter.status = e.target.value; renderLiterature(); };
  }

  // ---------- Agents ----------
  function taskPhrase(task) {
    return S.state.config.ui.locale === "pt"
      ? `Faz a tarefa ${task.id} da bancada: lê ${S.state.config.agents.tasks_dir}/${task.id}.json, corre o papel indicado (como subagente, se puderes) e valida com "python3 -m atw review validate ${task.id} --workspace .".`
      : `Do workbench task ${task.id}: read ${S.state.config.agents.tasks_dir}/${task.id}.json, run the role it names (as a sub-agent if you can) and validate with "python3 -m atw review validate ${task.id} --workspace .".`;
  }

  async function createTask(body) {
    try {
      const r = await api("api/tasks", body);
      const main = r.tasks[0];
      const phrase = taskPhrase(main);
      modal(`<h2>${t("ms.task_created")}</h2><div class="phrase mono" id="m-phrase">${esc(phrase)}</div>
        ${r.tasks.length > 1 ? `<div class="sub">${r.tasks.map((x) => `${esc(x.id)} ${esc(x.role || x.workflow)}`).join(" · ")}</div>` : ""}
        <div class="modal-actions"><button class="btn" id="m-cancel">${t("close")}</button><button class="btn primary" id="m-copy">${t("copy")}</button></div>`, (m) => {
        $("#m-cancel", m).onclick = closeModal;
        $("#m-copy", m).onclick = async () => { try { await navigator.clipboard.writeText(phrase); toast(t("copied")); } catch (_) {} };
      });
      S.agents = null;
      await refreshState(); syncSub(S.view);
    } catch (e) { toast(e.message); }
  }

  async function renderAgents() {
    const el = $("#view-agents");
    S.agents = await api("api/agents");
    const a = S.agents;
    const chOpts = S.state.chapters.map((c) => `<option value="${c.number}">${t("ch")} ${c.number} — ${esc(c.title)}</option>`).join("");
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("ag.title")}</h1><div class="sub">${t("ag.sub")}</div></div></div>
      <div class="card"><h2>${t("ag.new_task")}</h2>
        <div class="toolbar">
          <select id="ag-kind"><optgroup label="${t("ag.workflows")}">${a.workflows.map((w) => `<option value="wf:${esc(w.id)}">${esc(w.id)}</option>`).join("")}</optgroup>
            <optgroup label="${t("ag.roles")}">${a.roles.map((r) => `<option value="role:${esc(r.id)}">${esc(r.id)}</option>`).join("")}</optgroup></select>
          <select id="ag-ch">${chOpts}</select>
          <button class="btn primary" id="ag-create">${t("ag.create")}</button></div>
        <div class="sub mono">${t("ag.export")}</div></div>
      <div class="grid-2">
        <div class="card"><h2>${t("ag.tasks")}</h2>
          ${a.tasks.length ? `<table class="table"><tbody>${a.tasks.slice().reverse().map((x) => `<tr>
            <td class="mono">${esc(x.id)}</td><td>${esc(x.role || "workflow: " + x.workflow)}<div class="sub">${t("ch")} ${esc(x.chapter ?? "—")} · ${esc((x.created || "").slice(0, 16).replace("T", " "))}</div>
              ${(x.errors || []).length ? `<div class="sub bad">${x.errors.map(esc).join("<br>")}</div>` : ""}</td>
            <td>${x.status === "done" ? pill("fechado", t("ag.valid")) : x.status === "invalid" ? pill("bloqueado", t("ag.invalid")) : pill("aberto", t("ag.pending"))}</td>
            <td class="nowrap"><button class="btn sm" data-say="${esc(x.id)}">${t("ag.say")}</button>${x.has_output ? ` <button class="btn sm" data-val="${esc(x.id)}">${t("ag.validate")}</button>` : ""}</td></tr>`).join("")}</tbody></table>`
            : `<div class="empty">${t("ag.no_tasks")}</div>`}</div>
        <div class="card"><h2>${t("ag.reviews")}</h2>
          ${a.reviews.length ? a.reviews.slice().reverse().map((r) => `<details class="turn"><summary class="turn-head">${esc(r.task)} · ${esc(r.role || "")} · ${t("ch")} ${esc(r.chapter ?? "—")}
            ${who(r.agent?.name || "?", "1")} ${r.valid ? pill("fechado", t("ag.valid")) : pill("bloqueado", t("ag.invalid"))}</summary>
            <p>${esc(r.summary)}</p>${(r.findings || []).map((f) => `<div class="ql-item"><span class="mono">${esc(f.file || "")}${f.line ? ":" + f.line : ""}</span> <b>${esc(f.severity)}</b> ${esc(f.problem)}${f.suggestion ? `<div class="sub">→ ${esc(f.suggestion)}</div>` : ""}</div>`).join("")}</details>`).join("")
            : `<div class="empty">—</div>`}</div>
      </div>
      <div class="grid-2">
        <div class="card"><h2>${t("ag.roles")} (${a.roles.length})</h2>${a.roles.map((r) => `<div class="role"><b class="mono">${esc(r.id)}</b> <span class="tag">${t("ag.writes")} ${esc(r.writes)}</span>${r.fills_check ? ` <span class="tag">${t("ag.fills")} ${esc(r.fills_check)}</span>` : ""}
          <div class="sub">${esc(r.description)}</div></div>`).join("")}${a.role_errors.map((e) => `<div class="sub bad mono">${esc(e)}</div>`).join("")}</div>
        <div class="card"><h2>${t("ag.workflows")}</h2>${a.workflows.map((w) => `<div class="role"><b class="mono">${esc(w.id)}</b><div class="sub">${esc(w.description || "")}</div><div class="sub mono">${(w.roles || []).map(esc).join(" → ")}</div></div>`).join("")}</div>
      </div>`;
    if (S.activeChapter) $("#ag-ch").value = String(S.activeChapter);
    $("#ag-create").onclick = () => {
      const [k, id] = $("#ag-kind").value.split(":");
      createTask(k === "wf" ? { workflow: id, chapter: Number($("#ag-ch").value) } : { role: id, chapter: Number($("#ag-ch").value) });
    };
    $$("[data-say]", el).forEach((b) => (b.onclick = () => {
      const phrase = taskPhrase({ id: b.dataset.say });
      navigator.clipboard?.writeText(phrase).then(() => toast(t("copied")), () => toast(phrase, 6000));
    }));
    $$("[data-val]", el).forEach((b) => (b.onclick = async () => {
      try { const r = await api("api/validate", { task: b.dataset.val }); toast(r.ok ? t("ag.valid") : r.errors.join(" · "), 5000); await afterChange(); }
      catch (e) { toast(e.message); }
    }));
  }

  // ---------- Config ----------
  async function renderConfig() {
    const el = $("#view-config");
    const a = S.agents || (S.agents = await api("api/agents"));
    const plan = S.state.config.plan || {};
    const chs = Object.entries(plan.chapters || {});
    const pair = (v) => (Array.isArray(v) ? `${v[0]}–${v[1]}` : "—");
    el.innerHTML = `
      <div class="page-head"><div><h1>${t("cfg.title")}</h1><div class="sub">${t("cfg.sub")} · ${esc(S.state.host_shell)}</div></div></div>
      <div class="card"><h2>${t("cfg.plan")}</h2>
        <div class="sub">${plan.file ? t("cfg.plan_h", { f: `<code class="mono">${esc(plan.file)}</code>` }) : t("cfg.no_plan")}</div>
        ${chs.length ? `<table class="table"><thead><tr><th>${t("ch")}</th><th>${t("title")}</th><th>${t("pg.pages")}</th><th>${t("words")}</th><th>${t("cfg.sections")}</th><th>${t("ms.narrative")}</th></tr></thead><tbody>
          ${chs.map(([n, c]) => `<tr><td class="mono">${esc(n)}</td><td>${esc(c.title || "")}<div class="sub">${esc(c.part || "")}</div></td>
            <td class="mono">${pair(c.pages)}</td><td class="mono">${pair(c.words)}</td><td class="mono">${esc(c.sections ?? "")}</td>
            <td class="sub">${esc((c.narrative || "").slice(0, 220))}</td></tr>`).join("")}</tbody></table>` : ""}
      </div>
      <div class="grid-2"><div class="card"><h2>${t("cfg.engine")} — ${t("cfg.resolved")}</h2><pre class="mono pre">${esc(JSON.stringify({ ...S.state.config, plan: undefined }, null, 2))}</pre></div>
      <div class="card"><h2>${t("cfg.plugins")}</h2>${a.plugins.map((p) => `<div class="role"><b class="mono">${esc(p.id)}</b> <span class="tag">${esc(p.version)}</span> <span class="sub">${esc(p.source)}</span><div class="sub">${esc(p.description || "")}</div></div>`).join("")}
        ${a.plugin_errors.map((e) => `<div class="sub bad mono">${esc(e)}</div>`).join("")}</div></div>`;
  }

  // ---------- keyboard & live refresh ----------
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select"].includes(tag) || $(".modal-wrap")) return;
    const k = e.key.toLowerCase();
    if (S.view === "manuscript" && S.sel && !window.getSelection().isCollapsed) {
      if (k === "c") { e.preventDefault(); openComposer("comment"); }
      if (k === "s") { e.preventDefault(); openComposer("suggest"); }
    }
    if (S.view === "queue" && S.queue?.items?.length && S.qi >= 0) {
      if (k === "a") queueAct(S.queue.items[S.qi].source === "change" || S.queue.items[S.qi].status === "addressed" ? "accept" : "confirm");
      if (k === "r") queueAct("reopen");
      if (k === "w" && S.queue.items[S.qi].source !== "change") queueAct("wontfix");
      if (k === "j" || e.key === "ArrowDown") { e.preventDefault(); queueStep(1); }
      if (k === "k" || e.key === "ArrowUp") { e.preventDefault(); queueStep(-1); }
    }
  });

  async function poll() {
    try {
      const { etag } = await api("api/etag");
      const selecting = window.getSelection && !window.getSelection().isCollapsed;
      if (etag !== S.etag && !$(".modal-wrap") && !selecting && !S.busy && !$(".menu[open]")) {
        S.busy = true;
        S.chapter = {}; S.queue = null; S.literature = null; S.quality = null; S.ctx = {};
        await refreshState();
        await render();
        S.busy = false;
      }
    } catch (_) { S.busy = false; }
  }

  window.addEventListener("hashchange", render);
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (S.view === "manuscript" && S.msMode !== "pdf" && S.msNotes) layoutMargin($("#view-manuscript")); }, 150);
  });
  refreshState().then(render).catch((err) => {
    $("#view-overview").hidden = false;
    $("#view-overview").innerHTML = `<div class="card"><h2>Error</h2><p>${esc(err.message)}</p></div>`;
  });
  setInterval(poll, 5000);
})();
