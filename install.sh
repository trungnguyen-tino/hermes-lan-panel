#!/bin/bash
# =============================================================================
# hermes-lan-panel — cài Hermes Agent + GUI quản lý cho VPS trong mạng LAN
#
# Dùng cho VPS/VM nội bộ (vd 192.168.x.x) truy cập qua Nginx Proxy Manager:
# KHÔNG cài Caddy, KHÔNG xin Let's Encrypt, KHÔNG cần domain công khai.
#
# Cách chạy:
#   curl -fsSL https://raw.githubusercontent.com/trungnguyen-tino/hermes-lan-panel/main/install.sh | bash
#   bash install.sh --admin-pass 'MatKhau123' --panel-port 8088
#
# Cờ:
#   --panel-port <8088>    Cổng GUI panel (Nginx Proxy Manager trỏ vào đây)
#   --admin-user <admin>   Tài khoản đăng nhập panel
#   --admin-pass <...>     Mật khẩu panel (tự sinh nếu bỏ trống)
#   --chat-url <url>       URL chat UI hiển thị trên panel (vd https://chat.cty.vn)
#   --chat-local           Chỉ mở chat UI ở 127.0.0.1 (mặc định: mở ra LAN)
#   --ref <git-ref>        Nhánh/tag của hermes-agent (mặc định main)
#   --panel-repo <url>     Repo panel (mặc định repo trungnguyen-tino)
#   --skip-hermes          Chỉ cài/nâng cấp panel, không đụng Hermes
#   --skip-zalo            Không cài plugin Zalo
#   --allow-lan <CIDR>     Mở UFW cho dải LAN này (chỉ khi UFW đang bật)
# =============================================================================

set -euo pipefail

readonly APP_VERSION="0.1.0"
readonly HERMES_REPO_URL="https://github.com/NousResearch/hermes-agent.git"
readonly ZALO_PLUGIN_REPO="https://github.com/tinovn/hermes-zalo-plugin"
readonly INSTALL_DIR="/opt/hermes"
readonly HERMES_SRC_DIR="${INSTALL_DIR}/hermes-agent"
readonly PANEL_DIR="/opt/hermes-panel"
readonly HERMES_HOME="/root/.hermes"
readonly ZALO_PLUGIN_DIR="${HERMES_HOME}/plugins/zalo-personal"
readonly LOG_FILE="/var/log/hermes-lan-install.log"
readonly DASHBOARD_PORT=9119
# Giữ đúng bộ extras đã chạy ổn định trên bản deploy hiện tại của Tino.
readonly HERMES_EXTRAS="web,messaging,cron,voice,mcp,honcho"
readonly PYTHON_PIN="3.11"

# ---- Cờ dòng lệnh ---------------------------------------------------------
PANEL_PORT=8088
ADMIN_USER="admin"
ADMIN_PASS=""
CHAT_URL_ARG=""
CHAT_LOCAL=false
HERMES_REF="main"
PANEL_REPO="https://github.com/trungnguyen-tino/hermes-lan-panel.git"
SKIP_HERMES=false
WITH_ZALO=true
ALLOW_LAN=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --panel-port) PANEL_PORT="$2"; shift 2 ;;
    --admin-user) ADMIN_USER="$2"; shift 2 ;;
    --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
    --chat-url)   CHAT_URL_ARG="$2"; shift 2 ;;
    --chat-local) CHAT_LOCAL=true; shift ;;
    --ref)        HERMES_REF="$2"; shift 2 ;;
    --panel-repo) PANEL_REPO="$2"; shift 2 ;;
    --skip-hermes) SKIP_HERMES=true; shift ;;
    --skip-zalo)  WITH_ZALO=false; shift ;;
    --allow-lan)  ALLOW_LAN="$2"; shift 2 ;;
    -h|--help)    sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Bỏ qua tham số lạ: $1" >&2; shift ;;
  esac
done

# ---- Log ------------------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")"
log()  { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE" >&2; }
die()  { log "LỖI: $*"; exit 1; }
step() { log ""; log "==== $* ===="; }

log "=== hermes-lan-panel ${APP_VERSION} bắt đầu cài ==="

# ---- 1. Kiểm tra môi trường ----------------------------------------------
step "1. Kiểm tra hệ điều hành"
[[ "$(id -u)" == "0" ]] || die "Phải chạy bằng root (dùng sudo -i)."
[[ -f /etc/os-release ]] || die "Không tìm thấy /etc/os-release."
# shellcheck source=/dev/null
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) log "OS: ${PRETTY_NAME}" ;;
  *) log "CẢNH BÁO: chưa kiểm thử trên ${PRETTY_NAME:-OS lạ} — script tiếp tục nhưng có thể lỗi." ;;
esac

DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
RAM_MB=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
log "Đĩa trống ${DISK_GB}GB · RAM ${RAM_MB}MB"
[[ "${DISK_GB:-0}" -ge 6 ]]   || die "Cần ít nhất 6GB trống trên /, đang có ${DISK_GB}GB."
[[ "${RAM_MB:-0}" -ge 900 ]]  || die "Cần ít nhất 1GB RAM, đang có ${RAM_MB}MB."

LAN_IP=$(hostname -I | awk '{print $1}')
[[ -n "$LAN_IP" ]] || LAN_IP="127.0.0.1"
log "IP LAN: ${LAN_IP}"

# ---- 2. Gói hệ thống ------------------------------------------------------
step "2. Cài gói hệ thống"
export DEBIAN_FRONTEND=noninteractive

wait_for_apt() {
  local waited=0
  while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1; do
    [[ $waited -ge 180 ]] && { log "CẢNH BÁO: apt vẫn bị khoá sau 180s, vẫn thử tiếp"; return 0; }
    log "apt đang bị khoá, chờ 5s (${waited}s)…"
    sleep 5; waited=$((waited + 5))
  done
}

apt_retry() {
  local i=0
  while [[ $i -lt 3 ]]; do
    wait_for_apt
    if "$@"; then return 0; fi
    i=$((i + 1)); log "apt thử lại lần ${i}/3…"; sleep 5
  done
  die "Lệnh apt thất bại: $*"
}

apt_retry apt-get -qqy update
apt_retry apt-get -qqy install curl ca-certificates git jq build-essential \
  libssl-dev libffi-dev python3-venv python3-pip ffmpeg openssl psmisc

# ---- 3. uv + Python 3.11 --------------------------------------------------
step "3. Cài uv + Python ${PYTHON_PIN}"
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ln -sf /root/.local/bin/uv /usr/local/bin/uv
fi
uv python install "$PYTHON_PIN"
log "uv: $(uv --version)"

# ---- 4. Node.js 22 (sidecar Zalo + build web dashboard) -------------------
step "4. Cài Node.js 22"
if ! command -v node &>/dev/null || [[ "$(node -v 2>/dev/null)" != v22* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt_retry apt-get -qqy install nodejs
fi
log "Node: $(node -v) · npm: $(npm -v)"

mkdir -p "${INSTALL_DIR}" "${HERMES_HOME}" /opt/data/zalo

# ---- 5. Hermes Agent ------------------------------------------------------
if [[ "$SKIP_HERMES" != "true" ]]; then
  step "5. Cài Hermes Agent (ref=${HERMES_REF})"
  # Shallow clone: repo Hermes ~670MB nếu lấy cả lịch sử, trên đường truyền yếu
  # (vài trăm KB/s) sẽ mất cả tiếng. VPS không cần lịch sử git — chỉ cần mã nguồn
  # của đúng một ref. Nâng cấp sau này cũng fetch --depth 1 rồi reset.
  if [[ ! -d "${HERMES_SRC_DIR}/.git" ]]; then
    rm -rf "${HERMES_SRC_DIR}"
    git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO_URL}" "${HERMES_SRC_DIR}" \
      || git clone --depth 1 "${HERMES_REPO_URL}" "${HERMES_SRC_DIR}" \
      || die "Không clone được Hermes Agent"
  else
    git -C "${HERMES_SRC_DIR}" fetch --depth 1 origin "${HERMES_REF}" \
      && git -C "${HERMES_SRC_DIR}" reset --hard FETCH_HEAD \
      || log "CẢNH BÁO: không cập nhật được Hermes, dùng bản đang có"
  fi
  log "Hermes ref: $(git -C "${HERMES_SRC_DIR}" log -1 --format='%h %s' 2>/dev/null || echo '?')"

  [[ -d "${HERMES_SRC_DIR}/.venv" ]] || uv venv --python "$PYTHON_PIN" "${HERMES_SRC_DIR}/.venv"
  # cd vào thư mục nguồn rồi cài ".[extras]" — dạng "<path>[extras]" không phải
  # pip/uv nào cũng hiểu.
  (cd "${HERMES_SRC_DIR}" && VIRTUAL_ENV="${HERMES_SRC_DIR}/.venv" uv pip install \
    --python "${HERMES_SRC_DIR}/.venv/bin/python" -e ".[${HERMES_EXTRAS}]")
  ln -sf "${HERMES_SRC_DIR}/.venv/bin/hermes" /usr/local/bin/hermes
  log "Hermes: $(/usr/local/bin/hermes version 2>/dev/null | head -1 || echo 'đã cài')"

  # Build sẵn web dashboard: Hermes tự build lúc systemd khởi động sẽ hỏng
  # (không có TTY, tiến trình npm con bị giết sau ~7s).
  if [[ -d "${HERMES_SRC_DIR}/web" && ! -d "${HERMES_SRC_DIR}/hermes_cli/web_dist" ]]; then
    log "Build web dashboard (npm install + build)…"
    (cd "${HERMES_SRC_DIR}/web" && npm install --no-audit --no-fund --loglevel=error && npm run build) \
      || log "CẢNH BÁO: build web dashboard thất bại — chat UI có thể không mở được"
  fi

  # Cron gửi tin sạch: bỏ phần bọc "Cronjob Response: … (job_id: …)".
  # Dùng `env` chứ không gán tiền tố: HERMES_HOME là readonly nên
  # `HERMES_HOME=... lệnh` sẽ bị bash chặn ("readonly variable") và bỏ qua lệnh.
  env HERMES_HOME="${HERMES_HOME}" "${HERMES_SRC_DIR}/.venv/bin/python" - <<'PYEOF' >>"${LOG_FILE}" 2>&1 \
    || log "CẢNH BÁO: không đặt được cron.wrap_response=false"
import os, yaml
p = os.path.join(os.environ["HERMES_HOME"], "config.yaml")
d = yaml.safe_load(open(p).read()) if os.path.exists(p) else {}
d = d if isinstance(d, dict) else {}
cron = d.get("cron") if isinstance(d.get("cron"), dict) else {}
cron["wrap_response"] = False
d["cron"] = cron
yaml.safe_dump(d, open(p, "w"), allow_unicode=True, sort_keys=False)
print("cron.wrap_response=false")
PYEOF
else
  log "Bỏ qua Hermes (--skip-hermes)"
fi

# ---- 6. Plugin Zalo -------------------------------------------------------
if [[ "$WITH_ZALO" == "true" && "$SKIP_HERMES" != "true" ]]; then
  step "6. Cài plugin Zalo (zalo-personal)"
  mkdir -p "$(dirname "${ZALO_PLUGIN_DIR}")"
  if [[ ! -d "${ZALO_PLUGIN_DIR}/.git" ]]; then
    rm -rf "${ZALO_PLUGIN_DIR}"
    git clone --depth 1 "${ZALO_PLUGIN_REPO}" "${ZALO_PLUGIN_DIR}" \
      || log "CẢNH BÁO: clone plugin Zalo thất bại — bỏ qua"
  else
    git -C "${ZALO_PLUGIN_DIR}" pull --ff-only 2>/dev/null || true
  fi

  if [[ -f "${ZALO_PLUGIN_DIR}/sidecar/package.json" ]]; then
    log "Cài Node deps cho sidecar (zca-js)…"
    (cd "${ZALO_PLUGIN_DIR}/sidecar" && npm install --no-audit --no-fund --loglevel=error) \
      || log "CẢNH BÁO: npm install sidecar thất bại — chạy tay trước khi dùng Zalo"

    # Hermes ship plugin ở trạng thái TẮT. Khoá đăng ký là trường `name:` trong
    # plugin.yaml (không phải tên thư mục) — xem hermes_cli/plugins.py.
    ZALO_KEY="$(grep -E '^name:' "${ZALO_PLUGIN_DIR}/plugin.yaml" 2>/dev/null | head -1 | cut -d: -f2 | xargs)"
    ZALO_KEY="${ZALO_KEY:-zalo-personal-platform}"
    env HERMES_HOME="${HERMES_HOME}" /usr/local/bin/hermes plugins enable "${ZALO_KEY}" \
      >>"${LOG_FILE}" 2>&1 || log "CẢNH BÁO: bật plugin ${ZALO_KEY} thất bại — bật lại từ panel"
    log "Đã cài plugin Zalo tại ${ZALO_PLUGIN_DIR}"
    # platforms.zalo-personal.enabled sẽ được panel bật khi đặt chủ bot
    # (gateway chỉ chạy platform khi đã có ZALO_PERSONAL_OWNER_UID).
  else
    log "CẢNH BÁO: nguồn plugin Zalo không đầy đủ — bỏ qua sidecar"
  fi
else
  log "Bỏ qua plugin Zalo"
fi

# ---- 7. Nguồn panel -------------------------------------------------------
step "7. Cài panel"
if [[ -d "${PANEL_DIR}/.git" ]]; then
  git -C "${PANEL_DIR}" pull --ff-only 2>/dev/null || log "CẢNH BÁO: không pull được panel, dùng bản hiện có"
elif [[ -f "$(dirname "$(readlink -f "$0")")/panel/pyproject.toml" ]]; then
  # Chạy install.sh từ bản checkout sẵn có (scp lên máy) — copy vào /opt.
  SRC_DIR="$(dirname "$(readlink -f "$0")")"
  log "Dùng nguồn panel tại ${SRC_DIR}"
  mkdir -p "${PANEL_DIR}"
  cp -a "${SRC_DIR}/panel" "${SRC_DIR}/install.sh" "${PANEL_DIR}/" 2>/dev/null || true
else
  rm -rf "${PANEL_DIR}"
  git clone --depth 1 "${PANEL_REPO}" "${PANEL_DIR}" || die "Không clone được panel từ ${PANEL_REPO}"
fi

[[ -d "${PANEL_DIR}/.venv" ]] || uv venv --python "$PYTHON_PIN" "${PANEL_DIR}/.venv"
VIRTUAL_ENV="${PANEL_DIR}/.venv" uv pip install \
  --python "${PANEL_DIR}/.venv/bin/python" -e "${PANEL_DIR}/panel"

# ---- 8. Sinh .env ---------------------------------------------------------
step "8. Tạo cấu hình ${INSTALL_DIR}/.env"

read_env_value() {
  local key="$1" file="${INSTALL_DIR}/.env"
  [[ -f "$file" ]] || { echo ""; return; }
  awk -F= -v k="$key" '$1 == k { sub("^[^=]*=", ""); print; exit }' "$file"
}

hash_password() {  # đọc mật khẩu qua stdin để không lộ trong `ps`
  printf '%s' "$1" | "${PANEL_DIR}/.venv/bin/python" -c \
    'import bcrypt,sys; print(bcrypt.hashpw(sys.stdin.buffer.read(), bcrypt.gensalt(12)).decode())'
}

EXISTING_HASH=$(read_env_value HERMES_PANEL_PASSWORD_HASH)
EXISTING_SECRET=$(read_env_value HERMES_PANEL_SESSION_SECRET)
EXISTING_GATEWAY_TOKEN=$(read_env_value HERMES_GATEWAY_TOKEN)

PASSWORD_PLAIN=""
if [[ -n "$ADMIN_PASS" ]]; then
  PASSWORD_PLAIN="$ADMIN_PASS"
elif [[ -z "$EXISTING_HASH" ]]; then
  PASSWORD_PLAIN="$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)"
fi

if [[ -n "$PASSWORD_PLAIN" ]]; then
  PASSWORD_HASH="$(hash_password "$PASSWORD_PLAIN")"
else
  PASSWORD_HASH="$EXISTING_HASH"
fi
SESSION_SECRET="${EXISTING_SECRET:-$(openssl rand -hex 32)}"
GATEWAY_TOKEN="${EXISTING_GATEWAY_TOKEN:-$(openssl rand -hex 32)}"
CHAT_URL="${CHAT_URL_ARG:-$(read_env_value HERMES_CHAT_URL)}"
[[ -n "$CHAT_URL" ]] || CHAT_URL="http://${LAN_IP}:${DASHBOARD_PORT}"

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  cat > "${INSTALL_DIR}/.env" <<EOF
# hermes-lan-panel — sinh bởi install.sh $(date -u +%FT%TZ)
# Sửa xong nhớ: systemctl restart hermes-gateway hermes-panel

# --- Lõi ---
HERMES_HOME=${HERMES_HOME}
HERMES_LAN_VERSION=${APP_VERSION}
HERMES_LAN_IP=${LAN_IP}

# --- Cổng ---
HERMES_PANEL_PORT=${PANEL_PORT}
HERMES_DASHBOARD_PORT=${DASHBOARD_PORT}
HERMES_CHAT_URL=${CHAT_URL}

# --- Đăng nhập panel ---
HERMES_PANEL_USER=${ADMIN_USER}
HERMES_PANEL_PASSWORD_HASH=${PASSWORD_HASH}
HERMES_PANEL_SESSION_SECRET=${SESSION_SECRET}
HERMES_GATEWAY_TOKEN=${GATEWAY_TOKEN}

# --- API key nhà cung cấp (panel tự ghi khi bạn lưu từ GUI) ---
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# DEEPSEEK_API_KEY=

# --- Plugin Zalo ---
# DÙNG SỐ ZALO PHỤ cho bot (API không chính thức, có rủi ro khoá tài khoản).
# OWNER_UID = tài khoản Zalo của sếp, panel tự điền khi bạn nhập số điện thoại.
ZALO_PERSONAL_OWNER_UID=
ZALO_PERSONAL_SIDECAR_PORT=3838
ZALO_PERSONAL_SESSION_DIR=/opt/data/zalo
ZALO_PERSONAL_ALLOW_ALL_USERS=true
# ZALO_OWNER_NICKNAME=sếp
EOF
  chmod 600 "${INSTALL_DIR}/.env"
  log "Đã ghi ${INSTALL_DIR}/.env mới"
else
  log "Giữ nguyên ${INSTALL_DIR}/.env, chỉ cập nhật khoá còn thiếu"
  set_env_line() {  # key value — ghi đè nếu có, thêm mới nếu chưa
    local key="$1" value="$2" file="${INSTALL_DIR}/.env"
    if grep -q "^${key}=" "$file"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
      echo "${key}=${value}" >> "$file"
    fi
  }
  set_env_line HERMES_HOME "${HERMES_HOME}"
  set_env_line HERMES_PANEL_PORT "${PANEL_PORT}"
  set_env_line HERMES_DASHBOARD_PORT "${DASHBOARD_PORT}"
  set_env_line HERMES_CHAT_URL "${CHAT_URL}"
  set_env_line HERMES_PANEL_USER "${ADMIN_USER}"
  set_env_line HERMES_PANEL_PASSWORD_HASH "${PASSWORD_HASH}"
  set_env_line HERMES_PANEL_SESSION_SECRET "${SESSION_SECRET}"
  set_env_line HERMES_GATEWAY_TOKEN "${GATEWAY_TOKEN}"
  grep -q '^ZALO_PERSONAL_OWNER_UID=' "${INSTALL_DIR}/.env" || cat >> "${INSTALL_DIR}/.env" <<'ZEOF'

# --- Plugin Zalo (bổ sung bởi installer) ---
ZALO_PERSONAL_OWNER_UID=
ZALO_PERSONAL_SIDECAR_PORT=3838
ZALO_PERSONAL_SESSION_DIR=/opt/data/zalo
ZALO_PERSONAL_ALLOW_ALL_USERS=true
ZEOF
fi

# ---- 8b. Mật khẩu cho chat UI --------------------------------------------
# Hermes >= 0.20 TỪ CHỐI bind chat UI ra ngoài loopback khi chưa cấu hình auth
# ("Refusing to bind dashboard to 0.0.0.0"); cờ --insecure nay chỉ là no-op.
# Nên muốn mở chat UI ra LAN thì phải đặt dashboard.basic_auth trong config.yaml.
# Dùng chung tài khoản/mật khẩu với panel để người dùng chỉ phải nhớ một bộ.
CHAT_AUTH_OK=false
if [[ "$CHAT_LOCAL" != "true" && "$SKIP_HERMES" != "true" ]]; then
  step "8b. Đặt mật khẩu cho chat UI"
  if grep -q "basic_auth" "${HERMES_HOME}/config.yaml" 2>/dev/null && [[ -z "$PASSWORD_PLAIN" ]]; then
    CHAT_AUTH_OK=true
    log "Chat UI đã có mật khẩu từ trước — giữ nguyên"
  elif [[ -n "$PASSWORD_PLAIN" ]]; then
    if (cd "${HERMES_SRC_DIR}" && env HERMES_HOME="${HERMES_HOME}" \
        CHAT_USER="${ADMIN_USER}" CHAT_PASS="${PASSWORD_PLAIN}" \
        "${HERMES_SRC_DIR}/.venv/bin/python" - <<'PYEOF' >>"${LOG_FILE}" 2>&1
import os, yaml
from plugins.dashboard_auth.basic import hash_password
path = os.path.join(os.environ["HERMES_HOME"], "config.yaml")
data = yaml.safe_load(open(path).read()) if os.path.exists(path) else {}
data = data if isinstance(data, dict) else {}
dash = data.get("dashboard") if isinstance(data.get("dashboard"), dict) else {}
dash["basic_auth"] = {
    "username": os.environ["CHAT_USER"],
    "password_hash": hash_password(os.environ["CHAT_PASS"]),
}
data["dashboard"] = dash
yaml.safe_dump(data, open(path, "w"), allow_unicode=True, sort_keys=False)
print("dashboard.basic_auth đã đặt")
PYEOF
    ); then
      CHAT_AUTH_OK=true
      log "Chat UI: đã đặt mật khẩu (tài khoản ${ADMIN_USER})"
    else
      log "CẢNH BÁO: không đặt được mật khẩu chat UI — sẽ chỉ mở ở 127.0.0.1"
    fi
  else
    log "CẢNH BÁO: chưa có mật khẩu chat UI. Chạy lại kèm --admin-pass để bật, tạm mở ở 127.0.0.1"
  fi
fi

# ---- 9. systemd -----------------------------------------------------------
step "9. Viết unit systemd"

# Chỉ bind ra LAN khi chat UI thực sự có mật khẩu — nếu không Hermes sẽ khởi
# động lại vô hạn và service không bao giờ lên.
if [[ "$CHAT_LOCAL" == "true" || "$CHAT_AUTH_OK" != "true" ]]; then
  DASHBOARD_BIND="127.0.0.1"
else
  DASHBOARD_BIND="0.0.0.0"
fi
DASHBOARD_ARGS="--no-open --host ${DASHBOARD_BIND} --port ${DASHBOARD_PORT}"

cat > /etc/systemd/system/hermes.target <<'EOF'
[Unit]
Description=Hermes Agent (gateway + chat UI + panel)
Wants=hermes-gateway.service hermes-dashboard.service hermes-panel.service
After=network-online.target

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/hermes-gateway.service <<EOF
[Unit]
Description=Hermes Agent — Messaging Gateway
After=network-online.target
Wants=network-online.target
PartOf=hermes.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/local/bin/hermes gateway run
Restart=always
RestartSec=5
# Sidecar Zalo (Node) là tiến trình con nên dùng chung hạn mức bộ nhớ này.
MemoryMax=1536M

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/hermes-dashboard.service <<EOF
[Unit]
Description=Hermes Agent — Chat UI
After=network-online.target
Wants=network-online.target
PartOf=hermes.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/local/bin/hermes dashboard ${DASHBOARD_ARGS}
Restart=always
RestartSec=5
MemoryMax=1024M

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/hermes-panel.service <<EOF
[Unit]
Description=Hermes LAN Panel (GUI quản lý)
After=network-online.target
Wants=network-online.target
PartOf=hermes.target

[Service]
Type=simple
User=root
WorkingDirectory=${PANEL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${PANEL_DIR}/.venv/bin/uvicorn hermes_panel.main:app --host 0.0.0.0 --port ${PANEL_PORT} --workers 1 --proxy-headers
Restart=always
RestartSec=10
MemoryMax=512M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ---- 10. Tường lửa (chỉ khi UFW đang bật) ---------------------------------
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  step "10. Mở cổng trên UFW"
  if [[ -n "$ALLOW_LAN" ]]; then
    ufw allow from "$ALLOW_LAN" to any port "${PANEL_PORT}" proto tcp comment 'hermes-panel' || true
    [[ "$CHAT_LOCAL" == "true" ]] || \
      ufw allow from "$ALLOW_LAN" to any port "${DASHBOARD_PORT}" proto tcp comment 'hermes-chat' || true
    log "Đã mở ${PANEL_PORT} (và chat UI) cho dải ${ALLOW_LAN}"
  else
    ufw allow "${PANEL_PORT}/tcp" comment 'hermes-panel' || true
    [[ "$CHAT_LOCAL" == "true" ]] || ufw allow "${DASHBOARD_PORT}/tcp" comment 'hermes-chat' || true
    log "Đã mở ${PANEL_PORT}/tcp — nên siết lại bằng --allow-lan <CIDR>"
  fi
else
  log "UFW không bật — bỏ qua bước tường lửa"
fi

# ---- 11. Khởi động --------------------------------------------------------
step "11. Bật và khởi động dịch vụ"
systemctl enable hermes.target hermes-panel.service >/dev/null 2>&1 || true
systemctl restart hermes-panel.service
if [[ "$SKIP_HERMES" != "true" ]]; then
  systemctl enable hermes-gateway.service hermes-dashboard.service >/dev/null 2>&1 || true
  systemctl restart hermes-dashboard.service || log "CẢNH BÁO: chat UI chưa chạy được"
  systemctl restart hermes-gateway.service   || log "CẢNH BÁO: gateway chưa chạy (chưa cấu hình model là bình thường)"
fi

# ---- 12. Kiểm tra sức khoẻ ------------------------------------------------
step "12. Kiểm tra"
PANEL_OK=false
for _ in $(seq 1 15); do
  if curl -sf "http://127.0.0.1:${PANEL_PORT}/health" >/dev/null 2>&1; then PANEL_OK=true; break; fi
  sleep 2
done
CHAT_OK=false
if [[ "$CHAT_LOCAL" != "true" ]]; then
  curl -sf -o /dev/null --max-time 5 "http://${LAN_IP}:${DASHBOARD_PORT}/" && CHAT_OK=true || true
else
  curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:${DASHBOARD_PORT}/" && CHAT_OK=true || true
fi

svc() { systemctl is-active --quiet "$1" && echo "OK" || echo "CHƯA CHẠY"; }

log ""
log "============================================================"
log "  Cài đặt hoàn tất"
log "============================================================"
log "  Dịch vụ:"
log "    hermes-panel      : $(svc hermes-panel.service)"
log "    hermes-gateway    : $(svc hermes-gateway.service)"
log "    hermes-dashboard  : $(svc hermes-dashboard.service)"
log ""
log "  PANEL (trỏ Nginx Proxy Manager vào đây):"
log "    http://${LAN_IP}:${PANEL_PORT}     $([[ "$PANEL_OK" == true ]] && echo '(đã phản hồi)' || echo '(chưa phản hồi — xem journalctl -u hermes-panel)')"
log "    Tài khoản : ${ADMIN_USER}"
if [[ -n "$PASSWORD_PLAIN" ]]; then
log "    Mật khẩu  : ${PASSWORD_PLAIN}     <-- LƯU LẠI NGAY, chỉ hiện một lần"
else
log "    Mật khẩu  : (giữ nguyên mật khẩu cũ)"
fi
log ""
log "  CHAT UI: ${CHAT_URL}  $([[ "$CHAT_OK" == true ]] && echo '(đã phản hồi)' || echo '(chưa phản hồi)')"
if [[ "$DASHBOARD_BIND" == "0.0.0.0" ]]; then
log "    Đăng nhập chat UI: dùng chung tài khoản/mật khẩu của panel ở trên."
else
log "    Chat UI chỉ nghe 127.0.0.1 (chưa đặt được mật khẩu hoặc bật --chat-local)."
log "    Xem tạm bằng SSH tunnel:  ssh -L ${DASHBOARD_PORT}:127.0.0.1:${DASHBOARD_PORT} root@${LAN_IP}"
fi
log ""
log "  Trên Nginx Proxy Manager:"
log "    Panel   -> Forward: ${LAN_IP}:${PANEL_PORT}   (bật Websockets)"
log "    Chat UI -> Forward: ${LAN_IP}:${DASHBOARD_PORT}  (bật Websockets)"
log ""
log "  Bước tiếp theo: mở panel → đăng nhập → 'Đăng nhập ChatGPT' → 'Kết nối Zalo'."
log "  Log cài đặt: ${LOG_FILE}"
log "============================================================"
