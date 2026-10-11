"""Download pinned Laya checkpoints with streaming SHA256 verification.

No installs, pickle, remote Python or other checkpoints are downloaded.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "base": ("convaiinnovations/laya", "7b928d828b7b0e022f929d9bd2e44165aa270148"),
    "typed": ("convaiinnovations/laya-typed-decisions", "e929ae5cf69bc34259cd2f95c9e91145b818b1f0"),
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, target, size, expected=None):
    if target.is_file() and target.stat().st_size == size and (not expected or digest(target) == expected):
        return
    temporary = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "JIS/0.2"})
    h, count, progress = hashlib.sha256(), 0, 0
    with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as output:
        while chunk := source.read(1024*1024):
            count += len(chunk)
            if count > size:
                raise ValueError("Download exceeds pinned file size")
            h.update(chunk); output.write(chunk)
            if count-progress >= 64*1024*1024:
                print(target.name, f"{count/1024**2:.0f}/{size/1024**2:.0f} MiB", flush=True)
                progress = count
    if count != size or (expected and h.hexdigest() != expected):
        raise ValueError("Download integrity mismatch: " + str(target))
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("base", "typed", "both"), default="both")
    args = parser.parse_args()
    for name in MODELS if args.model == "both" else [args.model]:
        repo, revision = MODELS[name]
        checkpoint = ROOT / "models" / ("laya-"+name)
        url = f"https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true"
        with urllib.request.urlopen(url, timeout=60) as response:
            tree = json.load(response)
        files = []
        for entry in tree:
            path = entry["path"]
            if entry["type"] != "file" or not (path in {"rl_agent_config.json", "model.safetensors", "README.md"} or path.startswith(("encoder/", "tokenizer/"))):
                continue
            if Path(path).is_absolute() or ".." in Path(path).parts or path.endswith((".pt", ".bin", ".py")):
                raise ValueError("Unexpected checkpoint file: " + path)
            target = checkpoint / path
            expected = entry.get("lfs", {}).get("oid")
            download(f"https://huggingface.co/{repo}/resolve/{revision}/{path}?download=true", target, entry["size"], expected)
            source_hash = digest(target)
            # Apply the SDK's documented compatibility normalization once, so
            # repeated offline loads do not mutate an integrity-checked artifact.
            if path == "tokenizer/tokenizer_config.json":
                cfg = json.loads(target.read_text())
                if cfg.get("tokenizer_class") in (None, "TokenizersBackend"):
                    cfg["tokenizer_class"] = "PreTrainedTokenizerFast"
                    cfg.pop("backend", None); cfg.pop("is_local", None)
                if isinstance(cfg.get("extra_special_tokens"), list):
                    cfg["extra_special_tokens"] = {f"extra_{i}": token for i, token in enumerate(cfg["extra_special_tokens"])}
                target.write_text(json.dumps(cfg, indent=2)+"\n")
            files.append({"path": path, "bytes": target.stat().st_size, "sha256": digest(target), "source_sha256": source_hash})
        manifest = {"repo": repo, "revision": revision, "format": "safetensors",
                    "sdk_version": importlib.metadata.version("laya"), "files": files}
        (checkpoint / "jis-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        (ROOT / "docs" / ("laya-"+name+"-manifest.json")).write_text(json.dumps(manifest, indent=2)+"\n")
        print("Ready:", checkpoint, flush=True)


if __name__ == "__main__":
    main()
