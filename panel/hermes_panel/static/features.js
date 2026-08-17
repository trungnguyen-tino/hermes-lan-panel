/* Hermes Panel — ChatGPT, Zalo, model/API key, nhật ký. */
(function () {
  "use strict";

  const { $, api, toast, register } = window.Panel;

  /* Một trạng thái hiện ở 3 chỗ: thẻ chi tiết, mục sidebar, dòng tổng quan.
     Sidebar hẹp nên dùng nhãn rút gọn, rỗng thì ẩn hẳn cho đỡ rối. */
  function setBadge(ids, text, tone, short) {
    ids.forEach((id) => {
      const el = $(id);
      if (!el) return;
      const isNav = id.indexOf("nav-") === 0;
      const label = isNav ? (short === undefined ? text : short) : text;
      el.textContent = label;
      el.className = "badge " + (tone || "");
      if (isNav && !label) el.classList.add("hidden");
    });
  }

  /* ─── ChatGPT (Codex OAuth) ─────────────────────────────────── */
  const CODEX_IDS = ["codex-badge", "nav-codex-badge", "ov-codex"];

  async function refreshCodex() {
    const data = await api("/api/codex/status");
    const box = $("codex-pending");

    if (data.status === "connected") {
      setBadge(CODEX_IDS, data.active ? "đã kết nối" : "đã lưu", data.active ? "ok" : "warn", "ok");
      box.classList.add("hidden");
      $("codex-disable").classList.remove("hidden");
      $("codex-start").textContent = "Đăng nhập lại";
      $("codex-model").textContent = data.model || "—";
    } else if (data.status === "pending") {
      setBadge(CODEX_IDS, "chờ xác nhận", "warn", "chờ");
      if (data.url) {
        $("codex-url").textContent = data.url;
        $("codex-url").href = data.url;
        $("codex-code").textContent = data.code || "—";
        box.classList.remove("hidden");
      }
    } else {
      setBadge(CODEX_IDS, "chưa kết nối", "", "");
      box.classList.add("hidden");
      $("codex-disable").classList.add("hidden");
    }
  }

  $("codex-start").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    setBadge(CODEX_IDS, "đang tạo mã…", "warn", "chờ");
    try {
      const data = await api("/api/codex/start", { method: "POST" });
      $("codex-url").textContent = data.url;
      $("codex-url").href = data.url;
      $("codex-code").textContent = data.code || "—";
      $("codex-pending").classList.remove("hidden");
      toast("Mở link rồi nhập mã để hoàn tất.", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
      refreshCodex().catch(() => {});
    }
  });

  $("codex-copy").addEventListener("click", () => {
    const code = $("codex-code").textContent;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(code).then(
        () => toast("Đã sao chép mã.", "ok"),
        () => toast("Không sao chép được, chép tay: " + code, "err")
      );
    } else {
      toast("Mã: " + code);
    }
  });

  $("codex-disable").addEventListener("click", async () => {
    if (!confirm("Ngắt kết nối ChatGPT? Bot sẽ ngừng dùng tài khoản này.")) return;
    try {
      await api("/api/codex/disable", { method: "POST", body: {} });
      toast("Đã ngắt ChatGPT. Chọn nhà cung cấp khác nếu cần.", "ok");
    } catch (e) {
      toast(e.message, "err");
    }
    refreshCodex().catch(() => {});
  });

  $("codex-import").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const raw = $("codex-json").value.trim();
    if (!raw) return toast("Chưa dán nội dung auth.json.", "err");
    button.disabled = true;
    try {
      await api("/api/codex/import", { method: "POST", body: { auth_json: raw } });
      $("codex-json").value = "";
      toast("Đã nạp auth.json.", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
      refreshCodex().catch(() => {});
    }
  });

  /* ─── Zalo ──────────────────────────────────────────────────── */
  const ZALO_IDS = ["zalo-badge", "nav-zalo-badge", "ov-zalo"];
  const ZALO_LABEL = {
    connected: ["đã đăng nhập", "ok", "ok"],
    pending: ["chờ quét QR", "warn", "QR"],
    scanned: ["đang xử lý", "warn", "chờ"],
    error: ["lỗi", "err", "lỗi"],
    disconnected: ["chưa kết nối", "", ""],
  };

  function showQr() {
    $("zalo-qr-box").classList.remove("hidden");
    $("zalo-qr").src = "/api/zalo/qr?t=" + Date.now();
  }

  async function refreshZalo() {
    const data = await api("/api/zalo/status");
    const label = ZALO_LABEL[data.status] || [data.status, "", ""];
    setBadge(ZALO_IDS, label[0], label[1], label[2]);

    const connected = data.status === "connected";
    $("zalo-disconnect").classList.toggle("hidden", !connected);
    $("zalo-qr-box").classList.toggle("hidden", data.status !== "pending");
    if (data.status === "pending") showQr();
    $("zalo-owner-box").classList.toggle("hidden", !connected || data.owner_set);

    const bits = [];
    bits.push(data.bot_uid ? "Bot: " + (data.name || data.bot_uid) : "Chưa có tài khoản bot");
    bits.push(data.owner_set ? "đã có chủ bot" : "chưa đặt chủ bot");
    if (data.error) bits.push("lỗi: " + data.error);
    $("zalo-info").textContent = bits.join(" · ");
    $("ov-owner").textContent = data.owner_set ? "đã đặt" : "chưa đặt";
  }

  $("zalo-connect").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    setBadge(ZALO_IDS, "đang khởi động…", "warn", "chờ");
    try {
      const data = await api("/api/zalo/connect", { method: "POST" });
      if (data.status === "connected") {
        toast("Bot đã đăng nhập sẵn.", "ok");
      } else {
        setTimeout(showQr, 1500);
        toast("Quét mã QR bằng app Zalo (số phụ).", "ok");
      }
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
      refreshZalo().catch(() => {});
    }
  });

  $("zalo-owner-save").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const phone = $("zalo-phone").value.trim();
    if (!phone) return toast("Nhập số Zalo của sếp.", "err");
    button.disabled = true;
    try {
      await api("/api/zalo/set-owner", { method: "POST", body: { phone: phone } });
      toast("Đã đặt chủ bot, gateway đang khởi động lại…", "ok");
      $("zalo-phone").value = "";
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
      refreshZalo().catch(() => {});
    }
  });

  $("zalo-disconnect").addEventListener("click", async () => {
    if (!confirm("Đăng xuất tài khoản Zalo của bot?")) return;
    try {
      await api("/api/zalo/disconnect", { method: "POST" });
      toast("Đã đăng xuất Zalo.", "ok");
    } catch (e) {
      toast(e.message, "err");
    }
    refreshZalo().catch(() => {});
  });

  /* ─── Model + API key ───────────────────────────────────────── */
  /* Danh sách provider và model đều do Hermes cung cấp (/api/providers,
     /api/models) — panel không tự chép danh sách, vì slug model đổi theo bản
     Hermes (vd deepseek-chat -> deepseek-v4-pro). */
  let providers = [];

  function currentProvider() {
    return providers.find((p) => p.id === $("provider-select").value) || null;
  }

  async function loadProviders() {
    const data = await api("/api/providers");
    providers = data.providers || [];

    const select = $("provider-select");
    const previous = select.value;
    select.innerHTML = "";

    if (!providers.length) {
      $("provider-count").textContent = data.warning || "Chưa đọc được danh sách từ Hermes.";
    } else {
      $("provider-count").textContent =
        "Hermes hỗ trợ " + providers.length + " nhà cung cấp — danh sách lấy trực tiếp từ agent";
      const groups = [
        ["accounts", "Đăng nhập bằng tài khoản"],
        ["keys", "Dùng API key"],
      ];
      groups.forEach((pair) => {
        const members = providers.filter((p) => (p.tab || "keys") === pair[0]);
        if (!members.length) return;
        const group = document.createElement("optgroup");
        group.label = pair[1];
        members.forEach((provider) => {
          const option = document.createElement("option");
          option.value = provider.id;
          option.textContent = provider.label;
          group.appendChild(option);
        });
        select.appendChild(group);
      });
    }

    const wanted = previous || data.current.provider;
    if (wanted && providers.some((p) => p.id === wanted)) select.value = wanted;
    $("model-input").value = data.current.model || "";
    $("ov-model").textContent = data.current.provider
      ? data.current.provider + " / " + (data.current.model || "mặc định")
      : "chưa cấu hình";
    renderProviderDetails();
    await loadModels(false);
  }

  function renderProviderDetails() {
    const provider = currentProvider();
    if (!provider) return;
    $("provider-desc").textContent = provider.description || "";

    const needsKey = Boolean(provider.env_key);
    $("apikey-box").classList.toggle("hidden", !needsKey);
    $("oauth-box").classList.toggle("hidden", needsKey);

    if (needsKey) {
      const state = $("apikey-state");
      state.textContent = provider.key_set ? "đã lưu " + provider.key_masked : "chưa có";
      state.className = "badge " + (provider.key_set ? "ok" : "warn");
      $("apikey-hint").textContent =
        "Lưu vào biến " + provider.env_key +
        (provider.signup_url ? " · lấy key tại " + provider.signup_url : "");
    } else {
      $("oauth-note").textContent = provider.label + " — đăng nhập kiểu " + (provider.auth_type || "oauth");
    }
  }

  async function loadModels(refresh) {
    const provider = $("provider-select").value;
    if (!provider) return;
    const hint = $("model-hint");
    hint.textContent = refresh ? "đang hỏi lại Hermes…" : "đang tải danh sách từ Hermes…";
    try {
      const data = await api(
        "/api/models?provider=" + encodeURIComponent(provider) + (refresh ? "&refresh=1" : "")
      );
      const list = $("model-list");
      list.innerHTML = "";
      (data.models || []).forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        list.appendChild(option);
      });
      const parts = [];
      parts.push((data.models || []).length + " model khả dụng");
      if (data.default) parts.push("Hermes mặc định: " + data.default);
      hint.textContent = parts.join(" · ");
      if (!$("model-input").value && data.default) $("model-input").value = data.default;
      $("model-input").placeholder = data.default || "nhập tên model";
    } catch (e) {
      hint.textContent = e.message;
    }
  }

  $("provider-select").addEventListener("change", () => {
    $("model-input").value = "";
    renderProviderDetails();
    loadModels(false);
  });

  $("model-reload").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await loadModels(true);   // hỏi lại provider bằng key hiện có
      toast("Đã cập nhật danh sách model.", "ok");
    } finally {
      button.disabled = false;
    }
  });

  $("model-save").addEventListener("click", async (event) => {
    const button = event.currentTarget;   // giữ tham chiếu TRƯỚC await
    button.disabled = true;
    try {
      const data = await api("/api/model", {
        method: "PUT",
        body: { provider: $("provider-select").value, model: $("model-input").value.trim() },
      });
      $("model-input").value = data.model;
      $("ov-model").textContent = data.provider + " / " + (data.model || "mặc định");
      toast("Đã đặt " + data.provider + " / " + data.model + ", gateway đang khởi động lại.", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
    }
  });

  $("apikey-save").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const key = $("apikey-input").value.trim();
    if (!key) return toast("Chưa nhập API key.", "err");
    button.disabled = true;
    try {
      await api("/api/api-key", {
        method: "PUT",
        body: { provider: $("provider-select").value, api_key: key },
      });
      $("apikey-input").value = "";
      toast("Đã lưu key, đang hỏi Hermes danh sách model…", "ok");
      await loadProviders();
      await loadModels(true);   // lấy được model = key dùng được thật
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
    }
  });

  $("apikey-delete").addEventListener("click", async () => {
    if (!confirm("Xoá API key của nhà cung cấp này?")) return;
    try {
      await api("/api/api-key?provider=" + encodeURIComponent($("provider-select").value), {
        method: "DELETE",
      });
      toast("Đã xoá key.", "ok");
      await loadProviders();
    } catch (e) {
      toast(e.message, "err");
    }
  });

  /* ─── Nhật ký ───────────────────────────────────────────────── */
  let logTimer = null;

  async function loadLogs() {
    try {
      const data = await api(
        "/api/logs?service=" + $("log-service").value + "&lines=" + $("log-lines").value
      );
      const output = $("log-output");
      output.textContent = data.lines.join("\n") || "(trống)";
      output.scrollTop = output.scrollHeight;
    } catch (e) {
      $("log-output").textContent = e.message;
    }
  }

  $("log-refresh").addEventListener("click", loadLogs);
  $("log-service").addEventListener("change", loadLogs);
  $("log-lines").addEventListener("change", loadLogs);
  $("log-auto").addEventListener("change", (event) => {
    clearInterval(logTimer);
    logTimer = event.currentTarget.checked ? setInterval(loadLogs, 10000) : null;
  });

  /* ChatGPT + Zalo bám theo vòng lặp; provider chỉ nạp một lần để không ghi đè
     lựa chọn người dùng đang gõ dở. */
  register(refreshCodex);
  register(refreshZalo);
  register(function once() {
    return providers.length ? Promise.resolve() : loadProviders();
  });
})();
