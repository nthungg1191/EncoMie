# 📜 Nhật Ký Cập Nhật Phiên Bản (EncoMie Release Notes)

## 🚀 Phiên bản 1.6 (Version 1.6 - License Hardening, Subtitle Fidelity & Performance)
*Ngày cập nhật: 04/09/2026*

---

### 🔐 1. Nâng cấp Hệ thống Bản quyền (License Security)
- **Token ký Ed25519**: Server trả về *license token* ký bằng khóa bất đối xứng; client chỉ giữ **public key** nhúng sẵn. Không còn dùng chung secret HMAC cho response ⇒ **không thể dựng server giả**.
- **Đồng hồ offline = `exp` của token** (UTC tuyệt đối, ~48h). Gỡ bỏ hoàn toàn cơ chế "grace period = `now − saved_at`" và heuristic phát hiện xoay đồng hồ.
- **Request bắt buộc ký**: HMAC-SHA256 + `nonce` dùng một lần + `timestamp` ±120s. Server từ chối mọi request không ký / replay.
- **Ràng buộc thiết bị thật (server)**: bảng `license_devices` enforce `max_devices`, có trần lifetime activation, **fuzzy HWID match** (đổi MAC + hostname vẫn nhận, đổi MachineGuid thì không).
- **`core/entitlements.py` (mới)**: kẹp `RenderConfig` theo `features` trong token *trước mỗi lần render* — không token hợp lệ ⇒ coi như gói `free` (tắt NVENC → `libx264`, giới hạn số layer, bật cờ watermark). Patch `is_valid=True` một mình không mở khóa Pro.
- **Secrets rời khỏi repo**: nạp qua `wrangler secret` (xóa `ADMIN_TOKEN`/`SERVER_SECRET` khỏi `wrangler.toml`).
- Server bản quyền: thêm rate-limit per-key trên Cloudflare KV, cron quét bất thường 30 phút, CORS thắt lại cho `/api/admin/*`.

### 📝 2. Sửa Tỉ lệ & Bóng đổ Phụ đề khi Render (Subtitle Fidelity)
- **Khớp tỉ lệ preview ↔ video xuất**: đường phụ đề không-bo-góc trước đây đưa thẳng `.srt` cho filter `subtitles` của FFmpeg → libass tự tạo ASS với `PlayResY ≈ 288` → chữ/lề **to gấp ~2.5×** so với tab Edit Sub. Nay luôn chuyển sang `.ass` có `PlayResX/Y: 1280/720` qua hàm mới `convert_srt_to_ass_simple`.
- **Sửa "đuôi bóng" của hộp phụ đề**: với nền hộp (`BorderStyle=3`), ASS `Shadow>0` vẽ bóng bằng **màu hộp** lệch xuống-phải → ra một dải đặc vài px. Nay hộp dùng `Shadow=0`; đường không-nền vẽ bóng đúng trên **chữ** với `shadow_color`/`shadow_opacity`.
- **Sửa bug canh lề trên/giữa**: bỏ bảng remap keypad→SSA-legacy (sai trong ngữ cảnh ASS v4+); dùng thẳng mã numpad 1–9.

### 📐 3. Nâng Kích cỡ Layer lên 150%
- Ô "Cỡ (%)" của từng layer: `10–100` → `10–150`. Cập nhật đồng bộ 5 chỗ: spinbox, ngưỡng phần trăm ở 2 preview (Edit Video / Edit Sub), clamp kéo–giãn, và lúc render (`video_processor.py`). Vùng 101–150 giờ luôn là **phần trăm** khung hình.

### ⚡ 4. Tối ưu Hiệu năng & Độ mượt UI
- **Hết đơ định kỳ**: watchdog anti-tamper (`scan_suspicious_processes` ~175ms) và heartbeat bản quyền (request mạng) trước đây chạy **trên UI thread mỗi 3s / 2 phút**. Nay chuyển sang `QThreadPool` nền (`_BgProbeTask`, `_LicenseCheckTask`), chu kỳ 5s.
- **Khởi động nhanh hơn ~1.3s**: bỏ `detect_system_info()` chặn trong `MainWindow.__init__` (**1796ms → ~520ms**). Viết lại `detect_system_info` dùng Win32 ctypes (`GlobalMemoryStatusEx`, `GetSystemTimes`) + registry thay cho 4× `wmic` (**~1150ms → ~30ms**).
- **License check trong batch**: kiểm 1 lần đầu batch + tối đa 1 lần/phút (trước đây mỗi video: ~175ms scan + 1 request mạng).
- **Encoder**: NVENC `-preset p1 → p4` (chất lượng tốt hơn nhiều, tốc độ GPU gần như y hệt). Bỏ hệ số luồng `×1.2` gây over-subscribe; `-filter_threads = (số nhân − 2) // số job song song`; encoder `-threads 0`; bỏ `-threads` trước mỗi input. CPU x264 `fast → veryfast`.
- **Sạch log**: 53 lệnh `print()` chẩn đoán trong đường render → logger `encomie.video` (tắt mặc định, bật bằng `ENCOMIE_DEBUG=1`). Tránh lỗi ghi stdout trong build no-console.

### 📦 5. Đóng gói Bảo mật hơn (`build_nuitka.py` mới)
- Script đóng gói bằng **Nuitka** (`--standalone`, compiler `zig` tự tải) — biên dịch Python → C, **không còn bytecode `.pyc` để giải ngược**. `build.py` (PyInstaller) giữ làm dự phòng.
---

## 🚀 Phiên bản 1.5 (Version 1.5 - Modern Light Theme & UI Enhancement)
*Ngày cập nhật: 28/07/2026*

---

### 🎨 1. Tải Tạo Giao Diện Sáng Hiện Đại (Modern Light Theme UI Redesign)
- **Hệ thống màu sắc mới**: Chuyển sang tone màu sáng hiện đại chuẩn macOS/iOS với màu nền chính `#F8FAFC`, đường viền mịn `#E2E8F0`, màu tương tác xanh iOS `#007AFF` và chữ sắc nét `#0F172A`.
- **Tối ưu hóa mã nguồn QSS**: Gom và nhúng trực tiếp toàn bộ chuỗi định dạng StyleSheet vào hàm `MainWindow._apply_theme()`, loại bỏ file phụ giúp dự án gọn gàng, khởi chạy nhanh nhẹn.

### 🧭 2. Tái Cấu Trúc Thanh Navigation & Panel Trái
- **Căn lề góc trái**: Đưa 2 nút quản lý tiến trình **📂 Mở dự án** và **💾 Lưu dự án** về sát góc trái ngoài cùng.
- **Thống nhất ô chọn thư mục Xuất (Output Folder)**: Loại bỏ ô chọn "Xuất:" dư thừa ở cột trái của chế độ `🎬 Edit Video Scale`. Cả 2 chế độ (Biên tập Phụ đề & Biên tập Video) giờ đây dùng chung 1 thư mục xuất duy nhất trong tab **Cài đặt xuất** (`self.pick_output`), giúp giao diện cực kỳ tối giản.
- **Căn CHÍNH GIỮA cụm chuyển chế độ (Mode Switcher)**:
  - Đưa cụm nút chuyển mode **`📝  Biên tập Phụ đề`** và **`🎬  Edit Video Scale`** vào **chính giữa trung tâm** thanh Header với khoảng giãn cách cân đối 2 bên.
  - Tối ưu nhãn nút bấm và khoảng lề padding (`white-space: nowrap`), loại bỏ 100% tình trạng che khuất hoặc mất chữ.

### 📊 3. Khôi Phục Bảng Dánh Sách Tệp Tật Trung Mật Độ Cao (High-Density Grid Table)
- **Hiển thị 23+ dòng cùng lúc**: Khôi phục bảng dữ liệu lưới `PairTable` gọn gàng (`row height: 26px`), cho phép người dùng quan sát số lượng lớn tệp tin trên một màn hình mà không cần cuộn nhiều.
- **Màu sắc thông tin rõ ràng & Bổ sung trạng thái `⚠️ Lệch file`**:
  - Cột **AUDIO / MEDIA**: Nhãn file hiển thị màu xanh lam tươi `#007AFF`.
  - Cột **PHỤ ĐỀ (.SRT)**: Nhãn file hiển thị màu xanh lam tươi `#007AFF`.
  - Cột **TRẠNG THÁI**: `✓ Khớp` (Xanh ngọc `#10B981`), `⚠️ Lệch file` (Màu cam hổ phách `#D97706` khi số hiệu hoặc tên tệp audio và phụ đề không khớp nhau), `✗ Thiếu file` (Màu đỏ `#EF4444`).
- **Tự động nhận diện lệch số hiệu/tệp**: Hàm `build_pairs()` tự động trích xuất chỉ số (ví dụ: Audio `[226]` vs SRT `228`) để phát hiện và cảnh báo `⚠️ Lệch file` lập tức.
- **Sửa lỗi định dạng chuỗi chỉ số**: Thêm bộ xử lý `try ... except` ép kiểu an toàn khi format chỉ số `pair.index`, khắc phục triệt để lỗi `Unknown format code 'd' for object of type 'str'` khi quét danh sách lớn.

### 📐 4. Tối Ưu Bố Cục Khi Phóng To Màn Hình (Fullscreen Layout Stretch Fix)
- **Bổ sung Bottom Stretch Spacers (`addStretch(1)`)**: Thêm khoảng dồn ở cuối các bảng điều khiển (`VideoLayerConfigWidget`, `SubtitleStyleEditor`, `Tab Export`).
- **Khắc phục khoảng hổng**: Khi phóng to cửa sổ (Maximized / Fullscreen), tất cả các hàng nút bấm & ô nhập liệu vẫn gom khít khao ở phía trên, triệt tiêu hiện tượng các ô bị giãn xa nhau ra.
- **Cuộn dọc bảng Biên tập Phụ đề (`SubtitleStyleEditor`)**: Chuyển các nhóm tùy chỉnh (Font, Stroke, BG, Shadow, Position 3x3 Grid) sang bố cục cột dọc cuộn mượt mượt, tràn 100% chiều rộng cột phải.

---

## 🛠️ Hướng Dẫn Khởi Chạy
```bash
python main.py
```
