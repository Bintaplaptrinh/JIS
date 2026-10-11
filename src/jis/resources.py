"""Linux resource observations and pure, hysteretic admission policy (no torch)."""
from dataclasses import dataclass, asdict
import os
from pathlib import Path

MIB = 1024*1024


@dataclass(frozen=True)
class Snapshot:
    available_mib: float
    cpu_busy: float
    memory_psi: float = 0
    gpu_free_mib: float | None = None
    gpu_busy: float | None = None
    valid: bool = True

    def json(self):
        return asdict(self)


class ResourceProbe:
    def __init__(self):
        self.previous = None
        self.cgroup = self._cgroup()

    @staticmethod
    def _cgroup():
        try:
            relative = next(line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
            root = Path("/sys/fs/cgroup")
            candidate = root / relative.lstrip("/")
            # In cgroup namespaces the host-relative path may be invisible or
            # contain '..'; the mounted root is then our effective ancestor.
            return candidate if ".." not in candidate.parts and candidate.is_dir() else root
        except (OSError, StopIteration):
            return Path("/sys/fs/cgroup")

    def sample(self):
        try:
            memory = {line.split(":")[0]: int(line.split()[1])/1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.split(":")[0] in {"MemAvailable", "MemTotal"}}
            available = memory["MemAvailable"]
            # Ancestor cgroup limits apply even when this leaf has memory.max=max.
            node = self.cgroup
            while node == Path("/sys/fs/cgroup") or Path("/sys/fs/cgroup") in node.parents:
                try:
                    maximum = (node/"memory.max").read_text().strip()
                    if maximum != "max":
                        available = min(available, max(0, int(maximum)-int((node/"memory.current").read_text()))/MIB)
                except (OSError, ValueError):
                    pass
                if node == Path("/sys/fs/cgroup"):
                    break
                node = node.parent
            values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(values), values[3]+values[4]
            busy = 0.0
            if self.previous and total > self.previous[0]:
                busy = 1-(idle-self.previous[1])/(total-self.previous[0])
            self.previous = total, idle
            # Load includes tasks blocked on I/O; conservatively respect affinity
            # and cgroup CPU quota, including inherited ancestor quotas.
            cores = len(os.sched_getaffinity(0))
            node = self.cgroup
            while node == Path("/sys/fs/cgroup") or Path("/sys/fs/cgroup") in node.parents:
                try:
                    quota, period = (node/"cpu.max").read_text().split()
                    if quota != "max":
                        cores = min(cores, int(quota)/int(period))
                except (OSError, ValueError, ZeroDivisionError):
                    pass
                if node == Path("/sys/fs/cgroup"):
                    break
                node = node.parent
            busy = max(busy, min(1, os.getloadavg()[0]/max(.1, cores)))
            psi = 0.0
            for path in (Path("/proc/pressure/memory"), self.cgroup/"memory.pressure"):
                try:
                    lines = path.read_text().splitlines()
                    psi = max(psi, float(next(x.split("=")[1] for x in lines[0].split() if x.startswith("avg10="))))
                except (OSError, ValueError, StopIteration, IndexError):
                    pass
            return Snapshot(available, max(0, min(1, busy)), psi)
        except (OSError, ValueError, KeyError, IndexError):
            return Snapshot(0, 1, valid=False)


@dataclass(frozen=True)
class ResourcePolicy:
    load_ram_mib: int = 6144
    unload_ram_mib: int = 1024
    load_gpu_mib: int = 4096
    unload_gpu_mib: int = 768
    load_cpu: float = .70
    unload_cpu: float = .92
    idle_seconds: float = 120
    cooldown_seconds: float = 30
    stable_samples: int = 3

    def admit(self, sample, preferred):
        if not sample.valid or sample.available_mib < self.load_ram_mib or sample.cpu_busy > self.load_cpu or sample.memory_psi > 1:
            return None
        gpu_ok = sample.gpu_free_mib is not None and sample.gpu_free_mib >= self.load_gpu_mib and (sample.gpu_busy or 0) < 70
        if preferred in {"auto", "cuda"} and gpu_ok:
            return "cuda"
        return "cpu" if preferred in {"auto", "cpu"} else None

    def pressure(self, sample, device):
        if not sample.valid:
            return "resource_probe_failed"
        if sample.available_mib < self.unload_ram_mib or sample.memory_psi > 5:
            return "memory_pressure"
        if sample.cpu_busy > self.unload_cpu:
            return "cpu_pressure"
        if device == "cuda" and (sample.gpu_free_mib is None or sample.gpu_free_mib < self.unload_gpu_mib or (sample.gpu_busy or 0) > 95):
            return "gpu_pressure"
        return None
