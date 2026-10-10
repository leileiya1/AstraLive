"""Build an allowlisted service release; optionally attach an existing offline lab snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from .config import Config, digest


def build(out, config=None):
    source = Path(__file__).resolve().parent
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('RELEASE_OUTPUT_EXISTS')
    out.mkdir(parents=True, mode=0o700)
    paths = [p for p in source.rglob('*') if p.is_file() and not p.is_symlink()
             and p.relative_to(source).parts[0] not in {'.venv-tests', 'tests', 'evidence', '__pycache__'}
             and '__pycache__' not in p.parts and (p.suffix in {'.py', '.json', '.sh', '.md'}
                 or (p.suffix == '.txt' and p.parent == source/'deploy'))]
    for p in paths:
        target = out / 'gpu_worker' / p.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        if p.suffix == '.sh':
            target.chmod(0o700)
    shutil.copyfile(source/'deploy/install.sh', out/'install.sh')
    (out/'install.sh').chmod(0o700)
    sample = source.parent/'astralive-avatar-lab/assets/soulx/original/official_girl.png'
    if not sample.exists():
        sample = source.parent/'sample-avatar.png'
    shutil.copyfile(sample, out/'sample-avatar.png')
    if config:
        cfg = Config.load(config)
        if cfg.mode != 'gpu':
            raise ValueError('OFFLINE_SNAPSHOT_REQUIRES_GPU_CONFIG')
        cfg.verify_assets()
        # Reuse exactly the tested deployment layout; do not attempt venv relocation.
        lab = Path(cfg.lab_root)
        if lab != Path('/root/autodl-tmp/astralive-avatar-lab'):
            raise ValueError('OFFLINE_SNAPSHOT_REQUIRES_PINNED_LAYOUT')
        if Path(cfg.python) != lab/'environments/astralive-soulx/bin/python':
            raise ValueError('OFFLINE_SNAPSHOT_REQUIRES_PINNED_PYTHON')
        if not (lab/'repositories/SoulX-FlashHead/.git').is_dir():
            raise ValueError('OFFLINE_SNAPSHOT_REQUIRES_COMPLETE_REPOSITORY')
        from .doctor import inspect
        if not inspect(cfg)['preflightPassed']:
            raise ValueError('OFFLINE_SNAPSHOT_PREFLIGHT_FAILED')
        # Lab venv was built with --system-site-packages. The target base image must
        # retain /root/miniconda3 Python3.12.3 + Torch2.8.0+cu128 (not included here).
        roots = ['environments/astralive-soulx', 'repositories/SoulX-FlashHead', 'streaming/worker-deps']
        files = ['reports/soulx-weight-manifest.json', str(Path(cfg.asset_path).relative_to(lab))]
        for row in json.loads((lab/files[0]).read_text()):
            name = 'wav2vec2-base-960h' if row['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B'
            files.append('models/soulx/'+name+'/'+row['file'])
        candidates = [lab/p for p in files]
        for root in roots:
            candidates += [p for p in (lab/root).rglob('*') if p.is_file()]
        # Large fixed tensor/native-library payloads favor fast, lossless packaging.
        with tarfile.open(out/'lab-payload.tar.gz', 'w:gz', dereference=True, compresslevel=1) as archive:
            for p in sorted(set(candidates)):
                rel = p.relative_to(lab)
                if any(x in rel.parts for x in ('__pycache__', '.cache', '.pytest_cache', 'hooks', 'logs')):
                    continue
                if p.suffix in {'.pyc', '.log'} or rel.as_posix() == 'repositories/SoulX-FlashHead/.git/config':
                    continue
                real = p.resolve()
                if not real.is_relative_to(lab.resolve()) and not real.is_relative_to(Path('/root/miniconda3')):
                    raise ValueError('OFFLINE_SNAPSHOT_EXTERNAL_LINK')
                # Materialize file symlinks; no paths to secrets/state or link traversal.
                archive.add(p, arcname=rel.as_posix(), recursive=False)
        (out/'payload.json').write_text(json.dumps(dict(version=1, labRoot=str(lab), basePrefix='/root/miniconda3', python='3.12.3', torch='2.8.0+cu128', cuda='12.8'))+'\n')
    manifest = {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    release_id = hashlib.sha256(encoded).hexdigest()
    (out/'MANIFEST.json').write_text(json.dumps(dict(version=1, releaseId=release_id, files=manifest), indent=2)+'\n')
    return release_id


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--archive', help='Write portable tar.gz without macOS metadata')
    p.add_argument('--with-lab-config', help='Export on the existing validated GPU host only; no downloads')
    a = p.parse_args()
    release_id = build(a.out, a.with_lab_config)
    if a.archive:
        target = Path(a.archive).resolve()
        if target.exists() or target.is_relative_to(Path(a.out).resolve()):
            raise ValueError('RELEASE_ARCHIVE_OUTPUT_INVALID')
        with tarfile.open(target, 'w:gz', compresslevel=1) as archive:
            for path in sorted(Path(a.out).rglob('*')):
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(a.out).as_posix(), recursive=False)
    print(json.dumps(dict(releaseId=release_id, includesOfflineLab=bool(a.with_lab_config))))


if __name__ == '__main__':
    main()
