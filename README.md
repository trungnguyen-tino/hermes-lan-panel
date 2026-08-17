# hermes-lan-panel

Cài **Hermes Agent** + **GUI quản lý** cho VPS/VM trong mạng nội bộ (vd `192.168.232.79`),
truy cập qua **Nginx Proxy Manager**. Không Caddy, không Let's Encrypt, không cần domain công khai.

Giao diện dựng theo đúng design system của [openclaw-control-panel](https://github.com/trungnguyen-tino/openclaw-control-panel)
(sidebar 260px chia nhóm, topbar breadcrumb + stat pill, thẻ bo tròn shadow mềm, meter card, màn hình
đăng nhập split-hero) nhưng viết bằng HTML/CSS/JS thuần — **không npm, không build, không CDN**, nên
cài nhanh và chạy được cả khi VPS không ra Internet.

GUI chỉ gồm những thứ cần dùng hằng ngày:

| Thẻ | Làm được gì |
|---|---|
| **Trạng thái dịch vụ** | Xem gateway / chat UI / panel đang chạy hay không, Khởi động lại – Dừng – Chạy |
| **ChatGPT** | Đăng nhập tài khoản ChatGPT (OAuth device-code) để bot dùng làm bộ não — không cần API key |
| **Zalo bot** | Quét QR đăng nhập bot, nhập số Zalo của sếp làm chủ bot, ngắt kết nối |
| **Model & API key** | Đổi provider/model, lưu + kiểm tra API key (OpenAI, Anthropic, DeepSeek, Gemini, OpenRouter, Groq, xAI) |
| **Nhật ký** | Đọc log journalctl của từng service ngay trên web |

Mỗi mục là một trang riêng trong sidebar; trang **Bảng điều khiển** gộp meter RAM/ổ đĩa/tải/uptime,
danh sách dịch vụ và tóm tắt kết nối.

## Cài đặt

Trên VPS (Ubuntu 22.04/24.04, chạy bằng **root**):

```bash
curl -fsSL https://raw.githubusercontent.com/trungnguyen-tino/hermes-lan-panel/main/install.sh | bash
```

Đặt sẵn mật khẩu panel và giới hạn tường lửa theo dải LAN:

```bash
curl -fsSL https://raw.githubusercontent.com/trungnguyen-tino/hermes-lan-panel/main/install.sh \
  | bash -s -- --admin-pass 'MatKhauCuaSep' --allow-lan 192.168.232.0/24
```

Khoảng 5–10 phút (chủ yếu là build Hermes + npm). Kết thúc script in ra:

```
PANEL: http://192.168.232.79:8088
  Tài khoản : admin
  Mật khẩu  : <chỉ hiện một lần — lưu lại ngay>
CHAT UI: http://192.168.232.79:9119
```

### Cờ hay dùng

| Cờ | Ý nghĩa |
|---|---|
| `--panel-port 8088` | Cổng GUI (Nginx Proxy Manager trỏ vào đây) |
| `--admin-user admin` | Tài khoản đăng nhập panel |
| `--admin-pass '...'` | Mật khẩu panel (bỏ trống = tự sinh, in ra cuối script) |
| `--chat-url https://chat.cty.vn` | URL nút "Mở chat UI" (khi đã proxy qua NPM) |
| `--chat-local` | Chat UI chỉ nghe 127.0.0.1 (phải SSH tunnel mới xem được) |
| `--allow-lan 192.168.232.0/24` | Chỉ mở cổng cho dải LAN này (khi UFW đang bật) |
| `--skip-zalo` | Không cài plugin Zalo |
| `--skip-hermes` | Chỉ cài/nâng cấp panel |

## Cấu hình Nginx Proxy Manager

**Panel** — Proxy Host:

- Domain: `hermes.cty.vn`
- Forward: `192.168.232.79` port `8088`, scheme `http`
- Bật **Websockets Support** và **Block Common Exploits**

**Chat UI** (tuỳ chọn) — Proxy Host:

- Domain: `chat.cty.vn`
- Forward: `192.168.232.79` port `9119`, scheme `http`
- Bật **Websockets Support**

Chat UI có trang đăng nhập riêng của Hermes, **dùng chung tài khoản/mật khẩu với panel**
(installer ghi `dashboard.basic_auth` vào `config.yaml`). Không cần chat UI thì cài lại
với `--chat-local` — khi đó nó chỉ nghe `127.0.0.1`.

## Dùng hằng ngày

1. Mở panel → đăng nhập.
2. **ChatGPT**: bấm *Đăng nhập ChatGPT* → mở link hiện ra trên máy mình → nhập mã → panel tự nhận (bot chuyển sang provider `openai-codex`, model `gpt-5.5`).
   Không dùng ChatGPT thì sang thẻ *Model & API key* nhập key provider khác.
3. **Zalo**: bấm *Kết nối Zalo* → quét QR bằng **số Zalo phụ** (số này thành bot) → nhập **số Zalo của sếp** → panel lưu chủ bot, bật plugin và khởi động lại gateway.
4. Nhắn cho bot từ Zalo của sếp để kiểm tra.

> ⚠️ Zalo Web API là API **không chính thức**. Luôn dùng số phụ cho bot — gửi tin/kết bạn hàng loạt có rủi ro khoá tài khoản.

## Nâng cấp

```bash
cd /opt/hermes-panel && git pull && bash install.sh --skip-hermes   # chỉ panel
bash /opt/hermes-panel/install.sh                                    # cả Hermes + panel
```

Cài lại nhiều lần vô hại: `.env` được giữ nguyên, mật khẩu cũ không bị đổi (trừ khi truyền `--admin-pass`).

## Kiến trúc

```
Nginx Proxy Manager
   │  http
   ├── :8088  hermes-panel.service     GUI + API  (FastAPI, có đăng nhập)
   └── :9119  hermes-dashboard.service Chat UI của Hermes (không mật khẩu)

           hermes-gateway.service      Bot chạy nền
              └── sidecar Zalo (Node, 127.0.0.1:3838) — tiến trình con
```

| Đường dẫn | Nội dung |
|---|---|
| `/opt/hermes/.env` | Cấu hình + mật khẩu panel (bcrypt) + API key — systemd nạp cho cả 3 service |
| `/opt/hermes/hermes-agent/` | Mã nguồn Hermes (git + venv riêng) |
| `/opt/hermes-panel/` | Panel này (git + venv riêng) |
| `/root/.hermes/` | `HERMES_HOME`: `config.yaml`, `auth.json`, sessions, plugin Zalo |
| `/var/log/hermes-lan-install.log` | Nhật ký cài đặt |

Ba điểm kỹ thuật panel phải xử lý đúng, đừng sửa nếu chưa nắm:

1. `auth.json` → `active_provider` **được Hermes ưu tiên hơn** `config.yaml` → `model.provider`.
   Đổi provider mà không đồng bộ trường này thì bot vẫn chạy Codex như cũ.
2. Plugin Zalo chỉ tự chạy sidecar khi đã có `ZALO_PERSONAL_OWNER_UID`, nhưng UID chỉ biết
   được **sau** khi quét QR → panel tự spawn sidecar cho bước QR rồi bàn giao lại cho gateway
   (session lưu trên đĩa nên không phải quét lại).
3. Với Codex, `model.default` **không được rỗng** và phải nằm trong catalog ChatGPT
   (`gpt-5.5`, `gpt-5.4`…) — rỗng hoặc slug lạ sẽ làm hỏng cron job.

## Xử lý sự cố

```bash
systemctl status hermes-panel hermes-gateway hermes-dashboard
journalctl -u hermes-gateway -f          # log bot
journalctl -u hermes-panel -n 100        # log panel
curl http://127.0.0.1:8088/health        # panel còn sống?
```

| Triệu chứng | Cách xử lý |
|---|---|
| Quên mật khẩu panel | `bash /opt/hermes-panel/install.sh --skip-hermes --admin-pass 'MatKhauMoi'` |
| Bấm "Kết nối Zalo" báo sidecar chưa sẵn sàng | `cd /root/.hermes/plugins/zalo-personal/sidecar && npm install` rồi thử lại |
| Không đọc được link device-code của ChatGPT | Xem `journalctl -u hermes-panel`; hoặc dùng ô *dán sẵn auth.json* trong thẻ ChatGPT |
| Gateway `activating`/lỗi liên tục | Thường do chưa chọn model — vào thẻ *Model & API key* chọn provider rồi lưu |
| `hermes-dashboard` khởi động lại liên tục | Log báo *Refusing to bind dashboard to 0.0.0.0* → chưa có mật khẩu chat UI. Chạy lại installer kèm `--admin-pass '...'` |
| Quên mật khẩu chat UI | Nó luôn bằng mật khẩu panel; đặt lại cả hai bằng `--admin-pass` |

## Phát triển

```bash
cd panel
uv venv --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q          # 61 test
```

Chạy thử panel không cần VPS:

```bash
HERMES_PANEL_ENV_FILE=/đường/dẫn/panel.env .venv/bin/uvicorn hermes_panel.main:app --port 8099
```

## Ghi chú bảo mật

- Panel có đăng nhập riêng (bcrypt cost 12, session cookie ký HMAC, khoá 10 lần sai/15 phút mỗi IP).
- API key hiển thị dạng che (`****1234`), không bao giờ trả về nguyên văn.
- Panel chạy `root` (cần `systemctl`) — chỉ mở trong LAN hoặc sau Access List của NPM, đừng đưa thẳng ra Internet.
- Chat UI có đăng nhập riêng của Hermes (mật khẩu băm scrypt trong `config.yaml`), dùng chung tài khoản với panel.
- Hermes ≥ 0.20 **từ chối** mở chat UI ra ngoài `127.0.0.1` khi chưa cấu hình auth; cờ `--insecure` cũ nay vô hiệu.

## Đã kiểm chứng

Cài trọn vẹn trên Ubuntu 24.04.4 (4GB RAM) với **Hermes Agent v0.20.2**, đường truyền ~200KB/s:
3 service chạy ổn định, panel đăng nhập được từ LAN, luồng device-code ChatGPT trả về URL + mã thật,
luồng Zalo spawn được sidecar và trả về ảnh QR.

MIT. Hermes Agent là sản phẩm của Nous Research (MIT), dự án này không liên kết với họ.
