# Xưởng KOL — Văn phòng (portal)

Cổng khai báo đa thành viên cho Xưởng KOL Studio: đăng nhập bằng token, khai KOL / Sản phẩm / Kênh,
soạn kịch bản vào kanban duyệt, Thư viện Media (video Drive + trạng thái đăng + chỉ số).
Đồng bộ 2 chiều với máy Xưởng qua sync agent (PC chủ động gọi ra — không mở cổng vào PC).

Deploy: stack Docker qua Arcane — xem `HUONG-DAN-ARCANE.md`.
- Env bắt buộc: `SYNC_TOKEN` (chuỗi mạnh, chỉ cấp cho máy Xưởng)
- Data nằm trong volume `xuong_data` (/data trong container)
- Tạo user: `docker exec -it xuong-portal python create_user.py <ten> --role admin|member`
