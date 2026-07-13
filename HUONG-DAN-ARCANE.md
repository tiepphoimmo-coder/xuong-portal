# Đưa "Xưởng KOL — Văn phòng" lên VPS qua Arcane

Gói này dựng portal (đăng nhập thành viên, khai KOL/SP/kịch bản, kanban duyệt,
Thư viện Media) chạy Docker trên VPS — quản lý bằng Arcane, ra internet qua
subdomain (đề xuất `xuong.tiepphoi.com`, DNS Cloudflare như dangbai).

## 0. Chuẩn bị gói nguồn (làm trên PC — 1 lệnh)
Chạy `TAO-GOI-VPS.bat` trong thư mục này → sinh `xuong-portal-vps.tar.gz`
(chứa Dockerfile + compose + code studio, KHÔNG kèm data/secrets/não).

## 1. Đưa gói lên VPS
Cách A (SSH/SFTP): `scp xuong-portal-vps.tar.gz user@VPS:/opt/xuong-portal/`
rồi trên VPS: `cd /opt/xuong-portal && tar xzf xuong-portal-vps.tar.gz`
Cách B: dùng file manager nếu Arcane/panel có.

## 2. Tạo stack trong Arcane
1. Arcane → **Projects/Stacks → New** → trỏ tới `/opt/xuong-portal`
   (hoặc dán nội dung `docker-compose.yml`).
2. Thêm biến môi trường **SYNC_TOKEN** = chuỗi mạnh (vd `openssl rand -hex 24`).
   Token này CHỈ dùng cho máy Xưởng PC gọi đồng bộ — không phát cho thành viên.
3. **Deploy** — Arcane tự build image từ Dockerfile.

## 3. Trỏ domain (reverse proxy + Cloudflare)
- Reverse proxy đang có trên VPS (Nginx Proxy Manager / Traefik / Caddy —
  cái đang route dangbai.tiepphoi.com) → thêm host `xuong.tiepphoi.com`
  → `http://127.0.0.1:8091` (websocket không cần).
  - Traefik: bỏ `ports` trong compose, mở khối `labels` (đã ghi sẵn, sửa domain).
- Cloudflare DNS: thêm record `xuong` → IP VPS, bật proxy (mây cam) như dangbai.

## 4. Tạo tài khoản
```bash
docker exec -it xuong-portal python create_user.py tiepphoi --role admin
docker exec -it xuong-portal python create_user.py <ten-thanh-vien> --role member
```
Token in ra 1 lần — gửi riêng cho từng người.

## 5. Nối Xưởng PC vào (trên PC)
1. Sửa `TiepPhoi Space/studio/sync.env`:
   ```
   PORTAL_URL=https://xuong.tiepphoi.com
   SYNC_TOKEN=<đúng token ở bước 2>
   LOCAL_URL=http://127.0.0.1:8090
   ```
2. Đổ dữ liệu lần đầu: `python studio/sync_agent.py --seed --once`
   (⚠ luôn kèm `--once` — seed không tự thoát)
3. Chạy thường trực: bấm `START-SYNC.bat` (kèm START-STUDIO.bat).

## 6. Kiểm tra nhanh
- `https://xuong.tiepphoi.com` ra trang đăng nhập "Xưởng KOL Văn phòng".
- Đăng nhập admin thấy KOL/SP/kịch bản từ Xưởng (sau seed) + ảnh hiển thị.
- Thành viên đăng nhập chỉ thấy dữ liệu của mình.

## Cập nhật phiên bản sau này
Chạy lại `TAO-GOI-VPS.bat` → upload đè → Arcane **Rebuild/Redeploy** stack.
Data nằm trong volume `xuong_data` — không mất khi rebuild.

## An toàn
- KHÔNG mở cổng 8091 ra ngoài (compose đã bind 127.0.0.1) — chỉ đi qua proxy HTTPS.
- Trên VPS KHÔNG có: não brain/, API key, Flow, video gốc. Bị xâm nhập chỉ mất khai báo.
- PC chỉ gọi RA — không mở cổng nào vào PC.
