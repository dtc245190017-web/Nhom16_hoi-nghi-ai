/* Giao diện chính — gọi API hệ thống quản lý hội nghị khoa học */
const API = "";
let token = localStorage.getItem("token") || "";
let currentUser = null;
let currentPaperId = null;

function headers(json = true) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (token) h["Authorization"] = "Bearer " + token;
  return h;
}

async function api(path, options = {}) {
  const res = await fetch(API + path, options);
  if (res.status === 401) {
    localStorage.removeItem("token");
    location.href = "/login";
    return;
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (!res.ok) throw new Error((data && data.detail) || "Lỗi gọi API");
  return data;
}

function toast(message, isError = false) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.className = "toast" + (isError ? " error" : "");
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 5000);
}

function table(el, columns, rows, emptyText = "Không có dữ liệu") {
  if (!rows || !rows.length) { el.innerHTML = `<tr><td>${emptyText}</td></tr>`; return; }
  const head = "<tr>" + columns.map(c => `<th>${c.title}</th>`).join("") + "</tr>";
  const body = rows.map(r => "<tr>" + columns.map(c => `<td>${c.render ? c.render(r) : (r[c.key] ?? "")}</td>`).join("") + "</tr>").join("");
  el.innerHTML = head + body;
}

function money(n) { return n === null || n === undefined ? "—" : n; }

async function boot() {
  if (!token) { location.href = "/login"; return; }
  try {
    currentUser = await api("/api/auth/me", { headers: headers(false) });
  } catch (e) { location.href = "/login"; return; }
  document.getElementById("whoami").textContent = `${currentUser.full_name} (${currentUser.role})`;
  const isOrganizer = currentUser.role === "organizer";
  document.querySelectorAll('[data-view="reviewers"],[data-view="assignments"],[data-view="admin"]')
    .forEach(b => { if (!isOrganizer) b.classList.add("hidden"); });
  document.querySelector('[data-view="reviews"]').classList.toggle("hidden", currentUser.role !== "reviewer");
  document.querySelector('[data-view="papers"]').classList.toggle("hidden", currentUser.role === "reviewer");
  document.querySelector('[data-view="ai"]').classList.toggle("hidden", !isOrganizer);
  await show("dashboard");
}

async function show(view) {
  document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
  const target = document.getElementById("view-" + view);
  if (target) target.classList.remove("hidden");
  document.querySelectorAll(".nav").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  const loaders = {
    dashboard: loadDashboard, conferences: loadConferences, papers: loadPapers,
    reviewers: loadReviewers, assignments: loadAssignments, reviews: loadMyAssignments,
    sessions: loadSessions, registrations: loadRegistrations, ai: loadAi, admin: loadAdmin,
  };
  if (loaders[view]) {
    try { await loaders[view](); } catch (e) { toast(e.message, true); }
  }
}

/* ---------- Dashboard ---------- */
async function loadDashboard() {
  const s = await api("/api/stats/overview", { headers: headers(false) });
  document.getElementById("stats-cards").innerHTML = [
    ["Tổng bài nộp", s.total_papers],
    ["Tổng phân công", s.total_assignments],
    ["Đã hoàn thành", s.completed_assignments],
    ["Quá hạn", s.overdue_assignments],
    ["Tiến độ phản biện", s.review_progress_percent + "%"],
  ].map(([label, value]) => `<div class="card"><div class="value">${value}</div><div class="label">${label}</div></div>`).join("");

  table(document.getElementById("stats-status"),
    [{ title: "Trạng thái", key: "status" }, { title: "Số bài", key: "count" }],
    Object.entries(s.by_status).map(([status, count]) => ({ status, count })));

  table(document.getElementById("stats-field"),
    [{ title: "Lĩnh vực chuyên môn", key: "name" }, { title: "Số bài", key: "count" }],
    Object.entries(s.by_field).map(([name, count]) => ({ name, count })));

  table(document.getElementById("stats-overdue"),
    [{ title: "Bài báo", key: "paper_title" }, { title: "Phản biện", key: "reviewer_name" },
     { title: "Hạn", key: "due_date" }],
    s.overdue_list);
}

/* ---------- Hội nghị ---------- */
async function loadConferences() {
  const rows = await api("/api/conferences", { headers: headers(false) });
  table(document.getElementById("conference-list"),
    [{ title: "Tên hội nghị", key: "name" }, { title: "Năm", key: "year" },
     { title: "Hạn nộp", key: "submission_deadline" }, { title: "Hạn phản biện", key: "review_deadline" },
     { title: "Thông báo", key: "notification_date" }, { title: "Số bài", key: "paper_count" }],
    rows);
  const select = document.getElementById("paper-conference");
  select.innerHTML = rows.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  document.getElementById("session-conference").innerHTML = select.innerHTML;
  document.getElementById("reg-conference").innerHTML = select.innerHTML;
  await loadFields();
}

async function loadFields() {
  const fields = await api("/api/expertise-fields", { headers: headers(false) });
  document.getElementById("paper-topics").innerHTML =
    fields.map(f => `<option value="${f.id}">${f.name}</option>`).join("");
  document.getElementById("reviewer-fields").innerHTML =
    fields.map(f => `<option value="${f.id}">${f.name}</option>`).join("");
}

/* ---------- Bài báo ---------- */
async function loadPapers() {
  const q = document.getElementById("paper-q").value.trim();
  const status = document.getElementById("paper-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status_filter", status);
  const rows = await api("/api/papers?" + params.toString(), { headers: headers(false) });
  table(document.getElementById("paper-list"), [
    { title: "ID", key: "id" },
    { title: "Tiêu đề", key: "title" },
    { title: "Hội nghị", key: "conference_name" },
    { title: "Trạng thái", render: r => `<span class="badge">${r.status}</span>` },
    { title: "Từ khóa", render: r => r.keywords.join(", ") },
    { title: "Lĩnh vực", render: r => r.topics.map(t => t.name).join(", ") },
    { title: "Phản biện", key: "assignment_count" },
    { title: "Điểm TB", render: r => money(r.average_score) },
    { title: "Thao tác", render: r => `<button onclick="openAi(${r.id})">Chức năng AI</button>` },
  ], rows);
}

/* ---------- Phản biện ---------- */
async function loadReviewers() {
  const rows = await api("/api/reviewers", { headers: headers(false) });
  table(document.getElementById("reviewer-list"), [
    { title: "Họ tên", key: "full_name" }, { title: "Học vị", key: "degree" },
    { title: "Tổ chức", key: "organization" },
    { title: "Lĩnh vực chuyên môn", render: r => r.expertise.map(e => e.name).join(", ") || "chưa khai báo" },
    { title: "Đang phụ trách", render: r => `${r.current_load}/${r.max_load}` },
  ], rows);
  document.getElementById("reviewer-select").innerHTML =
    rows.map(r => `<option value="${r.id}">${r.full_name} — ${r.expertise.map(e => e.name).join(", ")}</option>`).join("");
  document.getElementById("assign-reviewer").innerHTML =
    rows.map(r => `<option value="${r.id}">${r.full_name} (${r.current_load}/${r.max_load})</option>`).join("");
}

/* ---------- Phân công ---------- */
async function loadAssignments() {
  const rows = await api("/api/assignments", { headers: headers(false) });
  table(document.getElementById("assignment-list"), [
    { title: "Bài báo", key: "paper_title" }, { title: "Phản biện", key: "reviewer_name" },
    { title: "Hạn", key: "due_date" },
    { title: "Trạng thái", render: r => `<span class="badge ${r.status}">${r.status}</span>` },
    { title: "Điểm", render: r => money(r.score) },
  ], rows);
  const papers = await api("/api/papers", { headers: headers(false) });
  document.getElementById("assign-paper").innerHTML =
    papers.map(p => `<option value="${p.id}">#${p.id} ${p.title}</option>`).join("");
}

/* ---------- Nhận xét của phản biện ---------- */
async function loadMyAssignments() {
  const rows = await api("/api/assignments", { headers: headers(false) });
  table(document.getElementById("my-assignment-list"), [
    { title: "Bài báo", key: "paper_title" }, { title: "Hạn", key: "due_date" },
    { title: "Trạng thái", render: r => `<span class="badge ${r.status}">${r.status}</span>` },
    { title: "Điểm đã gửi", render: r => money(r.score) },
  ], rows);
  document.getElementById("review-assignment").innerHTML =
    rows.map(r => `<option value="${r.id}">${r.paper_title}</option>`).join("");
}

/* ---------- Phiên & đăng ký ---------- */
async function loadSessions() {
  const rows = await api("/api/sessions", { headers: headers(false) });
  table(document.getElementById("session-list"), [
    { title: "Tên phiên", key: "title" }, { title: "Ngày", key: "session_date" },
    { title: "Phòng", key: "room" }, { title: "Chủ tọa", key: "chair" },
    { title: "Bài trong phiên", render: r => r.papers.map(p => p.title).join("; ") },
  ], rows);
  const papers = await api("/api/papers?status_filter=accepted", { headers: headers(false) });
  document.getElementById("session-papers").innerHTML =
    papers.map(p => `<option value="${p.id}">#${p.id} ${p.title}</option>`).join("");
}

async function loadRegistrations() {
  const rows = await api("/api/registrations", { headers: headers(false) });
  table(document.getElementById("registration-list"), [
    { title: "Hội nghị", key: "conference_name" }, { title: "Người đăng ký", key: "user_name" },
    { title: "Loại", key: "registration_type" }, { title: "Ghi chú", key: "note" },
  ], rows);
}

/* ---------- Nhật ký AI ---------- */
async function loadAi() {
  const logs = await api("/api/ai/logs", { headers: headers(false) });
  table(document.getElementById("ai-log-list"), [
    { title: "Loại", key: "kind" }, { title: "Bài báo", key: "paper_id" },
    { title: "Provider", key: "provider" }, { title: "Model", key: "model" },
    { title: "Thời gian (ms)", key: "latency_ms" },
    { title: "Kết quả", render: r => r.success ? '<span class="badge done">OK</span>' : `<span class="badge overdue">${r.error_type || "lỗi"}</span>` },
    { title: "Thời điểm", key: "created_at" },
  ], logs);

  const gens = await api("/api/ai/generations", { headers: headers(false) });
  table(document.getElementById("ai-generation-list"), [
    { title: "Loại", key: "kind" }, { title: "Bài báo", key: "paper_id" },
    { title: "Nguồn", render: r => r.source === "ai" ? "AI" : "Nội bộ (fallback)" },
    { title: "Cảnh báo thiên lệch", key: "bias_note" },
    { title: "Cập nhật", key: "updated_at" },
  ], gens);

  const drafts = await api("/api/email-drafts", { headers: headers(false) });
  table(document.getElementById("email-draft-list"), [
    { title: "Loại", key: "kind" }, { title: "Tiêu đề", key: "subject" },
    { title: "Trạng thái", key: "status" },
    { title: "Trường còn thiếu", key: "missing_fields" },
  ], drafts);
}

/* ---------- Quản trị ---------- */
async function loadAdmin() {
  const users = await api("/api/admin/users", { headers: headers(false) });
  table(document.getElementById("user-list"), [
    { title: "Họ tên", key: "full_name" }, { title: "Email", key: "email" },
    { title: "Vai trò", key: "role" }, { title: "Trạng thái", key: "status" },
    { title: "Số bài nộp", key: "paper_count" },
  ], users);
  const logs = await api("/api/admin/system-logs", { headers: headers(false) });
  table(document.getElementById("system-log-list"), [
    { title: "Mức", key: "level" }, { title: "Nguồn", key: "source" },
    { title: "Nội dung", key: "message" }, { title: "Thời điểm", key: "created_at" },
  ], logs);
}

/* ---------- Khu vực chức năng AI ---------- */
function openAi(paperId) {
  currentPaperId = paperId;
  document.getElementById("ai-panel").classList.remove("hidden");
  document.getElementById("ai-result").textContent = "";
  document.getElementById("ai-source").textContent = `Đang thao tác với bài báo #${paperId}`;
}

async function runAi(kind) {
  if (!currentPaperId) { toast("Chọn một bài báo trước", true); return; }
  const result = document.getElementById("ai-result");
  result.textContent = "Đang xử lý…";
  try {
    let data;
    if (kind === "summarize") {
      data = await api("/api/ai/summarize-paper", {
        method: "POST", headers: headers(), body: JSON.stringify({ paper_id: currentPaperId }),
      });
    } else if (kind === "suggest") {
      data = await api("/api/ai/suggest-reviewers", {
        method: "POST", headers: headers(), body: JSON.stringify({ paper_id: currentPaperId }),
      });
    } else {
      const emailKind = document.getElementById("ai-email-kind").value;
      data = await api(`/api/ai/email-draft?kind=${emailKind}`, {
        method: "POST", headers: headers(), body: JSON.stringify({ paper_id: currentPaperId }),
      });
    }
    document.getElementById("ai-source").textContent =
      `Nguồn: ${data.source === "ai" ? "AI Provider" : "Kết quả nội bộ (fallback)"}` +
      (data.fallback_notice ? " — " + data.fallback_notice : "");
    result.textContent = JSON.stringify(data.data, null, 2) + "\n\n" + (data.notice || "");
    toast("Đã lấy kết quả AI");
  } catch (e) {
    result.textContent = "";
    toast(e.message, true);
  }
}

/* ---------- Gắn sự kiện ---------- */
document.querySelectorAll(".nav").forEach(btn =>
  btn.addEventListener("click", () => show(btn.dataset.view)));

document.getElementById("btn-logout").addEventListener("click", () => {
  localStorage.removeItem("token");
  location.href = "/login";
});
document.getElementById("ai-close").addEventListener("click", () =>
  document.getElementById("ai-panel").classList.add("hidden"));
document.querySelectorAll("[data-ai]").forEach(btn =>
  btn.addEventListener("click", () => runAi(btn.dataset.ai)));
document.getElementById("btn-search-paper").addEventListener("click", loadPapers);

document.getElementById("form-conference").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = Object.fromEntries(f.entries());
  body.year = Number(body.year);
  ["camera_ready_deadline"].forEach(k => { if (!body[k]) delete body[k]; });
  try {
    await api("/api/conferences", { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã lưu hội nghị");
    e.target.reset();
    loadConferences();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-paper").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    conference_id: Number(f.get("conference_id")),
    title: f.get("title"),
    abstract: f.get("abstract"),
    keywords: (f.get("keywords") || "").split(",").map(s => s.trim()).filter(Boolean),
    topics: Array.from(document.getElementById("paper-topics").selectedOptions).map(o => Number(o.value)),
    authors: (f.get("authors") || "").split("\n").map(s => s.trim()).filter(Boolean),
  };
  try {
    await api("/api/papers", { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã nộp bài báo");
    e.target.reset();
    loadPapers();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-reviewer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    full_name: "x", email: "x@example.com",
    degree: f.get("degree"), organization: f.get("organization"),
    max_load: Number(f.get("max_load") || 5),
    expertise_ids: Array.from(document.getElementById("reviewer-fields").selectedOptions).map(o => Number(o.value)),
  };
  try {
    await api(`/api/reviewers/${f.get("profile_id")}`, { method: "PUT", headers: headers(), body: JSON.stringify(body) });
    toast("Đã cập nhật hồ sơ phản biện");
    loadReviewers();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-assignment").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    paper_id: Number(f.get("paper_id")),
    reviewer_profile_id: Number(f.get("reviewer_profile_id")),
    due_date: f.get("due_date"),
  };
  try {
    await api("/api/assignments", { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã phân công phản biện");
    loadAssignments();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-review").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    score: Number(f.get("score")),
    recommendation: f.get("recommendation"),
    comment: f.get("comment"),
    internal_note: f.get("internal_note") || "",
  };
  try {
    await api(`/api/assignments/${f.get("assignment_id")}/review`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã gửi nhận xét phản biện");
    e.target.reset();
    loadMyAssignments();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-session").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    conference_id: Number(f.get("conference_id")),
    title: f.get("title"),
    session_date: f.get("session_date") || null,
    room: f.get("room") || "",
    chair: f.get("chair") || "",
    paper_ids: Array.from(document.getElementById("session-papers").selectedOptions).map(o => Number(o.value)),
  };
  try {
    await api("/api/sessions", { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã tạo phiên trình bày");
    e.target.reset();
    loadSessions();
  } catch (err) { toast(err.message, true); }
});

document.getElementById("form-registration").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {
    conference_id: Number(f.get("conference_id")),
    registration_type: f.get("registration_type"),
    note: f.get("note") || "",
  };
  try {
    await api("/api/registrations", { method: "POST", headers: headers(), body: JSON.stringify(body) });
    toast("Đã đăng ký tham dự");
    e.target.reset();
    loadRegistrations();
  } catch (err) { toast(err.message, true); }
});

boot();
