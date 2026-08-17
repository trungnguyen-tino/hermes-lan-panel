/* Hermes Panel — lõi: API, đăng nhập, điều hướng, trạng thái máy chủ. */
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
      const data = await api("/api/login", {
        method: "POST",
        body: { username: $("login-user").value, password: $("login-pass").value },
      });
      $("login-pass").value = "";
      setUser(data.username);
      showApp();
    } catch (e) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
  });

  function setUser(name) {
    $("user-name").textContent = name;
    $("user-initials").textContent = name.slice(0, 2).toUpperCase();
  }

  $("logout-btn").addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
    } catch (e) { /* vẫn đăng xuất kể cả khi lỗi mạng */ }
    showLogin();
  });

  /* ─── Điều hướng + ngăn kéo mobile ──────────────────────────── */
  const VIEW_LABEL = {
    overview: "Bảng điều khiển",
    chatgpt: "ChatGPT",
    zalo: "Zalo bot",
    model: "Model & API key",
    logs: "Nhật ký",
  };

  function selectView(name) {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.view === name);
    });
    document.querySelectorAll(".view").forEach((view) => {
      view.classList.toggle("hidden", view.id !== "view-" + name);
    });
    $("crumb-current").textContent = VIEW_LABEL[name] || name;
    $("app-screen").classList.remove("drawer-open");
    window.scrollTo({ top: 0 });
  }

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => selectView(item.dataset.view));
  });
  $("drawer-toggle").addEventListener("click", () => {
    $("app-screen").classList.toggle("drawer-open");
  });
  $("drawer-backdrop").addEventListener("click", () => {
    $("app-screen").classList.remove("drawer-open");
  });

  /* ─── Định dạng ─────────────────────────────────────────────── */
  function gb(bytes) {
    return (bytes / 1073741824).toFixed(1) + " GB";
  }

  function uptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    if (days > 0) return days + "n " + hours + "g";
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours + "g " + minutes + "p";
  }

  function meterTone(percent) {
    if (percent >= 90) return "err";
    if (percent >= 75) return "warn";
    return "";
  }

  function fillMeter(prefix, percent, value, side) {
    $(prefix + "-value").textContent = value;
    $(prefix + "-bar").style.width = Math.max(0, Math.min(100, percent)) + "%";
    $(prefix + "-bar").className = meterTone(percent);
    if (side !== undefined) $(prefix + "-side").textContent = side;
  }

  /* ─── Thông tin máy + dịch vụ ───────────────────────────────── */
  const STATE_LABEL = { active: "đang chạy", inactive: "đã dừng", failed: "lỗi", unknown: "không rõ" };
  const SERVICE_DESC = {
    "hermes-gateway": "Bot xử lý tin nhắn",
    "hermes-dashboard": "Giao diện chat",
    "hermes-panel": "Trang quản lý này",
  };

  function stateTone(state) {
    if (state === "active") return "ok";
    if (state === "failed") return "err";
    return "warn";
  }

  async function loadInfo() {
    const info = await api("/api/info");
    $("head-host").textContent = info.hostname + " · " + info.ip + " · Hermes " + info.hermes_version;
    $("chat-link").href = info.chat_url;
    $("ov-ip").textContent = info.ip;
    $("ov-hermes").textContent = info.hermes_version;
  }

  async function loadStatus() {
    const data = await api("/api/status");

    const box = $("services");
    box.innerHTML = "";
    data.services.forEach((svc) => {
      const row = document.createElement("div");
      row.className = "svc";

      const left = document.createElement("div");
      left.innerHTML =
        '<div class="name">' + svc.name +
        ' <span class="badge ' + stateTone(svc.state) + '">' +
        (STATE_LABEL[svc.state] || svc.state) + "</span></div>" +
        '<div class="desc">' + (SERVICE_DESC[svc.name] || "") + "</div>";
      row.appendChild(left);

      if (svc.controllable) {
        const actions = document.createElement("div");
        actions.className = "row";
        [["restart", "Khởi động lại"], ["stop", "Dừng"], ["start", "Chạy"]].forEach((pair) => {
          const button = document.createElement("button");
          button.className = "tiny";
          button.textContent = pair[1];
          button.addEventListener("click", () => serviceAction(svc.name, pair[0], button));
          actions.appendChild(button);
        });
        row.appendChild(actions);
      }
      box.appendChild(row);
    });

    const gateway = data.services.find((s) => s.name === "hermes-gateway");
    if (gateway) {
      $("pill-bot").textContent = STATE_LABEL[gateway.state] || gateway.state;
      $("pill-bot-dot").className = "dot " + stateTone(gateway.state);
    }

    const host = data.host || {};
    if (host.memory && host.memory.total) {
      const used = host.memory.total - host.memory.available;
      fillMeter("ram", host.memory.percent, host.memory.percent + "%", gb(used) + " / " + gb(host.memory.total));
      $("pill-ram").textContent = host.memory.percent + "%";
    }
    if (host.disk && host.disk.total) {
      fillMeter("disk", host.disk.percent, host.disk.percent + "%", gb(host.disk.used) + " / " + gb(host.disk.total));
      $("pill-disk").textContent = host.disk.percent + "%";
    }
    if (host.load_avg && host.load_avg.length) {
      // Quy ước hiển thị: coi tải 4.0 là 100% thanh đo.
      fillMeter("load", (host.load_avg[0] / 4) * 100, host.load_avg[0].toFixed(2));
    }
    if (host.uptime_seconds) {
      $("uptime-value").textContent = uptime(host.uptime_seconds);
    }
  }

  async function serviceAction(service, action, button) {
    button.disabled = true;
    try {
      await api("/api/services/" + service + "/" + action, { method: "POST" });
      toast(service + ": đã " + (action === "restart" ? "khởi động lại" : action === "stop" ? "dừng" : "chạy"), "ok");
      setTimeout(loadStatus, 1500);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
    }
  }

  $("refresh-btn").addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    loadInfo().catch(() => {});
    Panel.refreshAll().finally(() => {
      button.disabled = false;
      toast("Đã cập nhật.", "ok");
    });
  });

  /* ─── Vòng lặp cập nhật ─────────────────────────────────────── */
  const tasks = [];       // các hàm refresh do features.js đăng ký
  let timer = null;

  const Panel = {
    $: $,
    api: api,
    toast: toast,
    showLogin: showLogin,
    selectView: selectView,
    register: (fn) => tasks.push(fn),
    refreshAll: async function () {
      for (const job of [loadStatus].concat(tasks)) {
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
    .then((resp) => (resp.ok ? resp.json() : null))
    .then((payload) => {
      if (payload && payload.data) {
        setUser(payload.data.username);
        showApp();
      } else {
        showLogin();
      }
    })
    .catch(() => showLogin());
})();
