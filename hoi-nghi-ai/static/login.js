/* Trang đăng nhập / đăng ký */
const msg = document.getElementById("auth-message");

function showMessage(text, isError) {
  msg.textContent = text;
  msg.className = "toast" + (isError ? " error" : "");
}

document.getElementById("tab-login").addEventListener("click", () => {
  document.getElementById("form-login").classList.remove("hidden");
  document.getElementById("form-register").classList.add("hidden");
  document.getElementById("tab-login").classList.add("active");
  document.getElementById("tab-register").classList.remove("active");
});

document.getElementById("tab-register").addEventListener("click", () => {
  document.getElementById("form-register").classList.remove("hidden");
  document.getElementById("form-login").classList.add("hidden");
  document.getElementById("tab-register").classList.add("active");
  document.getElementById("tab-login").classList.remove("active");
});

document.getElementById("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = new URLSearchParams(new FormData(e.target));
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Đăng nhập thất bại");
    localStorage.setItem("token", data.access_token);
    location.href = "/";
  } catch (err) {
    showMessage(err.message, true);
  }
});

document.getElementById("form-register").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Đăng ký thất bại");
    showMessage("Đăng ký thành công. Bạn có thể đăng nhập ngay.");
    localStorage.setItem("token", data.access_token);
    setTimeout(() => { location.href = "/"; }, 800);
  } catch (err) {
    showMessage(err.message, true);
  }
});
