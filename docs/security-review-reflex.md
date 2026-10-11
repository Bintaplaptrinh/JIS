> Historical Reflex-S1 verification. The Reflex runtime/checkpoint and fetch/benchmark scripts were removed when JIS migrated to Laya on 2026-10-11.

# Rà soát lỗi và bảo mật JIS — 2026-10-11

Phạm vi: source JIS, API Unix socket, filesystem state, helper subprocess,
zsh/ZLE, tích hợp Reflex-S1 và các đầu vào lỗi. Có kiểm thử tái hiện và sửa
lỗi; không phải chứng nhận bảo mật hoặc pentest toàn bộ hệ điều hành.
Các case nhạy cảm dùng dữ liệu giả trong thư mục tạm, không thực thi thao tác
xóa file, thay đổi database ngoài fixture hoặc khai thác dịch vụ khác.

## Các vấn đề đã xử lý

| Vấn đề | Ảnh hưởng trước sửa | Bản sửa / kiểm chứng |
|---|---|---|
| Model chạy cùng worker với history/typing | Một inference dài có thể chặn các terminal khác; Enter quá hạn | Worker model riêng; chỉ một inference đang chạy; chờ 80 ms rồi heuristic, request khi bận không xếp thêm inference. Test model sleep 350 ms và fast/control traffic vẫn đáp ứng |
| Cold torch/CUDA call | Lần đầu có thể vượt timeout; trong thử nghiệm CPU/GPU đồng thời từng làm một case autosuggestions chạy lệnh gõ sai thay vì hỏi lại | Warmup bằng dữ liệu giả trong model thread trước mở socket; shell dùng correction snapshot hợp lệ khi RPC quá hạn. CPU/GPU integration chạy đồng thời đều qua sau sửa |
| Helper git lấy từ PATH của request | Request có thể làm daemon chạy executable `git` bất kỳ do client chọn | Cố định helper từ PATH lúc daemon khởi động; kiểm thử PATH chứa fake git không tạo marker. Probe giới hạn 60 ms và stdout 32 KiB |
| Lock/log/SQLite/sidecar có thể là symlink hoặc hardlink | Ghi vào file không thuộc state hoặc sửa quyền/ghi file khác | `O_NOFOLLOW`, kiểm tra regular file, owner UID, single link; chmod 0600. DB/WAL/SHM kiểm tra trước mở; test target giữ nguyên |
| File DB cũ rộng quyền / history quá giới hạn lúc startup | History vẫn có thể đọc rộng hoặc vượt row cap trước lần record tiếp theo | Sửa quyền file và sidecar, prune theo cap lúc mở DB; test 0666 → 0600 và giảm limit |
| Unicode surrogate / control trong metadata / status bool / field lạ | Encode lỗi, phản hồi sai dạng, log exception hoặc nhận input ngoài schema | Validate type/giới hạn/control/surrogate, chặn field ngoài giao thức; không phản chiếu ID lỗi vào reply |
| Deep JSON / frame quá dài | Parser lỗi hoặc nhận metadata không dùng; connection có thể hỏng | Bắt lỗi parser, schema phẳng nghiêm ngặt, đóng frame quá 32 KiB. Test daemon tiếp tục trả ping |
| Native reply chưa validate | Một frame sai có thể hiển thị control character hoặc để shell chờ gợi ý mãi | Kiểm tra `=` prefix, ID số, kind whitelist, command không control; lỗi parse thì đóng và kết nối lại. Không eval/source reply |
| Socket write với paste quá dài | Có thể viết frame lớn vào socket blocking | Kiểm tra giới hạn byte trước encode/write; input quá dài đi theo zsh gốc |
| Snapshot thiếu PATH | Gợi ý từ môi trường cũ có thể được nhận sau PATH thay đổi | Kiểm tra buffer/CWD/PATH khi nhận và điền; kết quả stale bị bỏ |
| HISTORY_IGNORE chỉ áp dụng ở record | Lệnh riêng tư vẫn có thể đi vào correction request | Bỏ qua typing/correction nếu khớp HISTORY_IGNORE; test không hỏi lại lệnh riêng tư |
| Secret JSON/URL không khớp regex cũ | Một số token trong JSON hoặc user:password@URL có thể bị học | Mở rộng regex cho closing quote, URL credential và PEM marker; test các biến thể |
| Risk filter dùng tên executable nguyên văn | `/bin/rm`, wrapper `env/command`, một số delete/prune có thể lọt completion history | So sánh basename, chặn wrapper và các delete/prune biết được. Test absolute path, quote, wrapper |
| Checkpoint pickle-only hoặc `.pt`/safetensors lẫn nhau | Nạp định dạng không cần thiết / hash calibration khác weight đã nạp | JIS chỉ nhận safetensors và từ chối thư mục có `.pt`; fetch ghi manifest hash, ghim source/model revision |
| Model trả lỗi / NaN / ID không có / flag sai type | Reorder sai hoặc exception lan ra shell | Validate câu trả lời model; giữ abstention; fallback khi lỗi. Test mock và input >512 token bằng model thật, request sau phục hồi |
| Start model khi daemon heuristic đang chạy | Có thể báo thành công nhưng thực tế vẫn chạy cấu hình cũ | So sánh checkpoint/device/thread với daemon hiện tại, báo lỗi nếu khác; profile thử nghiệm dùng state riêng |

## Các rủi ro vẫn còn

1. **Model chưa phù hợp làm quyết định chính.** Trong tập diagnostic, lựa
   chọn thô đúng 12/19 và toàn bộ schema terminal đều abstain. Confidence
   chưa calibrate không phải xác suất đúng. Không bỏ abstention để ép dùng
   model. Nội dung command/CWD/previous là dữ liệu có thể chứa ý hướng dẫn;
   model có thể bị chi phối, còn filter và xác nhận của người dùng vẫn cần.

2. **Khoảng 0,9 GiB RAM CPU hoặc 1,7 GiB RAM GPU.** File trọng số 93 MB không
   bao gồm PyTorch/transformers/CUDA. Ngay cả một model dùng chung vẫn là chi
   phí đáng kể cho máy ít RAM. Số thread OS lớn hơn `torch.set_num_threads`
   do các pool runtime. Matrix benchmark ghim physical core; profile chạy
   bình thường chỉ giới hạn math threads, không ghim toàn process vào core.

3. **Timeout thread không hủy được native kernel đang chạy.** Sau 80 ms,
   UI dùng heuristic, model vẫn hoàn tất ở background; request mới dùng
   heuristic khi model bận. Nếu native model/CUDA treo vĩnh viễn, worker model
   không tự phục hồi và graceful shutdown có thể chờ. Cần process isolation
   với watchdog để hard-kill/restart trong phiên bản sau. Python GIL, I/O
   filesystem chậm hoặc máy quá tải vẫn có thể làm latency vượt budget.
   Warmup giảm cold-call risk, không tạo bảo đảm realtime.

4. **Filter secret và command nguy hiểm vẫn là heuristic.** Encoded secret,
   alias/function/script chứa thao tác nguy hiểm, option mới của CLI hoặc
   cấu trúc không được nhận diện vẫn có thể lọt. History plaintext local,
   không encrypted. Các hàng cũ đã lưu không bị xóa chỉ vì regex mới; filter
   mới ngăn đề xuất/ghi tiếp các mẫu khớp, không đảm bảo tẩy lịch sử bí mật.
   Dùng leading space/HISTORY_IGNORE để loại lệnh khỏi việc học.

5. **Giới hạn tin cậy là Unix user.** Socket private và peer UID không phân
   biệt hai process cùng UID. Process cùng user có thể đọc history, gửi record
   để làm nhiễu rank, gọi stop hoặc sửa source/manifest/checkpoint local. Session
   ID dùng để xếp hạng theo terminal, không phải xác thực/cách ly bí mật giữa
   các terminal. Không mở socket này ra TCP hoặc phục vụ user khác.

6. **TOCTOU cùng UID và thư mục cha.** Kiểm tra file DB trước `sqlite3.connect`
   không phải thao tác atomic với SQLite open. Directory 0700 ngăn user khác;
   process cùng UID vẫn có thể đổi path giữa hai bước. JIS_STATE_DIR cần là
   thư mục riêng được tin cậy, không dùng thư mục dự án chia sẻ hoặc chính
   `$HOME` làm state. Socket client Python kiểm tra type/UID/peer; adapter zsh
   chủ yếu dựa vào thư mục private, không có authentication token riêng.

7. **Cache và chất lượng ngoài fixture.** PATH/git alias cache 30 s có thể
   cũ; danh sách subcommand giới hạn; history ranking có global fallback giữa
   thư mục. Helper git theo môi trường daemon không hoàn toàn mô phỏng git
   wrapper/env của từng shell. Correct spelling không sửa stderr/argument
   runtime và không hiểu đầy đủ cú pháp zsh. Tên alias/function với whitespace
   hoặc cwd/path có control characters bị từ chối một cách bảo thủ.

8. **Dependency/source supply chain.** Safetensors loại phần nạp pickle của
   checkpoint nhưng không làm Python source/dependency thành sandbox. Source
   ghim commit và file hash được lưu trong manifest; runtime vẫn chạy code
   của package đã được review. Manifest cũng cần được tin cậy. Không tải
   remote code khi inference và không tự cài/upgrade dependency trong `bqp`.

## Kiểm chứng

- `tests/test_security.py`: state link/permission/cap, fake git PATH, SQL
  injection là dữ liệu, secret/risky variants, input type và model fallback,
  model delay không tích lũy queue.
- `tests/integration_zsh.py`: socket malformed/deep/oversize, privacy rules,
  yes/no/cancel/fill-only, nhiều terminal, autosuggestions và 2.000 completion
  functions. Chạy cùng suite với heuristic, CPU model và CUDA model.
- `tests/reflex_cases.json` và `scripts/benchmark_reflex.py`: 30 case và ma
  trận CPU 2/4/6/8 core + GPU; có lỗi tokenizer/schema cố ý.
- Các case chỉ điền `BUFFER`; test sentinel xác nhận `yes` không chạy lệnh.

Source/model và số đo: [manifest](reflex-manifest.json),
[kết quả benchmark](reflex-results.md), [JSON đầy đủ](reflex-benchmark.json).
