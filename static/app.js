// Upajna web and phone app (Calm workspace design).
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (iso) => { if (!iso) return ""; const d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso); return isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); };
const ago = (iso) => { if (!iso) return ""; const m = (Date.now() - new Date(iso)) / 60000; if (isNaN(m)) return ""; if (m < 60) return Math.max(1, Math.round(m)) + "m ago"; if (m < 1440) return Math.round(m / 60) + "h ago"; return Math.round(m / 1440) + "d ago"; };
const todayISO = () => new Date().toISOString().slice(0, 10);
const TRACK = ["Applied", "Interview", "Offer", "Rejected"];
const AUTO = ["greenhouse", "lever", "ashby"];
const PF = ["name", "email", "phone", "location", "linkedin", "portfolio", "auth", "sponsor", "salary", "start", "relocate", "workpref", "years", "eeo", "answers"];

const S = { jobs: [], settings: { profile: {}, search: {} }, roles: [], status: {}, sel: new Set(), open: new Set(),
  sort: "score", filters: new Set(), roleF: "", openId: null, tf: "All", rtab: "resume",
  ticked: new Set() };  // missing-keyword chips you've tapped (a vague label like "certification" maps to the exact name you typed)
const roleById = (id) => S.roles.find((r) => r.id === id);
const roleName = (id) => roleById(id)?.name || "";
const roleTag = (j) => (S.roles.length > 1 && roleName(j.role) ? `<span class="rtag">${esc(roleName(j.role))}</span>` : "");

let tt; function toast(m) { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(tt); tt = setTimeout(() => (t.hidden = true), 3000); }

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const r = await fetch("/api" + path, init);
  if (r.status === 401 && path !== "/login") { showLogin(); throw new Error("Please sign in."); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || "Something went wrong. Try again."); e.status = r.status; e.data = data; throw e; }
  return data;
}

/* ---------- sign in ---------- */
function showLogin() { $("#app").hidden = true; $("#login").hidden = false; }
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault(); $("#loginErr").hidden = true;
  try { await api("/login", { method: "POST", body: { password: $("#pw").value } }); $("#pw").value = ""; start(); }
  catch (err) { $("#loginErr").textContent = err.message; $("#loginErr").hidden = false; }
});
$("#logout").addEventListener("click", async () => { await api("/logout", { method: "POST" }).catch(() => {}); showLogin(); });

/* ---------- navigation ---------- */
function show(v) {
  $$(".tab").forEach((t) => t.setAttribute("aria-selected", t.dataset.view === v ? "true" : "false"));
  ["inbox", "review", "tracker", "profile"].forEach((x) => ($("#view-" + x).hidden = x !== v));
  history.replaceState(null, "", "#" + v); window.scrollTo({ top: 0 });
}
$$(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
// Links like /#review (and the Back button) switch tabs without reloading the page.
window.addEventListener("hashchange", () => {
  if (location.hash.startsWith("#add=")) return takeIncomingLink();
  const v = location.hash.slice(1); if (["inbox", "review", "tracker", "profile"].includes(v)) show(v);
});

/* ---------- data loading ---------- */
async function refresh() {
  const [jobs, status] = await Promise.all([api("/jobs"), api("/status")]);
  S.jobs = jobs; S.status = status;
  render();
}
let pollTimer;
function schedulePoll() {
  clearTimeout(pollTimer);
  const busy = S.status.searching || S.jobs.some((j) => ["tailoring", "ready", "applying"].includes(j.status));
  pollTimer = setTimeout(async () => { if (document.visibilityState === "visible") await refresh().catch(() => {}); schedulePoll(); }, busy ? 4000 : 30000);
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh().catch(() => {}); });

/* ---------- top bar ---------- */
function nextSearchText() {
  // Reads the hour list from a cron schedule like "0 11,15,19 * * *".
  const hours = String(S.status.schedule || "").split(" ")[1]?.split(",").map(Number).filter((n) => !isNaN(n)) || [];
  if (!hours.length) return "";
  const now = new Date(); const h = hours.find((x) => x > now.getHours()) ?? hours[0];
  const d = new Date(); d.setHours(h, 0, 0, 0);
  return "Next search " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function renderTopbar() {
  const name = S.settings.profile.name || "";
  $("#avatar").textContent = name.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "U";
  $("#nextSearch").textContent = S.status.searching ? "Searching now…" : nextSearchText();
}

/* ---------- inbox ---------- */
function renderInbox() {
  let list = S.jobs.filter((j) => j.status === "new" || j.status === "tailoring");
  if (S.filters.has("remote")) list = list.filter((j) => j.remote || /remote/i.test(j.location || ""));
  if (S.filters.has("auto")) list = list.filter((j) => AUTO.includes(j.ats));
  if (S.roleF) list = list.filter((j) => j.role === S.roleF);
  renderRolePills();
  list.sort(S.sort === "score" ? (a, b) => (b.fit?.score || 0) - (a.fit?.score || 0) : (a, b) => String(b.foundAt || "").localeCompare(a.foundAt || ""));
  const nNew = S.jobs.filter((j) => j.status === "new").length;
  $("#cInbox").textContent = nNew; $("#cInbox").classList.toggle("hot", nNew > 0);
  const box = $("#inboxList");
  box.innerHTML = !list.length
    ? `<div class="empty"><strong>No new jobs right now</strong><span>New matches arrive after each search. Use Search now to run one.</span></div>`
    : `<div class="tr th" role="row"><span role="columnheader"></span><span role="columnheader">Role</span><span role="columnheader">Location</span><span role="columnheader">Pay</span><span role="columnheader">Source</span><span role="columnheader" style="text-align:right">Match</span></div>` +
      list.map((j) => {
        const loc = (j.location || "") + (j.remote && !/remote/i.test(j.location || "") ? " · Remote" : "");
        const open = S.open.has(j.id);
        return `<div class="tr ${S.sel.has(j.id) ? "sel" : ""}" role="row" data-id="${esc(j.id)}">
          <span role="cell">${j.status === "tailoring" ? `<span class="spin" aria-label="Tailoring"></span>` : `<input type="checkbox" aria-label="Select ${esc(j.title)}" ${S.sel.has(j.id) ? "checked" : ""}>`}</span>
          <span role="cell" class="cell-role">
            <button type="button" class="role-toggle" aria-expanded="${open}" data-toggle><span class="t">${esc(j.title)}</span></button>
            <span class="s">${roleTag(j)}${esc(j.company)}${j.jobType ? " · " + esc(j.jobType) : ""} · ${esc(ago(j.postedAt || j.foundAt))}${AUTO.includes(j.ats) ? " · auto-apply" : j.applyVia === "easy_apply" ? " · Easy Apply" : ""}</span>
            ${j.status === "tailoring" ? `<span class="why">Tailoring your resume…</span>` : j.fit?.reason ? `<span class="why">${esc(j.fit.reason)}</span>` : ""}
            ${j.error ? `<span class="err">${esc(j.error)}</span>` : ""}
            <span class="s phone-only">${[loc, j.salary, j.source].filter(Boolean).map(esc).join(" · ")}</span>
          </span>
          <span role="cell" class="cell">${esc(loc)}</span>
          <span role="cell" class="cell">${esc(j.salary || "—")}</span>
          <span role="cell" class="cell"><span class="src">${esc(j.source || "Web")}</span></span>
          <span role="cell" class="score-cell">${esc(j.fit?.score ?? "–")}</span>
          ${open ? `<div class="jd-row">${esc(j.jd || "No description saved.")}${j.url ? `\n\n<a href="${esc(j.url)}" target="_blank" rel="noopener">Open the posting ↗</a>` : ""}</div>` : ""}
        </div>`;
      }).join("");
  $$(".tr[data-id]", box).forEach((el) => {
    const id = el.dataset.id;
    $("input", el)?.addEventListener("change", (e) => { e.target.checked ? S.sel.add(id) : S.sel.delete(id); el.classList.toggle("sel", e.target.checked); renderSel(); });
    $("[data-toggle]", el).addEventListener("click", () => { S.open.has(id) ? S.open.delete(id) : S.open.add(id); renderInbox(); });
  });
  renderSel();
  const st = S.status.searchState || {};
  $("#lastRun").innerHTML = S.status.searching ? `<span class="spin"></span> Searching now…`
    : st.lastRunAt ? `${st.lastRunFound ?? 0} new from the search ${esc(ago(st.lastRunAt))}` : "Searches run at 11am, 3pm and 7pm";
  $("#searchNow").disabled = !!S.status.searching;
  const miss = S.status.missing || [];
  const noResume = !S.roles.some((r) => r.ready);
  $("#configNote").hidden = !miss.length && !noResume;
  $("#configNote").textContent = miss.length ? `Server setup incomplete. Add these in your host's environment variables: ${miss.join(", ")}.` : "Add a resume for at least one role in Settings to start searching.";
}
function renderRolePills() {
  const box = $("#rolePills"), ready = S.roles.filter((r) => r.ready);
  if (ready.length < 2) { box.innerHTML = ""; S.roleF = ""; return; }
  box.innerHTML = `<span class="pill-sep" aria-hidden="true"></span>` + [{ id: "", name: "All roles" }, ...ready]
    .map((r) => `<button type="button" class="pill-btn" data-role="${esc(r.id)}" aria-pressed="${S.roleF === r.id}">${esc(r.name)}</button>`).join("");
  $$("[data-role]", box).forEach((b) => b.addEventListener("click", () => { S.roleF = b.dataset.role; renderInbox(); }));
}
function renderSel() {
  S.sel = new Set([...S.sel].filter((id) => S.jobs.some((j) => j.id === id && j.status === "new")));
  $("#selBar").hidden = !S.sel.size;
  $("#selText").textContent = `${S.sel.size} selected`;
}
$$("#sortSeg [data-s]").forEach((b) => b.addEventListener("click", () => { S.sort = b.dataset.s; $$("#sortSeg [data-s]").forEach((x) => x.setAttribute("aria-pressed", x === b)); renderInbox(); }));
$$("#sortSeg [data-f]").forEach((b) => b.addEventListener("click", () => { const f = b.dataset.f; S.filters.has(f) ? S.filters.delete(f) : S.filters.add(f); b.setAttribute("aria-pressed", S.filters.has(f)); renderInbox(); }));
async function skip(ids) {
  try { await api("/jobs/skip", { method: "POST", body: { ids } }); ids.forEach((i) => S.sel.delete(i)); toast(ids.length > 1 ? `Skipped ${ids.length} jobs` : "Skipped"); await refresh(); } catch (e) { toast(e.message); }
}
$("#skipSel").addEventListener("click", () => skip([...S.sel]));
$("#applySel").addEventListener("click", async () => {
  const ids = [...S.sel];
  try { await api("/jobs/tailor", { method: "POST", body: { ids } }); S.sel.clear(); toast(`Tailoring ${ids.length} job${ids.length > 1 ? "s" : ""}. They'll appear in Review.`); await refresh(); schedulePoll(); }
  catch (e) { toast(e.message); }
});
$("#searchNow").addEventListener("click", async () => {
  try { await api("/search/run", { method: "POST" }); toast("Searching now. New jobs appear in a minute or two."); await refresh(); schedulePoll(); } catch (e) { toast(e.message); }
});
/* Add a job by link. The server reads the link; if it can't, it asks for the description. */
let forceAdd = false;
function resetAdd() { forceAdd = false; $("#addMsg").hidden = true; $("#addPaste").hidden = true; $("#addJd").value = ""; }
$("#addUrl").addEventListener("input", () => { if (!$("#addPaste").hidden || forceAdd) resetAdd(); });
$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("#addUrl").value.trim(), jd = $("#addJd").value.trim();
  if (!url && !jd) return toast("Paste a job link first");
  const btn = $("#addJob"); btn.disabled = true; btn.textContent = "Reading…";
  try {
    const j = await api("/jobs", { method: "POST", body: { url, jd, role: $("#addRoleSel").value, force: forceAdd } });
    $("#addUrl").value = ""; resetAdd();
    if (j.duplicate) toast(`Already in Upajna: ${j.title}${j.company ? " at " + j.company : ""}`);
    else toast(`Added ${j.title}${j.company ? " at " + j.company : ""}. Tailoring from your ${roleName(j.role) || "master"} resume.` + (j.applyVia === "easy_apply" ? " It's Easy Apply, so you'll do the last step on LinkedIn." : ""));
    await refresh(); schedulePoll();
  } catch (err) {
    const m = $("#addMsg");
    if (err.data?.needsText) { m.textContent = err.message; m.hidden = false; $("#addPaste").hidden = false; $("#addJd").focus(); }
    else if (err.data?.blocked) { m.innerHTML = `${esc(err.message)} <button type="button" class="linkish" id="addAnyway">Add it anyway</button>`; m.hidden = false;
      $("#addAnyway").addEventListener("click", () => { forceAdd = true; $("#addForm").requestSubmit(); }); }
    else toast(err.message);
  } finally { btn.disabled = false; btn.textContent = "Add job"; }
});
// Jobs sent from the bookmark button (/#add=<link>) or Android's Share menu (/?url=…&text=…).
function takeIncomingLink() {
  const q = new URLSearchParams(location.search), h = location.hash.startsWith("#add=") ? decodeURIComponent(location.hash.slice(5)) : "";
  const shared = h || q.get("url") || q.get("text") || "";
  if (!shared) return false;
  history.replaceState(null, "", "/#inbox");
  show("inbox"); $("#addUrl").value = shared; $("#addForm").requestSubmit();
  return true;
}
function setupBookmarklet() {
  const code = `javascript:(()=>{window.open(${JSON.stringify(location.origin + "/#add=")}+encodeURIComponent(location.href),"_blank")})()`;
  $("#bookmarklet").setAttribute("href", code);
  $("#bookmarklet").addEventListener("click", (e) => { e.preventDefault(); toast("Drag this button to your bookmarks bar, then click it on a job page."); });
}

/* ---------- review: list | resume | decision rail ---------- */
function renderReview() {
  const list = S.jobs.filter((j) => j.status === "review").sort((a, b) => String(b.tailoredAt || "").localeCompare(a.tailoredAt || ""));
  const tailoring = S.jobs.filter((j) => j.status === "tailoring").length;
  $("#cReview").textContent = list.length; $("#cReview").classList.toggle("hot", list.length > 0);
  $("#tailoringNote").hidden = !tailoring;
  $("#tailoringNote").innerHTML = `<span class="spin"></span> Tailoring ${tailoring} job${tailoring > 1 ? "s" : ""}…`;
  if (S.openId && !list.some((j) => j.id === S.openId)) S.openId = null;
  if (!S.openId && list.length) S.openId = list[0].id;
  const box = $("#reviewList");
  $(".review").hidden = !list.length;
  if (!list.length) {
    $("#tailoringNote").insertAdjacentHTML("afterend", "");
    if (!$("#reviewEmpty")) $(".review").insertAdjacentHTML("beforebegin", `<div class="empty" id="reviewEmpty"><strong>Nothing to review</strong><span>Select jobs in your Inbox and choose Tailor and review.</span></div>`);
    $("#reviewEmpty").hidden = !!tailoring;
    return;
  }
  $("#reviewEmpty")?.remove();
  box.innerHTML = `<div class="head"><h2>To review</h2><span class="small faint">${list.length} job${list.length > 1 ? "s" : ""}</span></div>` +
    list.map((j) => `
    <button type="button" class="ritem" data-open="${esc(j.id)}" aria-current="${j.id === S.openId}">
      <span class="top"><span class="t">${esc(j.title)}</span><span class="n">${esc(j.fit?.score ?? "")}</span></span>
      <span class="s">${roleTag(j)}${esc(j.company)}${j.location ? " · " + esc(j.location) : ""}</span>
    </button>`).join("");
  $$("[data-open]", box).forEach((b) => b.addEventListener("click", () => { S.openId = b.dataset.open; S.rtab = "resume"; renderReview(); }));
  const editing = document.activeElement?.closest?.("#rBody");
  if (!editing) renderDetail(list.find((j) => j.id === S.openId));
}
function renderDetail(job) {
  const d = $("#reviewDetail"), rail = $("#reviewRail");
  if (!job) { d.innerHTML = ""; rail.innerHTML = ""; return; }
  const r = job.result || {}, fit = r.fit || {}, ats = r.ats || {};
  const answers = r.answers || [];
  const asks = answers.filter((a) => /^ASK ME/i.test(a.answer || "")).length;
  const auto = AUTO.includes(job.ats);
  const found = (r.keywords || []).filter((k) => k.found), missingKw = (r.keywords || []).filter((k) => !k.found);
  const meta = [job.company, job.location, job.jobType, job.salary].filter(Boolean).map(esc).join(" · ");

  d.innerHTML = `
    <div class="job-head">
      <span class="small faint">${esc(job.source || "")}${job.postedAt || job.foundAt ? " · posted " + esc(ago(job.postedAt || job.foundAt)) : ""}</span>
      <h1>${esc(job.title)}</h1>
      <span class="meta">${meta}</span>
    </div>
    <div class="subtabs" role="tablist" aria-label="Application parts">
      <button type="button" class="subtab" role="tab" data-t="resume">Resume</button>
      ${r.coverLetter ? `<button type="button" class="subtab" role="tab" data-t="letter">Cover letter</button>` : ""}
      <button type="button" class="subtab" role="tab" data-t="answers">Answers${asks ? ` (${asks} to fill)` : ""}</button>
      <button type="button" class="subtab" role="tab" data-t="changes">What changed</button>
    </div>
    <div id="rBody"></div>`;

  rail.innerHTML = `
    <div class="rail-block">
      <span class="small faint">Match</span>
      <div class="match"><b>${esc(fit.score ?? job.fit?.score ?? "–")}</b><span>${esc(fit.level ? fit.level + " fit" : "")}</span></div>
      ${fit.reason ? `<p class="small muted">${esc(fit.reason)}</p>` : ""}
    </div>
    ${S.roles.length > 1 ? `<div class="rail-block">
      <label class="small faint" for="roleSwitch">Tailored from your resume for</label>
      <select id="roleSwitch">${S.roles.map((x) => `<option value="${esc(x.id)}" ${x.id === job.role ? "selected" : ""}>${esc(x.name)}${x.ready ? "" : " (no resume yet)"}</option>`).join("")}</select>
    </div>` : ""}
    ${(r.keywords || []).length ? `<div class="rail-block">
      <span class="small faint">Keywords covered · ${found.length} of ${(r.keywords || []).length}${ats.score != null ? ` · ATS ${esc(ats.score)}%` : ""}</span>
      <div class="chips">${found.map((k) => `<span class="chip">${esc(k.term)}</span>`).join("")}${missingKw.map((k) => `<span class="chip miss">${esc(k.term)}</span>`).join("")}</div>
    </div>` : ""}
    ${(ats.missing || []).filter(Boolean).length ? `<div class="rail-block">
      <span class="small faint">Missing from your resume. Tap any you really have, then redo tailoring.</span>
      <div class="chips">${ats.missing.filter(Boolean).map((m) => isConfirmed(m)
        ? `<button type="button" class="chip on" data-unhave="${esc(m)}" title="Tap to remove">✓ ${esc(m)}</button>`
        : `<button type="button" class="chip" data-have="${esc(m)}">+ ${esc(m)}</button>`).join("")}</div>
      ${ats.missing.some(isConfirmed) ? `<button type="button" class="btn small primary" id="retailorAdded">Redo tailoring with ${ats.missing.filter(isConfirmed).length} added skill${ats.missing.filter(isConfirmed).length > 1 ? "s" : ""}</button>` : ""}
    </div>` : ""}
    <div class="rail-block">
      <span class="small faint">Answers ${asks ? "· " + asks + " need you" : "ready"}</span>
      <div class="answers-list">${answers.slice(0, 5).map((a) => /^ASK ME/i.test(a.answer || "")
        ? `<span class="ask">${esc(a.question)}: needs your answer</span>`
        : `<span>${esc(a.question)} · ${esc(String(a.answer).slice(0, 60))}</span>`).join("") || `<span class="faint">No questions found</span>`}</div>
      ${answers.length > 5 ? `<button type="button" class="linkish" data-goto="answers">See all ${answers.length} answers</button>` : ""}
    </div>
    <div class="rail-actions">
      <button class="btn primary big" id="approve">${auto && S.status.applySubmit ? "Approve and submit" : "Approve"}</button>
      <div class="row">
        <button class="btn" id="rSkip">Skip</button>
        <a class="btn" href="${esc(job.applyUrl || job.url || "#")}" target="_blank" rel="noopener">View posting</a>
      </div>
      <p class="rail-note">${auto
        ? (S.status.applySubmit ? "Approving fills in and submits this application on the server. If anything unexpected comes up, it stops and asks you." : "Test mode: approving fills in the form but doesn't submit it. You'll see a screenshot in Tracker.")
        : "This site needs your own sign-in, so approving moves it to Tracker with the resume and answers ready to copy."}
        <button type="button" class="linkish" id="retailor">Redo tailoring</button></p>
    </div>`;

  $$(".subtab", d).forEach((b) => b.addEventListener("click", () => { S.rtab = b.dataset.t; renderRBody(job); }));
  $$("[data-goto]", rail).forEach((b) => b.addEventListener("click", () => { S.rtab = b.dataset.goto; renderRBody(job); }));
  if (S.rtab === "letter" && !r.coverLetter) S.rtab = "resume";
  renderRBody(job);
  $("#approve").addEventListener("click", () => approve(job));
  $("#retailor").addEventListener("click", async () => { try { await api("/jobs/tailor", { method: "POST", body: { ids: [job.id] } }); toast("Tailoring again…"); await refresh(); schedulePoll(); } catch (e) { toast(e.message); } });
  $("#rSkip").addEventListener("click", () => skip([job.id]));
  $("#roleSwitch")?.addEventListener("change", async (e) => {
    try {
      await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "PATCH", body: { role: e.target.value } });
      await api("/jobs/tailor", { method: "POST", body: { ids: [job.id] } });
      toast(`Tailoring again from your ${roleName(e.target.value)} resume…`); await refresh(); schedulePoll();
    } catch (x) { toast(x.message); e.target.value = job.role; }
  });
  const retailor = async (msg) => { try { await api("/jobs/tailor", { method: "POST", body: { ids: [job.id] } }); toast(msg); await refresh(); schedulePoll(); } catch (e) { toast(e.message); } };
  $("#retailorAdded")?.addEventListener("click", () => retailor("Tailoring again with your added skills…"));
  $$("[data-have]", rail).forEach((b) => b.addEventListener("click", async () => {
    let skill = b.dataset.have;
    // A certification needs its exact name, or the resume would claim something vague.
    if (/certif/i.test(skill)) {
      const named = prompt(`Which certification do you hold? Type its exact name, e.g. "AWS Certified Data Engineer – Associate".`, "");
      if (!named || !named.trim()) return;
      skill = named.trim();
    }
    const names = [...new Set([...(S.settings.profile.confirmed || []), skill])];
    try { S.settings.profile = await api("/settings/profile", { method: "PUT", body: { confirmed: names } }); S.ticked.add(b.dataset.have.toLowerCase()); renderDetail(job); toast(`Added ${skill}. Choose "Redo tailoring with added skills" when you're done.`); } catch (e) { toast(e.message); }
  }));
  $$("[data-unhave]", rail).forEach((b) => b.addEventListener("click", async () => {
    const drop = b.dataset.unhave.toLowerCase();
    const names = (S.settings.profile.confirmed || []).filter((c) => c.toLowerCase() !== drop);
    S.ticked.delete(drop);
    try { S.settings.profile = await api("/settings/profile", { method: "PUT", body: { confirmed: names } }); renderDetail(job); toast("Removed " + b.dataset.unhave); } catch (e) { toast(e.message); }
  }));
}
function isConfirmed(term) {
  const t = String(term).toLowerCase();
  return S.ticked.has(t) || (S.settings.profile.confirmed || []).some((c) => c.toLowerCase() === t);
}
function resumeHTML(R) {
  const sec = (t, inner) => (inner ? `<div class="rs">${esc(t)}</div>${inner}` : "");
  return `<article class="paper"><div class="rn">${esc(R.name || S.settings.profile.name || "")}</div>${R.headline ? `<div class="rh">${esc(R.headline)}</div>` : ""}
    <div class="rc">${(R.contact || []).filter(Boolean).map(esc).join(" · ")}</div>
    ${sec("Summary", R.summary ? `<p>${esc(R.summary)}</p>` : "")}
    ${sec("Skills", (R.skills || []).map((g) => `<div><strong>${esc(g.group)}:</strong> ${esc((g.items || []).join(", "))}</div>`).join(""))}
    ${sec("Experience", (R.experience || []).map((j) => `<div class="pj"><div class="jt"><span>${esc(j.title)} · ${esc(j.company)}${j.location ? ", " + esc(j.location) : ""}</span><span class="jdt">${esc(j.dates)}</span></div><ul>${(j.bullets || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join(""))}
    ${sec("Education", (R.education || []).map((e) => `<div class="pj"><div class="jt"><span>${esc(e.degree)} · ${esc(e.school)}</span><span class="jdt">${esc(e.dates)}</span></div>${e.details ? `<div>${esc(e.details)}</div>` : ""}</div>`).join(""))}
    ${(R.extra || []).map((x) => sec(x.heading, `<ul>${(x.items || []).map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`)).join("")}</article>`;
}
function renderRBody(job) {
  const r = job.result || {}, b = $("#rBody");
  $$(".subtab").forEach((x) => x.setAttribute("aria-selected", x.dataset.t === S.rtab));
  if (S.rtab === "resume") {
    b.innerHTML = `<div class="stack"><div class="row"><a class="btn small" href="/api/jobs/${encodeURIComponent(job.id)}/resume.docx">Download Word</a></div>${resumeHTML(r.resume || {})}</div>`;
  } else if (S.rtab === "answers") {
    const ans = r.answers || [];
    b.innerHTML = `<div class="stack"><p class="small faint">Edit anything. These exact answers go on the form.</p>` + ans.map((a, i) => `
      <div class="qa ${/^ASK ME/i.test(a.answer || "") ? "ask" : ""}"><label class="q" for="ans-${i}">${esc(a.question)}</label><textarea id="ans-${i}" data-i="${i}">${esc(a.answer)}</textarea></div>`).join("") +
      `<div class="row"><button class="btn primary" id="saveAns">Save answers</button></div></div>`;
    $("#saveAns").addEventListener("click", async () => { try { await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "PATCH", body: { answers: readAnswers(job) } }); toast("Answers saved"); await refresh(); } catch (e) { toast(e.message); } });
  } else if (S.rtab === "letter") {
    b.innerHTML = `<div class="stack"><div class="row"><a class="btn small" href="/api/jobs/${encodeURIComponent(job.id)}/cover.docx">Download Word</a></div><textarea id="letterBox" class="tall">${esc(r.coverLetter)}</textarea><div class="row"><button class="btn primary" id="saveLetter">Save cover letter</button></div></div>`;
    $("#saveLetter").addEventListener("click", async () => { try { await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "PATCH", body: { coverLetter: $("#letterBox").value.trim() } }); toast("Cover letter saved"); await refresh(); } catch (e) { toast(e.message); } });
  } else {
    const fit = r.fit || {};
    b.innerHTML = `<div class="stack">
      <div class="card"><h3>What changed in your resume</h3><ul style="margin:0;padding-left:18px">${(r.changes || []).map((c) => `<li>${esc(c)}</li>`).join("") || "<li class='faint'>No notes</li>"}</ul></div>
      <div class="card"><h3>Leads with</h3><ul style="margin:0;padding-left:18px">${(fit.strengths || []).map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='faint'>—</li>"}</ul>
        <h3>Gaps</h3><ul style="margin:0;padding-left:18px">${(fit.gaps || []).map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='faint'>None found</li>"}</ul></div></div>`;
  }
}
function readAnswers(job) {
  const boxes = $$("#rBody [data-i]");
  return (job.result?.answers || []).map((a, i) => ({ question: a.question, answer: (boxes[i]?.value ?? a.answer).trim() }));
}
async function approve(job) {
  const body = {};
  if ($$("#rBody [data-i]").length) body.answers = readAnswers(job);
  if ($("#letterBox")) body.coverLetter = $("#letterBox").value.trim();
  const answers = body.answers || job.result?.answers || [];
  if (answers.some((a) => /^ASK ME/i.test(a.answer || ""))) { S.rtab = "answers"; renderRBody(job); toast("Fill in the answers marked ASK ME first"); return; }
  try {
    const r = await api(`/jobs/${encodeURIComponent(job.id)}/approve`, { method: "POST", body });
    const auto = AUTO.includes(r.ats);
    toast(auto ? (r.willSubmit ? "Approved. Submitting now." : "Approved. Filling the form (test mode).") : "Approved. It's in Tracker, ready for you to submit.");
    await refresh(); schedulePoll();
  } catch (e) { toast(e.message); }
}

/* ---------- tracker ---------- */
function statusPill(j) {
  if (j.status === "ready") return `<span class="status info">Queued</span>`;
  if (j.status === "applying") return `<span class="status info"><span class="spin"></span> Submitting</span>`;
  if (j.status === "needs_you") return `<span class="status warn">Needs you</span>`;
  if (j.status === "closed") return `<span class="status">Closed</span>`;
  const t = j.trackerStatus || "Applied";
  return `<span class="status ${t === "Interview" || t === "Offer" ? "good" : t === "Rejected" ? "bad" : ""}">${esc(t)}</span>`;
}
function renderTracker() {
  const inflight = S.jobs.filter((j) => ["ready", "applying", "needs_you"].includes(j.status));
  const done = S.jobs.filter((j) => j.status === "submitted" || j.status === "closed");
  const all = [...inflight, ...done];
  const needs = S.jobs.filter((j) => j.status === "needs_you").length;
  $("#cTracker").textContent = all.length; $("#cTracker").classList.toggle("hot", needs > 0);
  const sub = done.filter((j) => j.status === "submitted");
  const cnt = (s) => sub.filter((j) => (j.trackerStatus || "Applied") === s).length;
  const responded = cnt("Interview") + cnt("Offer") + cnt("Rejected");
  $("#stats").innerHTML = [
    ["Applied", sub.length, ""], ["Interviews", cnt("Interview") + cnt("Offer"), "accent"], ["Needs you", needs, needs ? "warn" : ""],
    ["Response rate", sub.length ? Math.round((responded / sub.length) * 100) + "%" : "—", ""],
  ].map(([k, v, c]) => `<div class="stat"><span>${k}</span><b class="${c}">${v}</b></div>`).join("");
  const today = todayISO();
  const F = ["All", "Needs you", "Submitting", "Follow up due", ...TRACK];
  $("#trackSeg").innerHTML = F.map((f) => `<button type="button" class="pill-btn" data-f="${f}" aria-pressed="${S.tf === f}">${f}</button>`).join("");
  $$("#trackSeg button").forEach((b) => b.addEventListener("click", () => { S.tf = b.dataset.f; renderTracker(); }));
  const due = (j) => j.status === "submitted" && (j.trackerStatus || "Applied") === "Applied" && j.followUp && j.followUp <= today;
  const match = (j) => S.tf === "All" || (S.tf === "Needs you" && j.status === "needs_you") || (S.tf === "Submitting" && ["ready", "applying"].includes(j.status))
    || (S.tf === "Follow up due" && due(j)) || (j.status === "submitted" && (j.trackerStatus || "Applied") === S.tf);
  const list = all.filter(match).sort((a, b) => String(b.appliedAt || b.approvedAt || "").localeCompare(a.appliedAt || a.approvedAt || ""));
  const box = $("#trackList");
  if (!list.length) { box.innerHTML = `<div class="empty">${all.length ? "Nothing here." : "Applications you approve show up here with their status and follow-up dates."}</div>`; return; }
  box.innerHTML = `<div class="tr th" role="row"><span role="columnheader">Role</span><span role="columnheader">Applied</span><span role="columnheader">Status</span><span role="columnheader">Next step</span><span role="columnheader"></span></div>` +
    list.map((j) => {
      const next = j.status === "needs_you" ? (j.note || "Open the application to finish it")
        : j.status === "submitted" && (j.trackerStatus || "Applied") === "Applied" && j.followUp ? (due(j) ? "Follow up now" : "Follow up " + fmtDate(j.followUp))
        : j.status === "applying" || j.status === "ready" ? "Filling in the form" : j.note || "—";
      return `<div class="tr" role="row" data-id="${esc(j.id)}">
        <span role="cell" class="cell-role"><span class="t">${esc(j.title)}</span><span class="s">${esc(j.company)}${j.source ? " · " + esc(j.source) : ""}</span></span>
        <span role="cell" class="cell ${j.appliedAt ? "" : "blank"}">${j.appliedAt ? `<span class="phone-inline">Applied </span>` + esc(fmtDate(j.appliedAt)) : "—"}</span>
        <span role="cell" class="cell cell-status">${statusPill(j)}</span>
        <span role="cell" class="cell ${next === "—" && !j.hasShot ? "blank" : ""}" ${due(j) ? 'style="color:var(--warn);font-weight:500"' : ""}>${esc(next)}${j.hasShot ? ` <button type="button" class="linkish" data-shotbtn>Screenshot</button>` : ""}</span>
        <span role="cell" class="cell-actions">
          ${j.status === "submitted" ? `<select aria-label="Status for ${esc(j.title)}" data-ts>${TRACK.map((s) => `<option ${s === (j.trackerStatus || "Applied") ? "selected" : ""}>${s}</option>`).join("")}</select>` : ""}
          ${j.status === "needs_you" ? `<a class="btn small primary" href="${esc(j.applyUrl || j.url || "#")}" target="_blank" rel="noopener">Open</a><button class="btn small" data-mine>I submitted it</button>${AUTO.includes(j.ats) ? `<button class="btn small ghost" data-retry>Retry</button>` : ""}` : ""}
          ${j.result ? `<a class="btn small ghost" href="/api/jobs/${encodeURIComponent(j.id)}/resume.docx">Resume</a>` : ""}
        </span>
        <div class="jd-row" data-shot hidden><img class="shot" alt="Screenshot of the application form"></div>
      </div>`;
    }).join("");
  $$(".tr[data-id]", box).forEach((el) => {
    const id = el.dataset.id;
    $("[data-ts]", el)?.addEventListener("change", (e) => api(`/jobs/${encodeURIComponent(id)}`, { method: "PATCH", body: { trackerStatus: e.target.value } }).then(() => { toast("Moved to " + e.target.value); refresh(); }).catch((x) => toast(x.message)));
    $("[data-retry]", el)?.addEventListener("click", () => api(`/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }).then(() => { toast("Trying again"); refresh(); schedulePoll(); }).catch((x) => toast(x.message)));
    $("[data-mine]", el)?.addEventListener("click", () => api(`/jobs/${encodeURIComponent(id)}`, { method: "PATCH", body: { markSubmitted: true } }).then(() => { toast("Added to tracker"); refresh(); }).catch((x) => toast(x.message)));
    $("[data-shotbtn]", el)?.addEventListener("click", async () => {
      const row = $("[data-shot]", el), img = $("img", row);
      if (!img.src) { const j = await api(`/jobs/${encodeURIComponent(id)}`); img.src = j.shot || ""; }
      row.hidden = !row.hidden;
    });
  });
}

/* ---------- settings ---------- */
function fillForms() {
  const { profile, search } = S.settings;
  PF.forEach((f) => { const el = $("#p_" + f); if (el !== document.activeElement) el.value = profile[f] || ""; });
  if ($("#p_confirmed") !== document.activeElement) $("#p_confirmed").value = (profile.confirmed || []).join(", ");
  $("#s_level").value = search.level || "Mid-Senior";
  $("#s_sponsor").value = search.sponsorship || "needs";
  $$("#s_types input").forEach((i) => (i.checked = (search.jobTypes || ["Full-time"]).includes(i.value)));
  $("#s_excludes").value = search.excludes || "";
  $("#s_hours").value = search.postedWithinHours || 24;
  $("#s_max").value = search.maxPerRun || 20;
  renderRoles();
}
function renderAuto() {
  const st = S.status, ss = st.searchState || {};
  const src = [st.sources?.jsearch && "JSearch (LinkedIn, Indeed, ZipRecruiter, Glassdoor)", st.sources?.adzuna && "Adzuna"].filter(Boolean).join(" and ");
  $("#autoSearch").textContent = (src ? `Searching ${src}. ` : "No job API keys set yet. ") + (ss.lastRunAt ? `Last run ${ago(ss.lastRunAt)}: ${ss.lastRunFound ?? 0} new. ${ss.lastRunNote || ""}` : "");
  $("#applyMode").textContent = st.applySubmit ? "Submits after you approve" : "Test mode: fills forms, doesn't submit";
  $("#pushState").textContent = !st.push ? "Notifications aren't set up on the server yet." : notifPerm() === "granted" ? "Notifications are on for this device." : "";
  $("#enablePush").hidden = !st.push || notifPerm() === "granted";
}
$("#saveProfile").addEventListener("click", async () => {
  const body = {}; PF.forEach((f) => (body[f] = $("#p_" + f).value.trim()));
  body.confirmed = $("#p_confirmed").value.split(",").map((x) => x.trim()).filter(Boolean);
  try { S.settings.profile = await api("/settings/profile", { method: "PUT", body }); renderTopbar(); toast("Details saved"); } catch (e) { toast(e.message); }
});
$("#saveSearch").addEventListener("click", async () => {
  const body = { level: $("#s_level").value, sponsorship: $("#s_sponsor").value,
    jobTypes: $$("#s_types input:checked").map((i) => i.value), excludes: $("#s_excludes").value.trim(), postedWithinHours: +$("#s_hours").value || 24, maxPerRun: +$("#s_max").value || 20 };
  try { S.settings.search = await api("/settings/search", { method: "PUT", body }); toast("Search saved"); } catch (e) { toast(e.message); }
});
/* Roles and resumes: one card per role, each with titles and its own resume. */
function renderRoles() {
  const box = $("#roles");
  box.innerHTML = S.roles.map((r, i) => `
    <div class="role-card" data-i="${i}">
      <input type="text" class="role-name" aria-label="Role name" value="${esc(r.name)}" placeholder="Role name, e.g. Data Engineer">
      <div class="field"><label for="rt-${i}">Job titles to search</label><textarea id="rt-${i}" class="role-titles" rows="4">${esc((r.titles || []).join(", "))}</textarea><span class="hint">Separate with commas.</span></div>
      <div class="role-resume">
        <span class="small ${r.resume ? "muted" : "faint"}"><span class="status ${r.ready ? "good" : "warn"}">${r.ready ? "Searching" : "Needs a resume"}</span> ${r.resume ? `Resume${r.fileName ? ": " + esc(r.fileName) : " pasted"}${r.updatedAt ? " · saved " + esc(fmtDate(r.updatedAt)) : ""}` : "No resume yet"}</span>
        <div class="row">
          <label class="btn small" for="rf-${i}">${r.resume ? "Replace file" : "Upload resume"}</label><input type="file" id="rf-${i}" class="role-file" accept=".pdf,.docx,.txt" hidden>
          ${S.roles.length > 1 ? `<button type="button" class="linkish role-remove">Remove role</button>` : ""}
        </div>
      </div>
      <details class="role-text"><summary>Paste or edit resume text</summary><textarea class="tall role-resume-text" aria-label="Resume text for ${esc(r.name)}">${esc(r.resume || "")}</textarea></details>
    </div>`).join("");
  $$(".role-card", box).forEach((el) => {
    const i = +el.dataset.i;
    $(".role-remove", el)?.addEventListener("click", () => { readRoles(); S.roles.splice(i, 1); renderRoles(); toast("Removed. Choose Save roles to keep this change."); });
    $(".role-file", el).addEventListener("change", async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try {
        await saveRoles(true); // a new role needs an id before it can take a file
        toast("Reading " + f.name + "…");
        const fd = new FormData(); fd.append("file", f);
        await api(`/roles/${encodeURIComponent(S.roles[i].id)}/resume`, { method: "POST", body: fd });
        S.roles = await api("/roles"); renderRoles(); renderInbox(); toast("Resume saved for " + S.roles[i].name);
      } catch (err) { toast(err.message); }
      e.target.value = "";
    });
  });
  $("#addRole").hidden = S.roles.length >= 5;
  $("#addRoleSel").innerHTML = `<option value="">Pick automatically</option>` + S.roles.map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("");
}
function readRoles() {
  $$("#roles .role-card").forEach((el) => {
    const r = S.roles[+el.dataset.i];
    r.name = $(".role-name", el).value.trim();
    r.titles = $(".role-titles", el).value.split(",").map((x) => x.trim()).filter(Boolean);
    r.resume = $(".role-resume-text", el).value.trim();
  });
}
async function saveRoles(quiet) {
  readRoles();
  if (S.roles.some((r) => !r.name)) throw new Error("Give every role a name");
  S.roles = await api("/roles", { method: "PUT", body: S.roles.map(({ id, name, titles, resume }) => ({ id, name, titles, resume })) });
  renderRoles(); renderInbox();
  if (!quiet) toast("Roles saved");
}
$("#saveRoles").addEventListener("click", () => saveRoles().catch((e) => toast(e.message)));
$("#addRole").addEventListener("click", () => { readRoles(); S.roles.push({ id: "", name: "", titles: [], resume: "" }); renderRoles(); $$("#roles .role-name").at(-1).focus(); });

/* ---------- notifications ---------- */
function notifPerm() { return typeof Notification === "undefined" ? "unsupported" : Notification.permission; }
function b64ToUint8(b64) { const p = "=".repeat((4 - (b64.length % 4)) % 4); const s = atob((b64 + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from([...s].map((c) => c.charCodeAt(0))); }
$("#enablePush").addEventListener("click", async () => {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return toast("This browser can't show notifications. On iPhone, add Upajna to your Home Screen first.");
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return toast("Notifications weren't allowed.");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(S.status.vapidPublic) });
    await api("/push/subscribe", { method: "POST", body: sub.toJSON() });
    toast("Notifications are on"); renderAuto();
  } catch (e) { toast("Couldn't turn on notifications: " + e.message); }
});

/* ---------- boot ---------- */
function render() { renderTopbar(); renderInbox(); renderReview(); renderTracker(); renderAuto(); }
async function start() {
  try {
    [S.settings, S.roles] = await Promise.all([api("/settings"), api("/roles")]);
    $("#login").hidden = true; $("#app").hidden = false;
    fillForms(); await refresh(); schedulePoll();
    setupBookmarklet();
    if (!takeIncomingLink()) { const tab = location.hash.slice(1); if (["inbox", "review", "tracker", "profile"].includes(tab)) show(tab); }
  } catch (e) { console.error(e); /* a 401 already showed the sign-in screen */ }
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
start();
