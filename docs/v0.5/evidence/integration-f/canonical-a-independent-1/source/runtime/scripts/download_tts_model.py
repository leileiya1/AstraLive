"""Download the pinned development-only Chinese VITS model."""
import argparse
import hashlib
from pathlib import Path
import tarfile
from urllib.request import urlopen


URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-zh_CN-xiao_ya-medium.tar.bz2"
SHA256 = "9396a3dffbb95b037acaa18094500f58d0db9a7c4f2689554e2539717cf0db65"
NAME = "vits-piper-zh_CN-xiao_ya-medium"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".local")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f"{NAME}.tar.bz2"
    digest = hashlib.sha256()
    with urlopen(URL, timeout=60) as source, archive.open("wb") as target:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)
    if digest.hexdigest() != SHA256:
        archive.unlink()
        raise ValueError("TTS model SHA-256 mismatch")
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if any(not ((member.name.rstrip("/") == NAME and member.isdir()) or (member.name.startswith(NAME + "/") and member.isfile())) for member in members):
            archive.unlink()
            raise ValueError("Unexpected TTS archive contents")
        tar.extractall(args.output, filter="data")
    archive.unlink()
    print(args.output / NAME)


if __name__ == "__main__":
    main()
