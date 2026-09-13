# Mã lỗi & Trạng thái (Error / Status Code Reference)

Tài liệu tra cứu các mã/thông báo lỗi người dùng có thể gặp trong EncoMie — dùng cho
hỗ trợ kỹ thuật và debug. Từ bản có log rút gọn (xem cuối file), người dùng chỉ thấy
trạng thái + lỗi ngắn gọn; tài liệu này giải thích **nguyên nhân thật** đằng sau mỗi
thông báo đó.

## 1. Lỗi ghép cặp file (trước khi render)

Hiện ở cột "TRẠNG THÁI" của bảng file, từ `core/video_processor.py::build_pairs()`.

| Thông báo | Nguyên nhân |
|---|---|
| `Thiếu file media` | Không tìm thấy file audio/video nguồn tương ứng cho dòng này |
| `Thiếu file SRT` | Không tìm thấy file phụ đề `.srt` tương ứng |
| `Lệch file` | Tên file audio và SRT không khớp thứ tự/tên — có thể đã xóa/thêm file lệch cặp |

## 2. Lỗi trong lúc render (panel "📝 Log FFmpeg")

Từ `core/worker.py` → `ui/main_window.py::_on_pair_done/_on_pair_error`.

| Ký hiệu | Ý nghĩa |
|---|---|
| `✓ [i] Xong → file.mp4` | Render thành công |
| `✗ [i] Lỗi: Render đã bị dừng` | Người dùng bấm Dừng/Tạm dừng giữa chừng (`InterruptedError`, không phải lỗi thật) |
| `✗ [i] Lỗi: FFmpeg thất bại với mã lỗi N` | Tiến trình `ffmpeg.exe` thoát với exit code `N ≠ 0`. Xem mục 2.1 |
| `✗ [i] Lỗi: <thông báo Python khác>` | Ngoại lệ khác trong pipeline (thiếu quyền ghi thư mục xuất, file nguồn bị xóa giữa chừng, ffmpeg.exe không tìm thấy, v.v.) — thông báo là `str(exception)` gốc |

### 2.1. Exit code của FFmpeg

FFmpeg hầu như luôn trả về `1` cho mọi lỗi (không có bảng mã lỗi số chi tiết như
HTTP) — **lý do thật nằm ở vài dòng log ngay phía trên dòng exit-code**, vì bản
đóng gói mặc định chỉ hiện `-loglevel warning` (ẩn banner/info, giữ warning+error).
Ví dụ thường gặp:

| Dòng log trước exit code | Nguyên nhân |
|---|---|
| `No such file or directory` | Đường dẫn video nền/audio/layer bị xóa hoặc ổ đĩa rời (USB) ngắt kết nối |
| `Error while opening encoder` / `Cannot load nvEncodeAPI64.dll` | Driver GPU cũ/thiếu, hoặc máy không có GPU NVENC dù đã chọn codec GPU |
| `Invalid argument` sau một dòng `Error reinitializing filters!` | Layer/ảnh nguồn hỏng hoặc định dạng không hỗ trợ (hiếm khi cấu hình sai từ UI vì UI đã validate) |
| `No space left on device` | Hết dung lượng ổ đĩa xuất |
| Không có dòng nào trước exit code (lạ) | Bật `ENCOMIE_DEBUG=1` để xem toàn bộ lệnh + log ffmpeg gốc, xem mục 4 |

## 3. Cổng bản quyền / hạn mức khi render

Từ `core/worker.py`, dừng cả hàng chờ (video đang chạy dở vẫn hoàn tất):

| Tín hiệu | Thông báo | Nguyên nhân |
|---|---|---|
| `license_expired` | *"Thời hạn bản quyền đã kết thúc..."* | `check_license()` trả về `EXPIRED`/`REVOKED`/`INVALID`/`SECURITY_VIOLATION` giữa batch |
| `quota_exceeded` | *"Đã đạt giới hạn render trong ngày của gói Free..."* | `render_quota.remaining_today(max_videos, key) == 0` — xem `core/render_quota.py` (tính riêng theo từng key/ngày) |

## 4. Trạng thái bản quyền (`LicenseStatus`, `core/license_manager.py`)

Hiện trong `LicenseInfoDialog` / hộp thoại cảnh báo khi mở app hoặc trước khi render.

| Status | Khi nào xảy ra |
|---|---|
| `VALID` | Token hợp lệ, còn hạn, đúng máy |
| `NOT_FOUND` | Chưa từng kích hoạt key trên máy này (không có cache) |
| `EXPIRED` | Token đã hết hạn **và** không kết nối được server để làm mới (offline quá lâu), hoặc license đã hết hạn thật sự |
| `INVALID` | Token hỏng chữ ký, hoặc bị server báo `INVALID_KEY`/`MACHINE_MISMATCH`/`NOT_ACTIVATED` |
| `REVOKED` | Key đã bị thu hồi (server báo `LICENSE_REVOKED`) |
| `SERVER_ERROR` | Không kết nối được server lúc activate (activate luôn cần online, không có offline-grace) |
| `SECURITY_VIOLATION` | Phát hiện debugger đang gắn vào tiến trình, process khả nghi đang chạy, hoặc **chữ ký phản hồi server sai** (khả năng bị proxy/MITM chặn) — xem `raw_data.error.message` để biết chi tiết cụ thể |

## 5. Mã lỗi API server (`D:\Cursor\Server`)

Trả về dạng `{ success: false, error: { code, message } }`. Client map các code
này sang `LicenseStatus` ở mục 4, hoặc hiện thẳng `message` nếu không khớp case nào.

| Code | HTTP | Endpoint | Ý nghĩa |
|---|---|---|---|
| `INVALID_KEY` | 400 | activate, verify | Key không tồn tại hoặc gõ sai |
| `LICENSE_EXPIRED` | 403 | activate, verify | License (không phải token) đã hết hạn theo DB |
| `LICENSE_REVOKED` | 403 | activate, verify | Key đã bị admin thu hồi |
| `NOT_ACTIVATED` | 403 | verify | Máy này chưa từng activate key này |
| `MACHINE_MISMATCH` | 409 | verify, deactivate | Token/thiết bị không khớp máy hiện tại |
| `DEVICE_LIMIT_REACHED` | 409 | activate | Đã đạt số thiết bị tối đa (`max_devices`) |
| `ACTIVATION_LIMIT_REACHED` | 409 | activate | Vượt trần kích hoạt trọn đời (`max_devices × 5`) — chống cycle activate/deactivate |
| `RATE_LIMITED` | 429 | mọi endpoint | Vượt giới hạn request/phút cho IP hoặc cho key (xem `middleware/rateLimit.ts`) |
| `SIGNATURE_REQUIRED` | 401 | mọi request ký | Thiếu field `key/machine_id/nonce/timestamp/signature` |
| `TIMESTAMP_EXPIRED` | 400 | mọi request ký | Đồng hồ máy lệch server quá ±120s |
| `INVALID_SIGNATURE` | 401 | mọi request ký | Chữ ký HMAC sai (secret không khớp, hoặc payload bị sửa) |
| `REPLAY_DETECTED` | 409 | mọi request ký | Nonce đã dùng trước đó — request bị replay |
| `VALIDATION_ERROR` | 400 | mọi endpoint (zod) | Body request sai schema |
| `BAD_REQUEST` | 400 | mọi request ký | Body không phải JSON hợp lệ |
| `CONFIG_ERROR` | 500 | mọi endpoint | Server thiếu secret bắt buộc (lỗi vận hành, không phải lỗi client) |
| `UNAUTHORIZED` / `FORBIDDEN` | 401 / 403 | admin API | Thiếu/sai `Authorization: Bearer` token quản trị |
| `NOT_FOUND` | 404 | mọi route | Endpoint không tồn tại, hoặc resource admin không tìm thấy |
| `SERVER_ERROR` | 500 | mọi endpoint | Lỗi không lường trước — xem log Cloudflare Worker |

## 6. Xem log chi tiết đầy đủ

Mặc định bản đóng gói chỉ hiện trạng thái/lỗi gọn (không lộ toàn bộ công thức
filter-graph FFmpeg ra UI, xem `core/video_processor.py::_DEV_MODE`). Để bật lại
log đầy đủ (lệnh FFmpeg nguyên văn, dump từng layer, filter graph...) khi cần debug
trên máy khách:

```
set ENCOMIE_DEBUG=1
EncoMie.exe
```

hoặc chạy trực tiếp từ source (`python main.py`) — khi đó `_DEV_MODE` tự bật, không
cần set biến môi trường.
