# Rà soát JIS/Laya và tài nguyên — 2026-10-11

Reflex đã được gỡ khỏi code, CLI, checkpoint và source cache. Báo cáo cũ
[Reflex audit](security-review-reflex.md) chỉ là lịch sử. Các bản sửa socket,
PATH helper, state file, secret/risk filter và ZLE vẫn được giữ và kiểm thử.

## Những thay đổi được kiểm chứng

- **Process isolation:** daemon không import torch/laya/transformers. Một
  worker dùng chung, một inference đang chạy; không tạo worker cho từng
  terminal. Không có model thì đường gợi ý/history vẫn hoạt động.
- **Thu hồi thật:** terminate 300ms rồi kill/reap, không chỉ `del model` /
  `empty_cache`. Kiểm chứng process thật CPU/CUDA đã nạp, thu hồi theo pressure
  injection, nạp lại PID mới và tự thu hồi theo idle. Parent còn khoảng 31 MiB
  trong chương trình kiểm chứng, worker đã biến mất khỏi `/proc`.
- **Watchdog:** nạp tối đa 90s, inference tối đa 3s; UI chờ tối đa 75ms.
  Fault-injection worker sleep/hang đã được reap, không tích lũy hàng đợi.
  Không áp idle timeout lên giai đoạn loading: đã tìm và sửa case cold load
  lâu hơn thời gian idle cấu hình ngắn.
- **Module/lifecycle:** worker có PYTHONPATH nội bộ rõ ràng, không phụ thuộc
  một script test đã export PYTHONPATH hay chưa; Linux parent-death signal,
  cancellation khi đang warmup và thu hồi khi RAM giảm đã được kiểm chứng.
- **Resource admission:** `/proc` MemAvailable/CPU/PSI và cgroup v2 ancestor
  RAM/CPU quota, GPU memory/utilization. Path cgroup bị ẩn/`..` trong namespace
  dùng mounted root; ba mẫu ổn định, load/unload thresholds riêng và cooldown
  tránh nạp/xả liên tục. Không gọi nvidia-smi khi idle không có demand.
- **Reply safety:** candidate IDs whitelist, exact probability keys, finite
  numbers, sum/margin/argmax/max-probability confidence kiểm tra; bool/NaN/
  choice lạ bị từ chối. Không dùng entropy confidence như xác suất đúng.
  Truncated state/collapsed option không dùng quyết định model. Candidate
  scores không bị mutate vào fallback khi model quá hạn.
- **Cache:** tối đa 32 entry, TTL 30s, không disk; fingerprint session/CWD/
  input/previous/PATH/known/candidate. Test khác session/CWD phải inference
  lại. Response muộn không tự điền vào BUFFER hoặc thực thi lệnh.
- **Offline artifacts:** hai repo/revision ghim, streaming download có cap
  size/SHA256; chỉ safetensors/config/tokenizer, không remote Python/pickle.
  Worker kiểm tra hash trước load, không tự tải model hoặc đổi dependency.
  Config tokenizer được normalize một lần và lưu cả source/local digest.
- **SDK fallback:** CUDA phải tồn tại; nếu SDK chuyển device hoặc gặp CUDA
  OOM fallback, parent bỏ reply/thu hồi worker thay vì âm thầm giữ model CPU
  không được resource admission cho phép. Nice +10, eager, không compile.
- **UX:** tests CPU/GPU model thật giữ yes/no/cancel/fill-only, privacy,
  alias/function, nhiều terminal và malformed frame. Dòng gốc vẫn đi theo
  zsh khi backend không sẵn sàng.

## Giới hạn còn lại

1. **Model không biết chắc ý định.** Hai checkpoint đều English, không fine-
   tune/calibrate cho terminal. Trong case synthetic có intended `git push`,
   Laya chọn `git pull` với answer_confidence khoảng 0,92. Confidence threshold
   không chứng minh đúng. Assist chỉ tie-break heuristic yếu; strong spelling
   evidence giữ nguyên. Có `shadow` để quan sát mà không đổi quyết định.
   Gợi ý vẫn phải qua xác nhận người dùng; JIS không tự chạy.
2. **RAM/VRAM lớn khi model sống.** CPU worker khoảng 2,5 GiB, peak khoảng
   3,2 GiB; GPU khoảng 1,7 GiB RAM và 2,6 GiB VRAM. Unload giảm idle cost,
   không giảm tải trong inference. Policy bảo thủ có thể không nạp trên máy
   yếu. Không đảm bảo số đo latency trên máy khác.
3. **Probe không phải allocation reservation.** Process khác có thể chiếm RAM/
   VRAM giữa admission và allocation. Resource sample khoảng một giây, load
   average có độ trễ. OOM-killer/kernel/driver treo vẫn có thể xảy ra; SIGKILL
   không giải phóng ngay tác vụ đang ở uninterruptible kernel state. Worker
   bị chết được phát hiện/fallback, không bảo đảm realtime hay tránh mọi OOM.
4. **Linux/cgroup v2/GPU tooling.** Cgroup v1 không có đầy đủ limit awareness;
   probe Linux thiếu/không hợp lệ thì không nạp. GPU cần nvidia-smi, mask phải
   là index/UUID của GPU đầu tiên; không tự chọn nhiều GPU hoặc hỗ trợ MIG.
5. **Trust boundary vẫn là Unix UID.** Cùng user có thể sửa source/checkpoint/
   manifest, đọc DB/socket, gửi history poison hoặc stop. Safetensors/hash
   không sandbox Python SDK. Không mở socket cho user khác hoặc TCP. State
   0700/files 0600, SQLite open vẫn có cùng-UID TOCTOU như báo cáo cũ.
6. **Privacy/filter heuristic.** Secret encoded và alias/script nguy hiểm vẫn
   có thể lọt filter; history plaintext local, dữ liệu cũ chưa tự tẩy. Dùng
   leading space/HISTORY_IGNORE. Prediction text chỉ vào process local và
   cache bounded; SDK diagnostics trong model.log cũng cần được tin cậy.
   Log truncate khi nạp nếu vượt 1 MiB, chưa có hard stream log rotation.
7. **Cold/cache tradeoff.** Tài nguyên cần ổn định trước nạp, nạp/warmup mất
   nhiều giây. CPU thường quá 75ms nên lần đầu fallback, reply chỉ hữu ích
   khi context khớp lần sau. Cache hết hạn/eviction không bị tự điền vào shell.

Thử nghiệm thiếu RAM là **snapshot injection**, không cố ý làm cạn RAM/VRAM
thật. Thời gian idle 5s/cooldown 1s trong kiểm chứng chỉ để test; mặc định
120s/30s. [Lifecycle JSON](laya-lifecycle.json), [số đo](laya-results.md),
[test summary](verification-model.md).
