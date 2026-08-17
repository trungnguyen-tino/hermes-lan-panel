/* Hermes Panel — ChatGPT, Zalo, model/API key, nhật ký. */
(function () {
  "use strict";

  const { $, api, toast, register } = window.Panel;
  const badge = (el, text, kind) => {
    el.textContent = text;
    el.className = "badge " + (kind || "");
  };

  /* ─── ChatGPT (Codex OAuth) ─────────────────────────────────── */
  async function refreshCodex() {
    const data = await api("/api/codex/status");
    const box = $("codex-pending");
    if (data.status === "connected") {
      badge($("codex-badge"), data.active ? "đã kết nối" : "đã lưu (chưa dùng)", data.active ? "ok" : "warn");
      box.classList.add("hidden");
      $("codex-disable").classList.remove("hidden");
      $("codex-start").textContent = "Đăng nhập lại";
    } else if (data.status === "pending") {
      badge($("codex-badge"), "đang chờ xác nhận", "warn");
      if (data.url) {
        $("codex-url").textContent = data.url;
        $("codex-url").href = data.url;
        $("codex-code").textContent = data.code || "—";
        box.classList.remove("hidden");
      }
    } else {
      badge($("codex-badge"), "chưa kết nối");
      box.classList.add("hidden");
      $("codex-disable").classList.add("hidden");
    }
  }

  $("codex-start").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    badge($("codex-badge"), "đang tạo mã…", "warn");
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
        () => toast("Không sao chép được, hãy chép tay: " + code, "err")
      );
    } else {
      toast("Mã: " + code);
    }
  });

  $("codex-disable").addEventListener("click", async () => {
    if (!confirm("Ngắt kết nối ChatGPT? Bot sẽ ngừng dùng tài khoản này.")) return;
    try {
      await api("/api/codex/disable", { method: "POST", body: {} });
      toast("Đã ngắt ChatGPT. Chọn provider khác nếu cần.", "ok");
      refreshCodex();
    } catch (e) {
      toast(e.message, "err");
    }
  });

  $("codex-import").addEventListener("click", async () => {
    const raw = $("codex-json").value.trim();
    if (!raw) return toast("Chưa dán nội dung auth.json.", "err");
    try {
      await api("/api/codex/import", { method: "POST", body: { auth_json: raw } });
      $("codex-json").value = "";
      toast("Đã nạp auth.json.", "ok");
      refreshCodex();
    } catch (e) {
      toast(e.message, "err");
    }
  });

  /* ─── Zalo ──────────────────────────────────────────────────── */
  const ZALO_LABEL = {
    connected: ["đã đăng nhập", "ok"],
    pending: ["chờ quét QR", "warn"],
    scanned: ["đã quét, đang xử lý", "warn"],
    error: ["lỗi", "err"],
    disconnected: ["chưa kết nối", ""],
  };

  function showQr() {
    $("zalo-qr-box").classList.remove("hidden");
    $("zalo-qr").src = "/api/zalo/qr?t=" + Date.now();
  }

  async function refreshZalo() {
    const data = await api("/api/zalo/status");
    const label = ZALO_LABEL[data.status] || [data.status, ""];
    badge($("zalo-badge"), label[0], label[1]);

    const connected = data.status === "connected";
    $("zalo-disconnect").classList.toggle("hidden", !connected);
    $("zalo-qr-box").classList.toggle("hidden", data.status !== "pending");
    if (data.status === "pending") showQr();
    $("zalo-owner-box").classList.toggle("hidden", !connected || data.owner_set);

    const bits = [];
    if (data.bot_uid) bits.push("Bot: " + (data.name || data.bot_uid));
    bits.push(data.owner_set ? "Đã có chủ bot ✓" : "Chưa đặt chủ bot");
    if (data.error) bits.push("Lỗi: " + data.error);
    $("zalo-info").textContent = bits.join(" · ");
  }

  $("zalo-connect").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    badge($("zalo-badge"), "đang khởi động…", "warn");
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
      toast("Đã đặt chủ bot, đang khởi động lại gateway…", "ok");
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
  let providers = [];

  function currentProvider() {
    return providers.find((p) => p.id === $("provider-select").value) || null;
  }

  function renderProviderDetails() {
    const provider = currentProvider();
    const list = $("model-list");
    list.innerHTML = "";
    if (!provider) return;
    (provider.models || []).forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      list.appendChild(option);
    });
    const needsKey = Boolean(provider.env_key);
    $("apikey-box").classList.toggle("hidden", !needsKey);
    $("apikey-state").textContent = needsKey
      ? (provider.key_set ? "(đã lưu " + provider.key_masked + ")" : "(chưa có)")
      : "";
  }

  async function loadProviders() {
    const data = await api("/api/providers");
    providers = data.providers;
    const select = $("provider-select");
    select.innerHTML = "";
    providers.forEach((provider) => {
      const option = document.createElement("option");
      option.value = provider.id;
      option.textContent = provider.label;
      select.appendChild(option);
    });
    if (data.current.provider) select.value = data.current.provider;
    $("model-input").value = data.current.model || "";
    renderProviderDetails();
  }

  $("provider-select").addEventListener("change", renderProviderDetails);

  /* Lưu tham chiếu nút TRƯỚC await: sau await thì event.currentTarget = null. */
  $("model-save").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const data = await api("/api/model", {
        method: "PUT",
        body: { provider: $("provider-select").value, model: $("model-input").value.trim() },
      });
      $("model-input").value = data.model;
      toast("Đã đặt " + data.provider + " / " + data.model + ", gateway đang khởi động lại.", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.disabled = false;
    }
  });

  $("apikey-test").addEventListener("click", async () => {
    const key = $("apikey-input").value.trim();
    if (!key) return toast("Chưa nhập API key.", "err");
    try {
      const data = await api("/api/test-key", {
        method: "POST",
        body: { provider: $("provider-select").value, api_key: key },
      });
      toast("Key hợp lệ (HTTP " + data.status_code + ").", "ok");
    } catch (e) {
      toast(e.message, "err");
    }
  });

  $("apikey-save").addEventListener("click", async () => {
    const key = $("apikey-input").value.trim();
    if (!key) return toast("Chưa nhập API key.", "err");
    try {
      await api("/api/api-key", {
        method: "PUT",
        body: { provider: $("provider-select").value, api_key: key },
      });
      $("apikey-input").value = "";
      toast("Đã lưu key, gateway đang khởi động lại.", "ok");
      loadProviders();
    } catch (e) {
      toast(e.message, "err");
    }
  });

  $("apikey-delete").addEventListener("click", async () => {
    if (!confirm("Xoá API key của provider này?")) return;
    try {
      await api("/api/api-key?provider=" + encodeURIComponent($("provider-select").value), {
        method: "DELETE",
      });
      toast("Đã xoá key.", "ok");
      loadProviders();
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

  /* Chỉ ChatGPT + Zalo cần bám theo vòng lặp; provider nạp một lần để không
     ghi đè lựa chọn người dùng đang gõ dở. */
  register(refreshCodex);
  register(refreshZalo);
  register(function once() {
    if (providers.length) return Promise.resolve();
    return loadProviders();
  });
})();
