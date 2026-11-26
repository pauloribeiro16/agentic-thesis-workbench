/* Agentic Thesis Workbench — standalone & second-brain compatible SPA.
   All API calls are relative ("api/...") so the app works identically at "/" and "/tese/". */
(function () {
  "use strict";

  const S = {
    state: null,
    literature: null,
    quality: null,
    chapterCache: {},
    activeChapter: null,
    litFilter: { status: "all", q: "" },
    activeThread: null,
  };

  const THESIS_TABS = [
    ["overview", "Overview"],
    ["manuscript", "Manuscript"],
    ["decisions", "Decisions"],
    ["quality", "Quality"],
  ];

  const STATE_TO_ST = {
    OPEN: ["aberto", "Open"],
    AGENT_CONSENSUS: ["curso", "Agent consensus"],
    AUTHOR_RESERVED: ["espera", "Reserved for author"],
    SINGLE_PROPOSAL: ["espera", "Single proposal"],
    APPROVED: ["fechado", "Approved"],
    AGENT_DEADLOCK: ["bloqueado", "Deadlock"],
  };

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString("en-US");

  function statusPill(st) {
    const [k, label] = STATE_TO_ST[st] || ["aberto", st || "Open"];
    return `<span class="st" data-st="${k}">${esc(label)}</span>`;
  }

  function qualityPill(st) {
    const map = { ok: ["fechado", "OK"], warn: ["espera", "Review"], bad: ["bloqueado", "Violation"], na: ["aberto", "Agent review"] };
    const [k, label] = map[st] || ["aberto", st];
    return `<span class="st" data-st="${k}">${esc(label)}</span>`;
  }

  function whoBadge(name, slot) {
    return `<span class="who who-${esc(slot || "0")}"><span class="dot"></span>${esc(name || "Agent")}</span>`;
  }

  function toast(msg) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  function simpleMd(raw) {
    const escaped = esc(raw || "");
    return escaped
      .replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm, "<h2>$1</h2>")
      .replace(/^# (.+)$/gm, "<h1>$1</h1>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\(([A-Z][^()]*?(?:19|20)\d{2}[a-z]?[^()]*)\)/g, (_, inner) =>
        `<a class="cite-pill" href="#literature?q=${encodeURIComponent(inner.split(",")[0].trim())}">${inner}</a>`
      )
      .replace(/\[@([A-Za-z0-9_:\-\.]+)\]/g, (_, key) =>
        `<a class="cite-pill" href="#literature?q=${encodeURIComponent(key)}">@${key}</a>`
      )
      .replace(/\n\n+/g, "</p><p>")
      .replace(/^/, "<p>")
      .replace(/$/, "</p>");
  }

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  function currentRoute() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, qs] = raw.split("?");
    const [view, param] = (path || "overview").split("/");
    const params = new URLSearchParams(qs || "");
    return { view: view || "overview", param: param || "", params };
  }

  function syncSubNav(view) {
    if (!window.plat) return;
    const isThesis = THESIS_TABS.some(([k]) => k === view);
    if (!isThesis) {
      window.plat.setSub([]);
      return;
    }
    const waiting = S.state?.stats?.questions_waiting || 0;
    const words = S.state?.stats?.total_words || 0;
    window.plat.setSub(
      THESIS_TABS.map(([k, label]) => ({
        k,
        label,
        href: "#" + k,
        badge: k === "decisions" && waiting ? waiting : 0,
      })),
      view,
      `${fmt(words)} words · ${S.state?.config?.format?.adapter || ""}`
    );
  }

  function syncPalette() {
    if (!window.plat || !window.plat.setSearchItems || !S.state) return;
    const items = [];
    for (const ch of S.state.chapters || []) {
      items.push({ g: "Chapters", t: `Ch. ${ch.number} — ${ch.title}`, s: `${fmt(ch.words)} words`, href: `#manuscript/${ch.number}` });
    }
    for (const th of S.state.threads || []) {
      for (const q of th.questions || []) {
        items.push({ g: "Decisions", t: `${q.id} — ${q.title}`, s: q.state, r: th.file, href: "#decisions" });
      }
    }
    window.plat.setSearchItems(items);
  }

  function renderOverview() {
    const st = S.state;
    const el = $("#view-overview");
    if (!st) { el.innerHTML = `<div class="empty">Loading workspace…</div>`; return; }
    const s = st.stats;
    const waiting = st.threads.flatMap((t) =>
      t.questions.filter((q) => q.state !== "APPROVED" && q.state !== "OPEN").map((q) => ({ ...q, file: t.file }))
    );

    el.innerHTML = `
      <div class="page-head">
        <div>
          <h1>${esc(st.config.project.title)}</h1>
          <div class="sub">${esc(st.config.project.author)} · Format: <span class="mono">${esc(st.config.format.adapter)}</span> · Citations: <span class="mono">${esc(st.config.citations.provider)}</span></div>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><div class="k">Total Words</div><div class="v">${fmt(s.total_words)}</div><div class="h">${s.chapters} chapters discovered</div></div>
        <div class="stat"><div class="k">Waiting Decisions</div><div class="v">${fmt(s.questions_waiting)}</div><div class="h">${s.questions_total} total questions</div></div>
        <div class="stat"><div class="k">Literature</div><div class="v">${fmt(s.literature_total)}</div><div class="h">${s.literature_verified} passage-verified</div></div>
        <div class="stat"><div class="k">Active Agents</div><div class="v">${fmt(s.agents_count)}</div><div class="h">Model-agnostic threads</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h2>Chapters</h2>
          ${st.chapters.length ? `<table class="table"><thead><tr><th>Ch.</th><th>Title</th><th>Words</th><th>Progress</th></tr></thead><tbody>
            ${st.chapters.map((c) => {
              const pct = c.target[1] ? Math.min(100, Math.round((c.words / c.target[1]) * 100)) : 0;
              return `<tr>
                <td class="mono">${String(c.number).padStart(2, "0")}</td>
                <td><a href="#manuscript/${c.number}">${esc(c.title)}</a><div class="sub">${c.section_count} file(s)</div></td>
                <td class="mono">${fmt(c.words)} / ${fmt(c.target[1])}</td>
                <td style="min-width:110px"><div class="bar"><i style="width:${pct}%"></i></div></td>
              </tr>`;
            }).join("")}
          </tbody></table>` : `<div class="empty">No chapters matched <code class="mono">${esc(st.config.format.chapters_glob)}</code>.</div>`}
        </div>
        <div class="card">
          <h2>Waiting for Author</h2>
          ${waiting.length ? `<table class="table"><tbody>
            ${waiting.slice(0, 8).map((q) => `<tr>
              <td class="mono">${esc(q.id)}</td>
              <td><a href="#decisions">${esc(q.title)}</a><div class="sub">${esc(q.file)}</div></td>
              <td>${statusPill(q.state)}</td>
            </tr>`).join("")}
          </tbody></table>` : `<div class="empty">No pending decisions.</div>`}
        </div>
      </div>`;
  }

  async function renderManuscript(param) {
    const el = $("#view-manuscript");
    const chapters = S.state?.chapters || [];
    if (!chapters.length) {
      el.innerHTML = `<div class="card"><div class="empty">No chapters found in workspace.</div></div>`;
      return;
    }
    const chNum = Number(param) || S.activeChapter || chapters[0].number;
    S.activeChapter = chNum;

    if (!S.chapterCache[chNum]) {
      el.innerHTML = `<div class="empty">Loading chapter ${chNum}…</div>`;
      S.chapterCache[chNum] = await api(`api/chapter/${chNum}`);
    }
    const ch = S.chapterCache[chNum];
    const comments = S.state?.comments?.[`CH${chNum}`] || [];

    el.innerHTML = `
      <div class="page-head">
        <div>
          <h1>Chapter ${ch.number}: ${esc(ch.title)}</h1>
          <div class="sub">${fmt(ch.words)} words · ${ch.sections.length} section(s) · ${comments.length} anchored comment(s)</div>
        </div>
        <div class="toolbar">
          <select id="ms-ch-select">${chapters.map((c) => `<option value="${c.number}"${c.number === chNum ? " selected" : ""}>Ch. ${c.number} — ${esc(c.title)}</option>`).join("")}</select>
        </div>
      </div>
      <div class="grid-2">
        <div class="card prose">
          ${ch.sections.map((s) => `<div style="margin-bottom:28px"><div class="mono" style="color:var(--faint);margin-bottom:8px">${esc(s.path)} (${fmt(s.words)} words)</div>${simpleMd(s.content)}</div>`).join("<hr style='border:none;border-top:1px solid var(--line);margin:24px 0'>")}
        </div>
        <div class="card">
          <h2>Anchored Comments & Proposals</h2>
          ${comments.length ? comments.map((cm) => `<div class="turn"><div class="turn-head"><b>${esc(cm.author || "Review")}</b></div><div>${esc(cm.body || cm.text || "")}</div></div>`).join("") : `<div class="empty">No anchored comments for Chapter ${chNum}.</div>`}
        </div>
      </div>`;

    const sel = $("#ms-ch-select");
    if (sel) sel.onchange = () => { location.hash = `#manuscript/${sel.value}`; };
  }

  function renderDecisions() {
    const el = $("#view-decisions");
    const threads = S.state?.threads || [];
    if (!threads.length) {
      el.innerHTML = `<div class="card"><h2>Multi-Agent Decisions</h2><div class="empty">No dialogue threads found in <code class="mono">${esc(S.state?.config?.agents?.dialogue_dir || ".thesis/dialogue")}</code>.</div></div>`;
      return;
    }
    const activeFile = S.activeThread || threads[0].file;
    const th = threads.find((t) => t.file === activeFile) || threads[0];
    S.activeThread = th.file;

    el.innerHTML = `
      <div class="page-head">
        <div><h1>Decisions & Agent Dialogue</h1><div class="sub">Append-only threads with HMAC-authenticated moderator approvals</div></div>
        <div class="toolbar">
          <select id="th-select">${threads.map((t) => `<option value="${esc(t.file)}"${t.file === th.file ? " selected" : ""}>${esc(t.file)} (${t.questions.length} Qs)</option>`).join("")}</select>
        </div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h2>Questions (${th.questions.length})</h2>
          <table class="table"><thead><tr><th>ID</th><th>Topic</th><th>State</th><th>Action</th></tr></thead><tbody>
            ${th.questions.map((q) => `<tr>
              <td class="mono">${esc(q.id)}</td>
              <td>${esc(q.title)}</td>
              <td>${statusPill(q.state)}</td>
              <td>${q.state !== "APPROVED" ? `<button class="btn primary approve-btn" data-qid="${esc(q.id)}">Approve</button>` : `<span class="mono" style="color:var(--st-fechado)">${q.authenticated ? "sealed ✓" : "approved"}</span>`}</td>
            </tr>`).join("")}
          </tbody></table>
        </div>
        <div class="card">
          <h2>Turns (${th.turns.length})</h2>
          ${th.turns.map((t) => `<div class="turn">
            <div class="turn-head">${whoBadge(t.agent, t.slot)} <span>${esc(t.date)}</span> ${t.sealed ? `<span class="st" data-st="fechado">HMAC verified</span>` : ""}</div>
            <div style="font-size:13.5px">${simpleMd(t.md.slice(0, 600))}${t.md.length > 600 ? "<p class='sub'>…</p>" : ""}</div>
          </div>`).join("")}
        </div>
      </div>`;

    const sel = $("#th-select");
    if (sel) sel.onchange = () => { S.activeThread = sel.value; renderDecisions(); };

    el.querySelectorAll(".approve-btn").forEach((btn) => {
      btn.onclick = async () => {
        const qid = btn.dataset.qid;
        try {
          await api("api/decide", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file: th.file, sha: th.sha, decisions: [{ id: qid, state: "APPROVED", note: "Approved in workbench." }] }),
          });
          toast(`Decision recorded & sealed for ${qid}`);
          await refreshState();
          renderDecisions();
        } catch (err) {
          toast(`Failed: ${err.message}`);
        }
      };
    });
  }

  async function renderQuality() {
    const el = $("#view-quality");
    el.innerHTML = `<div class="empty">Running quality checks…</div>`;
    S.quality = await api("api/quality");
    const chs = S.quality.chapters || [];
    el.innerHTML = `
      <div class="page-head">
        <div><h1>Structural & Consistency Quality</h1><div class="sub">Read-only deterministic checks + qualitative agent review slots (${S.quality.style_guide_entries} style guide entries)</div></div>
      </div>
      ${chs.length ? chs.map((ch) => `<div class="card">
        <h2>Chapter ${ch.chapter}: ${esc(ch.title)} <span class="mono" style="color:var(--muted);font-weight:400">(${fmt(ch.words)} words)</span></h2>
        <table class="table"><thead><tr><th>Group</th><th>Check</th><th>Rule</th><th>Status</th><th>Count</th></tr></thead><tbody>
          ${ch.checks.map((c) => `<tr>
            <td style="color:var(--muted)">${esc(c.group)}</td>
            <td><b>${esc(c.label)}</b></td>
            <td style="color:var(--muted);font-size:13px">${esc(c.rule)}</td>
            <td>${qualityPill(c.state)}</td>
            <td class="mono">${c.state === "na" ? "—" : fmt(c.count)}</td>
          </tr>`).join("")}
        </tbody></table>
      </div>`).join("") : `<div class="card"><div class="empty">No chapters available to check.</div></div>`}`;
  }

  async function renderLiterature(params) {
    const el = $("#view-literature");
    if (params && params.get("q")) S.litFilter.q = params.get("q");
    if (!S.literature) {
      el.innerHTML = `<div class="empty">Loading literature…</div>`;
      S.literature = await api("api/literature");
    }
    const data = S.literature;
    const q = (S.litFilter.q || "").toLowerCase();
    const stFilter = S.litFilter.status;
    const rows = (data.entries || []).filter((e) => {
      if (stFilter !== "all" && e.status !== stFilter) return false;
      if (!q) return true;
      return `${e.key} ${e.title} ${e.author} ${e.year} ${e.venue}`.toLowerCase().includes(q);
    });

    el.innerHTML = `
      <div class="page-head">
        <div><h1>Literature & Citations</h1><div class="sub">Provider: <span class="mono">${esc(data.provider)}</span> · Syntax: <span class="mono">${esc(data.syntax)}</span> · ${data.verified}/${data.total} passage-verified</div></div>
      </div>
      <div class="toolbar">
        <input class="input" id="lit-q" placeholder="Filter by key, author, title, year…" value="${esc(S.litFilter.q)}" style="min-width:260px">
        <select id="lit-st">
          <option value="all"${stFilter === "all" ? " selected" : ""}>All statuses (${data.total})</option>
          <option value="verified"${stFilter === "verified" ? " selected" : ""}>Verified (${data.verified})</option>
          <option value="archived"${stFilter === "archived" ? " selected" : ""}>Archived PDF/MD</option>
          <option value="bib_only"${stFilter === "bib_only" ? " selected" : ""}>Bibliography only</option>
        </select>
      </div>
      <div class="card">
        ${rows.length ? `<table class="table"><thead><tr><th>Key</th><th>Author & Year</th><th>Title</th><th>Status</th></tr></thead><tbody>
          ${rows.slice(0, 200).map((e) => `<tr>
            <td class="mono">${esc(e.key)}</td>
            <td>${esc(e.author || "—")} <span class="mono">(${esc(e.year || "n.d.")})</span></td>
            <td>${esc(e.title || "—")}<div class="sub">${esc(e.venue || "")}</div></td>
            <td><span class="st" data-st="${e.status === "verified" ? "fechado" : e.status === "archived" ? "curso" : "aberto"}">${esc(e.status)}</span></td>
          </tr>`).join("")}
        </tbody></table>` : `<div class="empty">No bibliography entries matched.</div>`}
      </div>`;

    $("#lit-q").oninput = (ev) => { S.litFilter.q = ev.target.value; renderLiterature(); };
    $("#lit-st").onchange = (ev) => { S.litFilter.status = ev.target.value; renderLiterature(); };
  }

  function renderAgents() {
    const el = $("#view-agents");
    const st = S.state;
    const agents = st?.agents || [];
    el.innerHTML = `
      <div class="page-head">
        <div><h1>Bring Your Own Agents</h1><div class="sub">Model-agnostic collaboration protocol — any CLI, IDE, or local agent can participate</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h2>Participating Agents (${agents.length})</h2>
          ${agents.length ? `<div style="display:flex;flex-wrap:wrap;gap:8px">${agents.map((a, i) => whoBadge(a, String(i % 4))).join("")}</div>` : `<div class="empty">No agent turns recorded yet. Any agent can append a turn to <code class="mono">${esc(st?.config?.agents?.dialogue_dir)}</code>.</div>`}
        </div>
        <div class="card">
          <h2>How Any Agent Joins</h2>
          <p style="font-size:14px;color:var(--muted)">Point any coding or writing agent to your repository's <code class="mono">AGENTS.md</code> and <code class="mono">docs/AGENT_MANUAL.md</code>. Agents append turns using:</p>
          <pre class="mono" style="background:var(--surface-2);padding:12px;border-radius:8px;overflow:auto">## Turn N — &lt;Agent Name&gt; (&lt;Model&gt;) — YYYY-MM-DD

**Q1 — Topic**
- **Verdict:** \`AGREE\` | \`PARTIALLY AGREE\` | \`DISAGREE\`
- **Evidence:** file, section, citation key</pre>
        </div>
      </div>`;
  }

  function renderConfig() {
    const el = $("#view-config");
    const cfg = S.state?.config;
    el.innerHTML = `
      <div class="page-head">
        <div><h1>Workspace Configuration</h1><div class="sub">Loaded live from <code class="mono">thesis.toml</code> (or auto-detected) · Host shell: <span class="mono">${esc(S.state?.host_shell)}</span></div></div>
      </div>
      <div class="card">
        <h2>Resolved Adapters</h2>
        <pre class="mono" style="background:var(--surface-2);padding:14px;border-radius:8px;overflow:auto">${esc(JSON.stringify(cfg, null, 2))}</pre>
      </div>`;
  }

  async function refreshState() {
    S.state = await api("api/state");
    if (window.plat && window.plat.setBrand && S.state?.config?.project?.title) {
      window.plat.setBrand(S.state.config.project.title);
    }
    syncPalette();
  }

  async function route() {
    if (!S.state) await refreshState();
    const { view, param, params } = currentRoute();
    const valid = ["overview", "manuscript", "decisions", "quality", "literature", "agents", "config"];
    const target = valid.includes(view) ? view : "overview";

    document.querySelectorAll(".view").forEach((s) => { s.hidden = s.id !== `view-${target}`; });
    syncSubNav(target);

    if (target === "overview") renderOverview();
    else if (target === "manuscript") await renderManuscript(param);
    else if (target === "decisions") renderDecisions();
    else if (target === "quality") await renderQuality();
    else if (target === "literature") await renderLiterature(params);
    else if (target === "agents") renderAgents();
    else if (target === "config") renderConfig();
  }

  window.addEventListener("hashchange", route);
  route().catch((err) => {
    $("#view-overview").hidden = false;
    $("#view-overview").innerHTML = `<div class="card"><h2>Error</h2><p>${esc(err.message)}</p></div>`;
  });
})();
