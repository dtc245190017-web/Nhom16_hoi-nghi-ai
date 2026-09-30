/* Trang quản trị */
const token = localStorage.getItem("token") || "";

function h() { return { Authorization: "Bearer " + token }; }

async function get(path) {
  const res = await fetch(path, { headers: h() });
  if (!res.ok) throw new Error("Không tải được dữ liệu: " + path);
  return res.json();
}

function render(el, columns, rows) {
  if (!rows.length) { el.innerHTML = "<tr><td>Không có dữ liệu</td></tr>"; return; }
  el.innerHTML = "<tr>" + columns.map(c => `<th>${c.title}</th>`).join("") + "</tr>" +
    rows.map(r => "<tr>" + columns.map(c => `<td>${r[c.key] ?? ""}</td>`).join("") + "</tr>").join("");
}

(async function init() {
  if (!token) { location.href = "/login"; return; }
  try {
    render(document.getElementById("admin-user-list"),
      [{ title: "Họ tên", key: "full_name" }, { title: "Email", key: "email" },
       { title: "Vai trò", key: "role" }, { title: "Trạng thái", key: "status" },
       { title: "Số bài nộp", key: "paper_count" }],
      await get("/api/admin/users"));

    render(document.getElementById("admin-system-logs"),
      [{ title: "Mức", key: "level" }, { title: "Nguồn", key: "source" },
       { title: "Nội dung", key: "message" }, { title: "Thời điểm", key: "created_at" }],
      await get("/api/admin/system-logs"));

    render(document.getElementById("admin-ai-logs"),
      [{ title: "Loại", key: "kind" }, { title: "Bài báo", key: "paper_id" },
       { title: "Provider", key: "provider" }, { title: "Thời gian (ms)", key: "latency_ms" },
       { title: "Lỗi", key: "error_type" }, { title: "Thời điểm", key: "created_at" }],
      await get("/api/ai/logs"));
  } catch (err) {
    document.body.insertAdjacentHTML("afterbegin",
      `<div class="toast error">${err.message}</div>`);
  }
})();
