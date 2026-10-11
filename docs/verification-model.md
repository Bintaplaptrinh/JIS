# Kiểm chứng JIS/Laya — 2026-10-11

Python luôn chạy trong `conda activate bqp`. Socket/PTY/CUDA dùng quyền
ngoài sandbox; không import history cá nhân hoặc chạy lệnh destructive.
Laya 0.4.0 đã có sẵn, không cài/nâng cấp môi trường.

| Kiểm tra | Kết quả |
|---|---|
| Core/protocol/security/resource/lifecycle unittest | 39/39 qua |
| Heuristic zsh/PTY integration | 15 qua, 1 case model skip |
| CPU Laya thật zsh/PTY integration | 16/16 qua |
| CUDA Laya thật zsh/PTY integration | 16/16 qua |
| Matrix base CPU 2/4/6/8 physical core + CUDA host 2 | Đã đo bằng worker mới cho từng cấu hình |
| Typed CPU 2 + CUDA host 2 | Đã đo và so sánh với base |
| 30 diagnostic case | 7 model-eligible: raw đúng 7/7; pipeline khớp expected 30/30 |
| Process Laya thật CPU/CUDA | Load, cache hit, injected memory pressure eviction, PID mới sau reload, idle release đều qua |
| `.zshrc` thật + bqp + experimental profile auto | Qua; cold fallback, CUDA được nạp, model có inference, yes chỉ điền BUFFER |
| Daemon thử nghiệm sau idle mặc định 120s | Unix-socket stats xác nhận daemon còn hoạt động, model đã unload, model_pid=null, loads=1/unloads=1/errors=0 |
| Compile Python và zsh syntax | Qua |

Unit lifecycle dùng worker giả lập lỗi/hang: timeout không tích lũy queue;
pressure trong loading reaps process; CPU spike cần nhiều mẫu; RAM/cgroup
ancestor quota; cache gắn session/CWD; trả lời NaN/bool/ID lạ bị từ chối;
ties dùng probability scores mà không mutate fallback. Integration giữ
yes/no/cancel/fill-only, alias, privacy, 64 client, hai terminal, 2.000
completion functions, malformed/deep/oversize socket frames và long input
bỏ qua model. CPU/CUDA integration chạy đồng thời, matrix đo chạy tuần tự.

Lifecycle actual cũng kiểm tra bốn spelling tie synthetic; model không đảm
bảo khớp intended command. Điều này được ghi ở [results](laya-results.md),
không coi confidence cao là chứng minh đúng. Low RAM là snapshot injection,
không dùng chương trình chiếm hết RAM/VRAM máy.

[Benchmark JSON](laya-benchmark.json), [lifecycle JSON](laya-lifecycle.json),
[live profile smoke](laya-live-smoke.json),
[live idle confirmation](laya-live-resources.json),
[audit](security-review.md), [historical Reflex test](verification-reflex.md).
