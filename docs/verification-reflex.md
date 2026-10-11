> Historical Reflex-S1 verification. The Reflex runtime/checkpoint and fetch/benchmark scripts were removed when JIS migrated to Laya on 2026-10-11.

# Kiểm chứng model thật — 2026-10-11

Mọi lệnh Python chạy sau `conda activate bqp` (Python 3.12.14). Kiểm thử
Unix socket, PTY và CUDA chạy ngoài sandbox vì sandbox không cung cấp các
tài nguyên đó. Dữ liệu giả/state tạm được dùng trong suite, không import
history cá nhân. Không cài hoặc nâng cấp dependency của môi trường.

| Kiểm tra | Kết quả |
|---|---|
| `PYTHONPATH=src python -m unittest discover -s tests -v` | 31/31 qua, gồm 18 core/protocol và 13 security/scheduling |
| `PYTHONPATH=src python tests/integration_zsh.py` | 15 qua; 1 case model được skip đúng điều kiện |
| `JIS_MODEL_TEST=cpu PYTHONPATH=src python tests/integration_zsh.py` | 16/16 qua với checkpoint thật |
| `JIS_MODEL_TEST=cuda PYTHONPATH=src python tests/integration_zsh.py` | 16/16 qua với checkpoint thật trên RTX 3060 |
| `python -m compileall -q src scripts tests` | Qua |
| `zsh -n shell/jis.plugin.zsh shell/jis.experimental.zsh` | Qua |
| `.zshrc` thật + `conda activate bqp` + `jis.experimental.zsh` trong PTY | Qua; `yes` điền BUFFER, không thực thi sentinel |
| CPU 2/4/6/8 core và CUDA host 2 core | Đã chạy process riêng, affinity/threads cố định, lưu số đo latency/RSS/CPU/VRAM |
| 30 case diagnostic × 5 cấu hình | Heuristic đúng 30/30; model thô đúng 12/19 case eligible, 19/19 abstain |

CPU/CUDA integration được chạy đồng thời sau bản sửa model warmup và shell
snapshot; cả hai đạt. Sau đó bổ sung giới hạn stdout/thời gian helper git
và case helper đóng stdout nhưng không thoát; chạy lại core/security và
integration heuristic đều đạt. Phép đo direct inference và daemon được
chạy tuần tự, không chạy đồng thời như suite integration.

Suite ZLE kiểm tra `yes` chỉ điền BUFFER, sentinel chỉ xuất hiện khi Enter
lần nữa; `no`/Ctrl-G giữ lệnh cũ; bypass; history privacy; alias; context
nhiều terminal; 2.000 completion functions; malformed native reply;
deep JSON, surrogate, frame quá dài; lỗi model >512 token và request sau
phục hồi. Kiểm thử security có model sleep 350 ms, busy fallback không
xếp hàng model thêm, request ping/fast vẫn xử lý được.

Không kết luận model tốt hơn từ các case đã chọn, không gọi mọi schema
thành công chỉ vì inference trả về: all-abstain được ghi rõ. Không đo
điện năng, terminal emulator hay hiệu năng máy có cấu hình khác.

[Báo cáo số đo](reflex-results.md), [JSON](reflex-benchmark.json),
[manifest source/weight](reflex-manifest.json), [audit](security-review.md),
[kết quả profile smoke](reflex-live-smoke.json).
