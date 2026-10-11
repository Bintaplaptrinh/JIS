# JIS

JIS v0.1 là engine gợi ý terminal bằng Python, tích hợp trực tiếp với zsh.
Chạy local, không gọi API. Profile heuristic chỉ cần Python standard library;
profile model dùng torch/transformers đã có trong môi trường `bqp`.
Các component tách biệt để có thể thay daemon bằng Rust/Go sau này.

## Thử ngay trên máy này

```zsh
cd /home/tuanphat/Projects/JIS
source /home/tuanphat/anaconda3/etc/profile.d/conda.sh
conda activate bqp
source shell/jis.plugin.zsh
```

JIS tự khởi động một daemon dùng chung. Không chỉnh `.zshrc`.
Để thử nhiều terminal, chạy các lệnh trên trong từng terminal.
Nếu `zsh-autosuggestions` đã nạp, JIS tắt renderer đó trong phiên hiện tại
để nhận quyền hiển thị ghost text. Mở một shell mới sẽ dùng cấu hình cũ.

Gõ `gti status`, nhấn Enter:

```text
Do you mean git status ? Type yes or no, then Enter.
```

Gõ `yes` rồi Enter: JIS điền `git status` vào dòng nhập. **Chưa chạy.**
Bạn sửa lệnh tùy ý; nhấn Enter lần nữa mới thực thi.
`no` trả lại lệnh gõ ban đầu; `Ctrl-G` hủy xác nhận và trả lại lệnh cũ.

Sau khi chạy `echo jis-demo-one`, gõ `echo jis-`: phần còn lại xuất hiện
dưới dạng ghost text. `Ctrl-Space` điền gợi ý; Enter vẫn chạy nội dung bạn
đang thực sự nhập. Ctrl-Space có thể bị terminal/IME giữ lại; đổi phím bằng
`bindkey '^X^A' jis-fill` sau khi source.

| Thao tác | Kết quả |
|---|---|
| Enter trên lỗi chính tả đủ rõ | Hỏi `Do you mean … ?` |
| `yes` + Enter | Chỉ điền lệnh |
| `no` + Enter / Ctrl-G | Trả lại lệnh gốc |
| Ctrl-Space | Điền gợi ý lịch sử |
| Ctrl-X rồi Enter | Chạy đúng dòng đang nhập, bỏ qua sửa lỗi |
| `jis-off` / `jis-on` | Tắt / bật JIS trong phiên |
| `jis-refresh` | Kết nối lại, cập nhật alias/function |
| `jis-status` | PID, số client, số lịch sử, ranker |

## Engine hiện có

- Sửa tên executable theo PATH, builtins, alias và function của shell;
  dùng khoảng cách chỉnh sửa có tính đến đảo ký tự.
- Sửa subcommand phổ biến của git, npm, docker, conda, kubectl, pip.
  Kiểm tra git alias và executable `git-*` trước khi sửa.
- Gợi ý prefix từ lệnh thành công đã quan sát sau khi bật JIS. Xếp hạng theo
  phiên, thư mục, lệnh trước đó, tần suất trong mẫu và độ gần về thời gian.
- Một daemon, một worker nhanh và một worker model tùy chọn;
  một request gợi ý đang chờ trong mỗi shell. Buffer/CWD/PATH
  đổi trong lúc chờ thì bỏ kết quả cũ và gửi trạng thái mới.
- SQLite WAL giữ tối đa 20.000 dòng; cache và hàng đợi đều có giới hạn.
- Không học lệnh có khoảng trắng đầu dòng, `HISTORY_IGNORE`, control character
  hoặc một số mẫu secret. Lệnh không thành công không được đề xuất lại.
- Không bổ sung lệnh nguy hiểm từ lịch sử; sửa chính tả chỉ đổi token sai và
  giữ nguyên đối số người dùng đã nhập. Không có `eval` phản hồi từ daemon.

Đây là bản đầu có thể thử thực tế, chưa phải trợ lý hiểu mọi ý định. Chỉ xử lý
lệnh đơn; pipeline, redirect, substitution và cú pháp shell phức tạp được
bỏ qua. Không đọc stderr của lệnh để tự sửa lỗi runtime hoặc suy đoán đối số.
Lịch sử bắt đầu từ lúc bật JIS, chưa import `.zsh_history`. Danh sách subcommand
có giới hạn; cache PATH/git-alias làm mới sau 30 giây. Bộ lọc secret là
heuristic: không đảm bảo phát hiện mọi bí mật. Lịch sử vẫn là plaintext local;
dùng khoảng trắng đầu dòng để bỏ một lệnh khỏi việc học.

## Dùng CLI và kiểm thử

```zsh
./bin/jis status
./bin/jis correct 'gti status'
./bin/jis suggest 'echo jis-'
./bin/jis stop
./bin/jis start

PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tests/integration_zsh.py
python scripts/benchmark.py
```

Các lệnh Python chạy trong `conda activate bqp`. Integration tests dùng
pseudo-terminal với zsh thật, state tạm riêng, không đọc lịch sử cá nhân.
Benchmark đo riêng daemon với dữ liệu giả; xem [kết quả](docs/benchmark.json).
Kiểm thử model thật trên CPU/GPU và rà soát bảo mật đã hoàn tất;
xem [kiểm chứng model](docs/verification-model.md),
[bảo mật và rủi ro còn lại](docs/security-review.md).
Biên bản profile heuristic ban đầu ở [verification.md](docs/verification.md).

Lần đo trên máy này (Ryzen 7 7700, Python 3.12, 6.000 dòng lịch sử, không model):
RAM nhàn rỗi khoảng 27,3 MiB với 1 kết nối và 27,8 MiB với 64 kết nối;
sau tải khoảng 30,1 MiB. p95 truy vấn warm khoảng 1,3 ms; 16 client gửi
liên tục đồng thời có p95 khoảng 16,6 ms. Đây là số đo daemon qua socket,
chưa gồm thời gian vẽ zsh, chi phí terminal emulator hoặc máy yếu hơn.

State mặc định: `~/.local/state/jis` (directory 0700, socket/DB 0600).
Đổi bằng `export JIS_STATE_DIR=/đường/dẫn/riêng` trước khi source.
Đổi interpreter bằng `export JIS_PYTHON=/đường/dẫn/python`.
Nếu daemon mất kết nối, shell tiếp tục hoạt động; `./bin/jis start` rồi
`jis-refresh` để nối lại. `jis-off` không dừng daemon đang phục vụ shell khác.

## Laya và nạp/giải phóng theo tài nguyên

Reflex đã được gỡ khỏi runtime, CLI, test, source cache và checkpoint.
Số đo Reflex được giữ làm tài liệu lịch sử. JIS hỗ trợ checkpoint local:
`models/laya-base` (`convaiinnovations/laya`) và `models/laya-typed`
(`convaiinnovations/laya-typed-decisions`). Đã tải cả hai theo revision/SHA256
trong manifest; `python scripts/fetch_laya.py` tải lại, không cài dependency.
Môi trường `bqp` hiện có `laya 0.4.0`, torch và transformers.

Trong **zsh mới**, bật Laya base với lựa chọn CPU/GPU theo tài nguyên:

```zsh
source /home/tuanphat/anaconda3/etc/profile.d/conda.sh
conda activate bqp
source /home/tuanphat/Projects/JIS/shell/jis.experimental.zsh
jis-status
```

Profile dùng state riêng `.runtime/laya-state`. Daemon mở socket ngay và
không import torch. Model chỉ nạp sau một yêu cầu correction có >=2 ứng viên;
trong lúc chưa sẵn sàng, terminal dùng heuristic. Background history suggestion
luôn dùng worker nhanh. Chỉ một process model dùng chung cho mọi terminal.

- Quan sát `MemAvailable`, giới hạn RAM/CPU của cgroup v2 và ancestor, CPU
  busy/load, memory PSI; GPU qua `nvidia-smi` khi cần, tôn trọng GPU đầu tiên
  trong `CUDA_VISIBLE_DEVICES` (index hoặc UUID).
- Nạp khi RAM khả dụng >=6 GiB, CPU <=70%, memory PSI <=1%, ổn định 3 mẫu.
  `auto` ưu tiên CUDA nếu VRAM trống >=4 GiB và GPU utilization <70%; nếu
  không đủ GPU nhưng đủ RAM/CPU thì chọn CPU. Trên máy ít RAM sẽ giữ heuristic.
- Thu hồi ngay khi RAM <1 GiB, PSI >5% hoặc VRAM <768 MiB. CPU >92% / GPU
  >95% phải kéo dài 3 mẫu mới thu hồi, tránh dao động. Không nạp lại trong
  cooldown 30s; yêu cầu mới vẫn phải qua kiểm tra tài nguyên ổn định.
- Dừng process sau 120s không có correction đủ điều kiện. RAM/VRAM model và
  runtime được trả lại hệ điều hành; cache nhỏ của parent còn tối đa 32 kết quả.
  Hết thời gian nạp 90s / inference 3s thì terminate, sau 300ms vẫn chưa thoát
  thì kill và reap. Worker đặt nice +10 và tự thoát nếu parent chết trên Linux.
- Enter chờ model tối đa 75ms. Inference muộn được cache 30s, ràng buộc đúng
  session/CWD/previous/PATH/known/candidate. Bận thì fallback, không xếp hàng
  thêm inference. Request dài và token/options bị truncate/collapse không dùng
  quyết định model. Cache không ghi xuống disk.

Model chọn từ ứng viên đã qua filter, không sinh lệnh mới. Dùng
`answer_confidence` (max probability), không dùng entropy `confidence` của
SDK. Chỉ hỗ trợ tie-break khi heuristic yếu, probability >=0,9 và margin
>=0,2; giữ sửa lỗi có evidence spelling mạnh. Confidence vẫn chưa được
calibrate trên domain terminal. `yes` chỉ điền BUFFER như trước.

Cấu hình trước khi source (khi thay cấu hình, dừng daemon cũ và mở shell mới):

```zsh
export JIS_LAYA_DEVICE=cpu         # auto / cpu / cuda
export JIS_LAYA_THREADS=2         # 1..8; math threads, không ghim affinity
export JIS_LAYA_MODE=shadow       # assist mặc định; shadow chỉ quan sát
export JIS_LAYA_IDLE=120          # >=5 giây
export JIS_LAYA_CHECKPOINT=/home/tuanphat/Projects/JIS/models/laya-typed

JIS_STATE_DIR=/home/tuanphat/Projects/JIS/.runtime/laya-state ./bin/jis stop
```

CLI tương đương:

```zsh
JIS_STATE_DIR=$PWD/.runtime/laya-state ./bin/jis start \
  --laya-checkpoint "$PWD/models/laya-base" --laya-device auto --laya-threads 2
```

Mỗi checkpoint khoảng 843 MB, 421 triệu tham số. Laya không phải mô hình
vài MB; process CPU khoảng 2,5 GiB RAM. Cơ chế thu hồi giảm tài nguyên khi
không cần, không làm giảm chi phí trong lúc inference. Xem
[kết quả thật](docs/laya-results.md), [lifecycle](docs/laya-lifecycle.json),
[kiểm chứng](docs/verification-model.md), [bảo mật](docs/security-review.md).
Typed-decisions được tinh chỉnh cho bốn nghiệp vụ khác, không mặc định tốt
hơn cho terminal. Model base/typed đều cần dữ liệu terminal độc lập để xác
nhận lợi ích. Giao thức socket v1 và component boundaries tiếp tục cho phép
thay engine Python bằng Rust/Go; xem [architecture](docs/architecture.md).
