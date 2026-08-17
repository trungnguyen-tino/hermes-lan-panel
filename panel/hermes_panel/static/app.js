/* Hermes Panel — core: API helper, đăng nhập, trạng thái dịch vụ. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  let toastTimer = null;
  function toast(message, kind) {
    const el = $("toast");
    el.textContent = message;
    el.className = "toast " + (kind || "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 4500);
  }

  /* Mọi phản hồi API đều là {ok, data, error}. 401 => quay về màn đăng nhập. */
  async function api(path, options) {
    const opts = options || {};
    const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(path, init);
    if (resp.status === 401) {
      showLogin();
      throw new Error("Phiên đăng nhập đã hết hạn.");
    }
    let payload = {};
    try {
      payload = await resp.json();
    } catch (err) {
      throw new Error("Máy chủ trả về dữ liệu không hợp lệ (HTTP " + resp.status + ").");
    }
    if (!resp.ok || payload.ok === false) {
      throw new Error(payload.error || "Lỗi HTTP " + resp.status);
    }
    return payload.data;
  }

  function showLogin() {
    $("app-screen").classList.add("hidden");
    $("login-screen").classList.remove("hidden");
    Panel.stopPolling();
  }

  function showApp() {
    $("login-screen").classList.add("hidden");
    $("app-screen").classList.remove("hidden");
    Panel.startPolling();
  }

  /* ─── Đăng nhập ─────────────────────────────────────────────── */
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const err = $("login-error");
    err.classList.add("hidden");
    try {
      await api("/api/login", {
        method: "POST",
        body: { username: $("login-user").value, password: $("login-pass").value },
      });
      $("login-pass").value = "";
      showApp();
    } catch (e) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
  });

  $("logout-btn").addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
    } catch (e) { /* đăng xuất luôn kể cả khi lỗi mạng */ }
    showLogin();
  });

  /* ─── Thông tin máy + dịch vụ ───────────────────────────────── */
  const STATE_LABEL = { active: "đang chạy", inactive: "đã dừng", failed: "lỗi" };

  function stateClass(state) {
    if (state === "active") return "ok";
    if (state === "failed") return "err";
    return "warn";
  }

  async function loadInfo() {
    const info = await api("/api/info");
    $("host-label").textContent = info.hostname + " · " + info.ip;
    $("hermes-version").textContent = "Hermes: " + info.hermes_version;
    $("chat-link").href = info.chat_url;
  }

  function renderHost(host) {
    const parts = [];
    if (host.memory && host.memory.total) {
      parts.push("RAM " + host.memory.percent + "%");
    }
    if (host.disk && host.disk.total) {
      parts.push("Ổ đĩa " + host.disk.percent + "%");
    }
    if (host.load_avg && host.load_avg.length) {
      parts.push("Tải " + host.load_avg[0].toFixed(2));
    }
    if (host.uptime_seconds) {
      parts.push("Uptime " + Math.floor(host.uptime_seconds / 3600) + "h");
    }
    $("host-stats").textContent = parts.join(" · ");
  }

  async function loadStatus() {
    const data = await api("/api/status");
    const box = $("services");
    box.innerHTML = "";
    data.services.forEach((svc) => {
      const row = document.createElement("div");
      row.className = "service";
      const label = document.createElement("div");
      label.innerHTML =
        '<span class="name">' + svc.name + '</span> ' +
        '<span class="badge ' + stateClass(svc.state) + '">' +
        (STATE_LABEL[svc.state] || svc.state) + "</span>";
      row.appendChild(label);
      if (svc.controllable) {
        const actions = document.createElement("div");
        actions.className = "row";
        actions.style.marginTop = "0";
        [["restart", "Khởi động lại"], ["stop", "Dừng"], ["start", "Chạy"]].forEach((pair) => {
          const btn = document.createElement("button");
          btn.className = "btn tiny";
          btn.textContent = pair[1];
          btn.addEventListener("click", () => serviceAction(svc.name, pair[0], btn));
          actions.appendChild(btn);
        });
        row.appendChild(actions);
      }
      box.appendChild(row);
    });
    renderHost(data.host || {});
  }

  async function serviceAction(service, action, button) {
    button.disabled = true;
    try {
      await api("/api/services/" + service + "/" + action, { method: "POST" });
      toast(service + ": đã " + (action === "restart" ? "khởi động lại" : action), "ok");
      setTimeout(loadStatus, 1500);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
    }
  }

  /* ─── Vòng lặp cập nhật ─────────────────────────────────────── */
  const tasks = [];       // các hàm refresh do features.js đăng ký
  let timer = null;

  const Panel = {
    $: $,
    api: api,
    toast: toast,
    showLogin: showLogin,
    register: (fn) => tasks.push(fn),
    refreshAll: async function () {
      const jobs = [loadStatus].concat(tasks);
      for (const job of jobs) {
        try {
          await job();
        } catch (e) {
          /* một mục lỗi không được chặn các mục còn lại */
        }
      }
    },
    startPolling: function () {
      if (timer) return;
      loadInfo().catch(() => {});
      Panel.refreshAll();
      timer = setInterval(() => Panel.refreshAll(), 8000);
    },
    stopPolling: function () {
      clearInterval(timer);
      timer = null;
    },
  };
  window.Panel = Panel;

  /* Khởi động: còn phiên thì vào thẳng bảng điều khiển. */
  fetch("/api/me", { credentials: "same-origin" })
    .then((resp) => (resp.ok ? showApp() : showLogin()))
    .catch(() => showLogin());
})();
