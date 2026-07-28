# 📜 Nhật Ký Cập Nhật Phiên Bản (EncoMie Release Notes)

## 🚀 Phiên bản 1.5 (Version 1.5 - Modern Light Theme & UI Enhancement)
*Ngày cập nhật: 28/07/2026*

---

### 🎨 1. Tải Tạo Giao Diện Sáng Hiện Đại (Modern Light Theme UI Redesign)
- **Hệ thống màu sắc mới**: Chuyển sang tone màu sáng hiện đại chuẩn macOS/iOS với màu nền chính `#F8FAFC`, đường viền mịn `#E2E8F0`, màu tương tác xanh iOS `#007AFF` và chữ sắc nét `#0F172A`.
- **Tối ưu hóa mã nguồn QSS**: Gom và nhúng trực tiếp toàn bộ chuỗi định dạng StyleSheet vào hàm `MainWindow._apply_theme()`, loại bỏ file phụ giúp dự án gọn gàng, khởi chạy nhanh nhẹn.

### 🧭 2. Tái Cấu Trúc Thanh Navigation (Header Bar Rearrangement)
- **Căn lề góc trái**: Đưa 2 nút quản lý tiến trình **📂 Mở dự án** và **💾 Lưu dự án** về sát góc trái ngoài cùng.
- **Căn CHÍNH GIỮA cụm chuyển chế độ (Mode Switcher)**:
  - Đưa cụm nút chuyển mode **`📝  Biên tập Phụ đề`** và **`🎬  Edit Video Scale`** vào **chính giữa trung tâm** thanh Header với khoảng giãn cách cân đối 2 bên.
  - Tối ưu nhãn nút bấm và khoảng lề padding (`white-space: nowrap`), loại bỏ 100% tình trạng che khuất hoặc mất chữ.

### 📊 3. Khôi Phục Bảng Dánh Sách Tệp Tật Trung Mật Độ Cao (High-Density Grid Table)
- **Hiển thị 23+ dòng cùng lúc**: Khôi phục bảng dữ liệu lưới `PairTable` gọn gàng (`row height: 26px`), cho phép người dùng quan sát số lượng lớn tệp tin trên một màn hình mà không cần cuộn nhiều.
- **Màu sắc thông tin rõ ràng**:
  - Cột **AUDIO / MEDIA**: Nhãn file hiển thị màu xanh lam tươi `#007AFF`.
  - Cột **PHỤ ĐỀ (.SRT)**: Nhãn file hiển thị màu xanh lam tươi `#007AFF`.
  - Cột **TRẠNG THÁI**: `✓ Khớp` màu xanh lá ngọc `#10B981`, thông báo lỗi màu đỏ `#EF4444`.
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
