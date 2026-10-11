"""Generate standalone measured report and scientific plot from sealed JSON."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    data=json.loads((ROOT/"docs/laya-benchmark.json").read_text())
    lifecycle=json.loads((ROOT/"docs/laya-lifecycle.json").read_text())
    rows=[]
    for c in data["configs"]:
        label=f"{c['model']} / {c['device']} {c['threads']}"
        rows.append(f"| {label} | {c['warm']['p50_ms']:.2f} / {c['warm']['p95_ms']:.2f} | {c['memory']['rss_mib']:.0f} / {c['memory']['peak_rss_mib']:.0f} | {c.get('vram_mib','—')} | {c['load_and_warmup_ms']/1000:.2f} | {c['raw_correct']}/{c['eligible']} |")
    text="""# JIS/Laya: checkpoint thật và adaptive lifecycle — 2026-10-11

Máy Ryzen 7 7700, 8 core vật lý / 16 logical; RTX 3060 12 GiB; `bqp`
Python 3.12.14, torch 2.14.0+cu130, transformers 5.17.0, laya **0.4.0**
đã có sẵn. Không cài/nâng cấp dependency. Hai checkpoint 421.293.827 tham số,
khoảng 842,6 MB mỗi safetensors. Base revision và typed revision/SHA256 ở
[manifest base](laya-base-manifest.json), [manifest typed](laya-typed-manifest.json).

| Model / cấu hình | Warm inference p50 / p95 (ms) | RSS / peak RSS (MiB) | VRAM process (MiB) | Nạp + warmup (s) | Raw eligible đúng |
|---|---:|---:|---:|---:|---:|---:|
"""+"\n".join(rows)+"\n\n"
    text+="""Mỗi hàng là process mới, chạy tuần tự; CPU ghim một logical CPU/core vật lý
(ID 0..1/3/5/7), torch math threads bằng số core, interop=1, tokenizer không
parallel. CUDA host dùng 2 core, autocast **fp16**; CPU F32. Eager, compile/
TileLang tắt, nice +10. 40 request warm cùng schema; thời gian đo toàn bộ
`Agent.predict` trong worker, có tokenize, serialize, decode và copy output
GPU về CPU (đồng bộ). Không bao gồm socket RPC/zsh/terminal emulator.
RAM là cả process/runtime; peak gồm loading. VRAM từ nvidia-smi đúng PID.
CPU/GPU khác precision; không coi đây là so sánh số học tương đương.

![Biểu đồ đo](laya-benchmark.png)

## Case và giới hạn chất lượng

30 case cố định ở `tests/decision_cases.json`. 23 case bị policy/provider
loại hoặc chỉ có một ứng viên, nên runtime không gọi model. 7 case có >=2
ứng viên được gửi model, cả base và typed đúng 7/7 trên tất cả cấu hình;
pipeline assist khớp expected 30/30 trong bộ nhỏ này. Bộ test có chọn lọc,
không phải benchmark độc lập hoặc độ chính xác sản phẩm. Không so trực tiếp
7/7 với Reflex 12/19 trước đây: diagnostic Reflex cũ cũng gọi model cho case
có một ứng viên; điều kiện eligibility/schema/runtime khác.

Không thấy typed tốt hơn base trên những case này. Typed được fine-tune cho
bốn nghiệp vụ khác, chưa phải terminal; base làm mặc định, typed vẫn chọn
được qua `JIS_LAYA_CHECKPOINT` / CLI. Không dùng Router preload ba model vì
trái mục tiêu một worker/tài nguyên thấp. Cả hai là checkpoint English.

Bốn case thêm có spelling tie ở `tests/laya_ambiguity_cases.json` dùng ý định
expected **synthetic**, không khẳng định biết chắc ý định người dùng. Ví dụ
`git pulh origin HEAD` với previous `git commit -m update` đặt intended là
`git push origin HEAD`, nhưng model chọn `git pull origin HEAD` với max-prob
confidence khoảng 0,92. Confidence cao vẫn có thể khác ý định; không tuyên bố
Laya cải thiện mọi lỗi. Gợi ý vẫn chỉ điền sau xác nhận, người dùng có thể sửa.

## Thu hồi/nạp lại thật

Chương trình kiểm chứng dùng ResourceProbe thật để nạp. Sau đó inject
snapshot MemAvailable=100 MiB để đi qua đúng nhánh low-memory policy;
**không làm cạn RAM thật**. Worker CPU/CUDA được terminate/reap, PID không
còn trong `/proc`, rồi nạp lại PID mới sau cooldown. Chờ idle thật 5s cũng
thu hồi worker. Test dùng idle=5s/cooldown=1s để ngắn; sản phẩm 120s/30s.

"""
    for row in lifecycle:
        text+=f"- {row['device']}: parent trước nạp {row['initial_parent_memory']['rss_mib']:.2f} MiB; worker khi nạp {row['loaded_worker_memory']['rss_mib']:.0f} MiB; parent sau thu hồi {row['unloaded_parent_memory']['rss_mib']:.2f} MiB. First rank {row['first_rank_ms']:.2f} ms, cache hit, reload và idle release đều được xác nhận.\n"
    text+="""
Đây là RSS của **chương trình kiểm chứng lifecycle** và worker, không thay
thế số đo daemon dưới tải lớn. GPU context được sở hữu bởi worker đã thoát;
không gọi `del` rồi giữ process torch trong RAM. Cache parent vẫn có tối đa
32 kết quả, TTL 30s, ràng buộc session/ngữ cảnh. Cache hit không thêm inference.

CPU 2 core ~377ms vượt ngân sách Enter 75ms, nên lần đầu fallback rồi cache
kết quả muộn; GPU ~17ms có thể đáp ứng khi đã nạp. Request khi cold/loading/
bận/thiếu tài nguyên vẫn trả heuristic; không làm terminal chờ model nạp.
Đường history suggestion không dùng model. Thêm terminal không thêm worker.
Unloaded daemon không import ML libraries và không probe GPU khi không có demand.

Ngưỡng hiện tại: nạp RAM >=6 GiB, CPU <=70%, PSI <=1%; auto ưu tiên GPU khi
VRAM >=4 GiB và utilization <70%, ổn định 3 mẫu. Thu hồi RAM <1 GiB / PSI >5%
/ VRAM <768 MiB; CPU >92% / GPU >95% kéo dài 3 mẫu; cooldown 30s. Snapshot
không reserve tài nguyên: OOM/driver/kernel vẫn là rủi ro được ghi trong audit.

Không đo watt/joule; CPU-seconds nằm trong JSON. Nhiều core giảm wall latency
nhưng tăng CPU cost. Không nội suy sang máy yếu; cơ chế admission có thể giữ
heuristic toàn bộ phiên trên máy ít RAM. Trước khi tin quyết định model cần
tập terminal độc lập, calibration và kiểm chứng false-positive/abstention.

Tái lập trong `conda activate bqp`:

```zsh
python scripts/fetch_laya.py
python scripts/benchmark_laya.py
python scripts/verify_laya_lifecycle.py
python scripts/report_laya.py
PYTHONPATH=src python -m unittest discover -s tests -v
JIS_MODEL_TEST=cpu PYTHONPATH=src python tests/integration_zsh.py
JIS_MODEL_TEST=cuda PYTHONPATH=src python tests/integration_zsh.py
```

[JSON đo đầy đủ](laya-benchmark.json), [lifecycle/ambiguity JSON](laya-lifecycle.json),
[bảo mật/rủi ro](security-review.md), [test summary](verification-model.md).
Primary model cards: [base](https://huggingface.co/convaiinnovations/laya),
[typed](https://huggingface.co/convaiinnovations/laya-typed-decisions).
"""
    (ROOT/"docs/laya-results.md").write_text(text)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    base=[c for c in data["configs"] if c["model"]=="base"]
    labels=[f"CPU {c['threads']}" if c["device"]=="cpu" else "RTX 3060" for c in base]
    plt.rcParams.update({"font.size":10,"axes.spines.right":False,"axes.spines.top":False})
    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    axes[0,0].bar(labels,[c["warm"]["p95_ms"] for c in base],color="#2563eb")
    axes[0,0].axhline(75,color="#dc2626",linestyle="--",label="UI wait budget (not inference cancellation)")
    axes[0,0].set(title="Base Laya: warm predict p95",ylabel="ms");axes[0,0].legend(fontsize=8)
    axes[0,1].bar(labels,[c["memory"]["rss_mib"] for c in base],color="#0d9488")
    axes[0,1].set(title="Loaded worker RSS (runtime included)",ylabel="MiB")
    axes[1,0].plot(labels[:-1],[c["warm"]["cpu_seconds"]/40*1000 for c in base[:-1]],"o-",label="CPU time",color="#dc2626")
    axes[1,0].plot(labels[:-1],[c["warm"]["p50_ms"] for c in base[:-1]],"o-",label="Wall p50",color="#2563eb")
    axes[1,0].set(title="CPU cost per prediction",ylabel="ms");axes[1,0].legend()
    axes[1,1].bar([r["device"] for r in lifecycle],[r["unloaded_parent_memory"]["rss_mib"] for r in lifecycle],color="#0d9488")
    axes[1,1].set(title="Lifecycle harness RSS after worker eviction",ylabel="MiB")
    fig.suptitle("JIS / Laya — Ryzen 7 7700 + RTX 3060\nPinned physical cores; local checkpoints; process-based release",fontsize=14)
    fig.savefig(ROOT/"docs/laya-benchmark.png",dpi=160);plt.close(fig)


if __name__=="__main__":
    main()
