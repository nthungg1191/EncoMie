# Auto Video Editor

Một ứng dụng desktop giúp tạo video từ file âm thanh (mp3, m4a, wav, aac) và phụ đề SRT, bằng cách:

- **Chọn ngẫu nhiên** một video nền từ thư mục
- **Ghép âm thanh + SRT** thành cặp video + phụ đề
- **Render** bằng FFmpeg (hỗ trợ GPU NVENC hoặc CPU)
- **Chỉnh sửa style phụ đề** trực tiếp trong giao diện: font, màu sắc, đường viền, nền, bóng

Ứng dụng được viết bằng **Python 3 + PyQt6**, gọi FFmpeg từ thư mục `bin/` hoặc từ PATH hệ thống.

---

## Cấu trúc dự án

```
auto_video_editor/
├── bin/                           # FFmpeg & FFprobe (nếu có)
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── core/                          # Logic xử lý chính
│   ├── video_processor.py         # Render pipeline, FFmpeg wrapper
│   ├── srt_service.py            # Đọc/ghi/sửa file SRT
│   ├── subtitle_model.py          # Kiểu dữ liệu phụ đề
│   ├── style_preset_service.py    # Lưu/tải preset style
│   └── worker.py                  # Qt worker thread cho render
├── ui/                            # Giao diện PyQt6
│   ├── main_window.py             # Cửa sổ chính (3-panel)
│   ├── subtitle_preview_widget.py # Preview phụ đề
│   └── subtitle_editor_widget.py  # Widget chỉnh sửa
├── presets/
│   └── subtitle_presets.json      # Các preset style phụ đề
├── utils/
│   ├── gpu_detect.py              # Phát hiện GPU & NVENC
│   └── settings.py                # Cấu hình lưu trữ
├── main.py                        # Entry point
└── README.md
```

---

## Tính năng chính

### Ghép video nền + âm thanh + phụ đề

- Chọn thư mục chứa file âm thanh và thư mục chứa file SRT
- Tự động ghép cặp audio + SRT theo tên file (theo thứ tự hoặc fuzzy match)
- Chọn video nền ngẫu nhiên từ thư mục (hoặc chọn video cố định)
- Điều chỉnh tốc độ video nền (lam chậm/chạy nhanh theo %)
- Hỗ trợ nhiều video nền, xử lý tuần tự theo hàng đợi

### Chỉnh sửa style phụ đề

| Thành phần | Tùy chọn |
|------------|----------|
| Font       | Arial, Roboto, Montserrat, Open Sans, Verdana, Tahoma, Georgia, Times New Roman... |
| Kích thước | 12 - 100 px |
| Màu chữ   | Màu sắc tùy chọn (HEX) |
| Đường viền | Màu + độ rộng |
| Nền        | Màu nền + độ trong + bo góc + padding |
| Bóng       | Màu + độ trong + góc + khoảng cách + blur |
| Vị trí     | Giữa màn hình / Dưới giữa / Trên giữa |

Có sẵn **5 preset** style: Mặc định, Sáng, To, newpreset, tbn1. Có thể lưu/tải preset tùy ý.

### Render

- **Codec**: H.265 HEVC (GPU/CPU), H.264 AVC (GPU/CPU)
- **GPU**: Tự động phát hiện NVIDIA GPU & NVENC
- **Điều khiển**: Tạm dừng, tiếp tục, dừng render
- **Log**: Xem FFmpeg log trực tiếp trong giao diện
- **Xếp hàng**: Render nhiều cặp video/audio theo thứ tự
- **Tiến trình**: Thanh progress theo thời gian thực

---

## Cài đặt

### Yêu cầu

- Python 3.8+
- PyQt6
- FFmpeg & FFprobe (trong `bin/` hoặc PATH hệ thống)

### Cài đặt thư viện

```bash
pip install PyQt6
```

### Khởi động

```bash
python main.py
```

### FFmpeg

Nếu FFmpeg chưa có trong PATH, copy `ffmpeg.exe` và `ffprobe.exe` vào thư mục `bin/`. Ứng dụng sẽ ưu tiên sử dụng các file này.

---

## Giao diện

Giao diện gồm **3 panel ngang**:

| Panel trái | Panel giữa | Panel phải |
|------------|------------|------------|
| Chọn thư mục audio / SRT / video nền | Chỉnh sửa style phụ đề + Preview | Cấu hình render + Log + Nút render |

---

## Preview phụ đề

Widget preview hiển thị phụ đề với đầy đủ các thuộc tính: fill, stroke, background, shadow. Thư mục `presets/subtitle_presets.json` lưu các preset style, có thể chỉnh sửa trực tiếp bằng giao diện.

---

## Changelog

### [Unreleased]

### [1.1.0] - 2026-06-15

#### Fixed
- **Escape ký tự đặc biệt trong tên file SRT**: Sửa lỗi FFmpeg không mở được file SRT có dấu nháy đơn (apostrophe) trong tên file. Trước đây, file như `001_ I Overheard Her Tell Her Ex 'I Still Love You.'...srt` sẽ gây lỗi "Unable to open" do FFmpeg interpret sai cú pháp filter. Đã thêm escape `'` → `'\''` trong `_build_subtitle_filter()`.


---

### [1.0.0] - 2026-06-14

#### Added
- Ứng dụng desktop Auto Video Editor
- Giao diện PyQt6 với 3 panel ngang
- Chọn thư mục audio, SRT, video nền
- Ghép cặp audio + SRT theo tên file
- Chọn video nền ngẫu nhiên từ thư mục
- Điều chỉnh tốc độ video nền (%)
- Chỉnh sửa style phụ đề: font, màu, viền, nền, bóng, vị trí
- 5 preset style phụ đề có sẵn
- Render với FFmpeg (GPU NVENC / CPU)
- Hỗ trợ codec H.265 HEVC và H.264 AVC
- Tự động phát hiện NVIDIA GPU
- Điều khiển render: tạm dừng, tiếp tục, dừng
- Hiển thị log FFmpeg trực tiếp
- Thanh tiến trình real-time

---

## Từ khóa

PyQt6, FFmpeg, NVENC, subtitle, SRT, video editor, GPU encoding, HEVC, H.264
