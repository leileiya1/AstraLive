"""Idempotent operator installation. Config and tokens survive code upgrades."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shlex
import shutil
import sys
import tarfile
import tempfile
from .config import Config, digest


def verify_bundle(bundle):
    manifest = json.loads((bundle/'MANIFEST.json').read_text())
    files = manifest['files']
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    if manifest['version'] != 1 or manifest['releaseId'] != hashlib.sha256(encoded).hexdigest():
        raise ValueError('RELEASE_MANIFEST_INVALID')
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual != set(files) | {'MANIFEST.json'}:
        raise ValueError('RELEASE_FILE_SET_MISMATCH')
    for name, sha in files.items():
        path = bundle/name
        if path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()) or digest(path) != sha:
            raise ValueError('RELEASE_SHA256_MISMATCH')
    return manifest['releaseId']


def restore_lab(bundle, lab):
    meta = json.loads((bundle/'payload.json').read_text())
    if meta.get('version') != 1 or str(lab) != meta['labRoot']:
        raise ValueError('OFFLINE_LAYOUT_MISMATCH')
    if lab.exists():
        raise ValueError('OFFLINE_RESTORE_REFUSES_EXISTING_LAB')
    import subprocess
    script = 'import torch,sys; assert sys.version_info[:3]==(3,12,3); assert torch.__version__=="2.8.0+cu128"; assert torch.version.cuda=="12.8"'
    try:
        subprocess.run(['/root/miniconda3/bin/python', '-c', script], capture_output=True, timeout=30, check=True)
    except Exception:
        raise ValueError('OFFLINE_BASE_IMAGE_MISMATCH') from None
    lab.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.soulx-restore-', dir=lab.parent) as tmp:
        with tarfile.open(bundle/'lab-payload.tar.gz') as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if name.is_absolute() or '..' in name.parts or not member.isfile():
                    raise ValueError('OFFLINE_PAYLOAD_UNSAFE_MEMBER')
                archive.extract(member, tmp, filter='data')
        os.rename(tmp, lab)
        # TemporaryDirectory cleanup tolerates the atomically moved directory.


def install(bundle, root, *, lab_root=None, python=None, mode='gpu', worker_ref='soulx-lite-01', port=17087, management_port=17088, restore=False):
    os.umask(0o077)
    bundle, root = Path(bundle).resolve(), Path(root).resolve()
    release_id = verify_bundle(bundle)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_path = root/'config/worker.json'
        settings_path = root/'settings.json'
        if config_path.exists():
            cfg = Config(**json.loads(config_path.read_text()))
            cfg.validate()
            # Reject even a STARTING supervisor; don't replace files beneath a process.
            state = Path(cfg.state_dir)
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (state/'supervisor.lock').open('a') as active:
                try:
                    fcntl.flock(active, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('STOP_WORKER_BEFORE_UPGRADE') from None
                # A reboot can leave the socket/READY snapshot behind. The
                # acquired kernel lock proves no supervisor owns this state.
            # Re-running install does not rotate tokens, change ports, mode or paths.
            if (lab_root and str(Path(lab_root).resolve()) != cfg.lab_root) or (python and str(Path(python).absolute()) != cfg.python):
                raise ValueError('EXISTING_CONFIGURATION_CONFLICT')
            if restore:
                restore_lab(bundle, Path(cfg.lab_root))
        else:
            cfg_data = json.loads((bundle/'gpu_worker/deploy/worker.example.json').read_text())
            lab = Path(lab_root or cfg_data['lab_root']).resolve()
            if restore:
                restore_lab(bundle, lab)
            image = lab/'assets/soulx/original/official_girl.png'
            if mode == 'simulation':
                # A bundled, immutable sample portrait is included only for explicit CPU tests.
                image = bundle/'sample-avatar.png'
                if not image.exists():
                    raise ValueError('SIMULATION_SAMPLE_MISSING')
                asset_sha = digest(image)
            else:
                asset_sha = cfg_data['asset_sha256']
            for sub in ('config', 'secrets', 'state', 'bin', 'releases'):
                (root/sub).mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in ('worker-token', 'management-token'):
                p = root/'secrets'/name
                if not p.exists():
                    with p.open('x') as f:
                        f.write(secrets.token_hex(32)+'\n')
                p.chmod(0o600)
            # Simulation sample lives in a persistent location, never a release input dir.
            if mode == 'simulation':
                shutil.copyfile(image, root/'config/sample-avatar.png')
                image = root/'config/sample-avatar.png'
            cfg_data.update(worker_ref=worker_ref, lab_root=str(lab), asset_path=str(image), asset_sha256=asset_sha,
                            python=str(Path(python).absolute()) if python else str(lab/'environments/astralive-soulx/bin/python'),
                            state_dir=str(root/'state'), token_file=str(root/'secrets/worker-token'),
                            management_token_file=str(root/'secrets/management-token'), mode=mode, port=port, management_port=management_port)
            cfg = Config(**cfg_data)
            cfg.validate()
            config_path.write_text(json.dumps(cfg_data, indent=2)+'\n')
            config_path.chmod(0o600)
        destination = root/'releases'/release_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            for name, sha in json.loads((bundle/'MANIFEST.json').read_text())['files'].items():
                if (name.startswith('gpu_worker/') or name == 'sample-avatar.png') and digest(destination/name) != sha:
                    raise ValueError('INSTALLED_RELEASE_CHANGED')
        if not destination.exists():
            with tempfile.TemporaryDirectory(prefix='.release-', dir=destination.parent) as tmp:
                shutil.copytree(bundle/'gpu_worker', Path(tmp)/'gpu_worker', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                shutil.copyfile(bundle/'sample-avatar.png', Path(tmp)/'sample-avatar.png')
                (Path(tmp)/'MANIFEST.json').write_text((bundle/'MANIFEST.json').read_text())
                os.rename(tmp, destination)
        # Atomic symlink replacement, with previous code available for operator rollback.
        current = root/'current'
        if current.exists() and current.resolve() != destination:
            previous = root/'.previous-new'
            previous.unlink(missing_ok=True)
            previous.symlink_to(current.resolve(), target_is_directory=True)
            os.replace(previous, root/'previous')
        link = root/'.current-new'
        link.unlink(missing_ok=True)
        link.symlink_to(destination, target_is_directory=True)
        os.replace(link, current)
        settings_path.write_text(json.dumps(dict(version=1, root=str(root), config=str(config_path), releaseId=release_id))+'\n')
        launcher = root/'bin/astralive-worker'
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd '+shlex.quote(str(current))+'\nexec '+shlex.quote(sys.executable)+' -B -m gpu_worker.manage --root '+shlex.quote(str(root))+' "$@"\n')
        launcher.chmod(0o700)
        return dict(installed=True, workerRef=cfg.worker_ref, mode=cfg.mode, releaseId=release_id, command=str(launcher), ready=False, modelLoaded=False)


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('BOOTSTRAP_PYTHON_3_12_REQUIRED')
    p = argparse.ArgumentParser()
    p.add_argument('--bundle', required=True)
    p.add_argument('--root', default='/root/autodl-tmp/astralive-services/soulx-lite-01')
    p.add_argument('--lab-root')
    p.add_argument('--python')
    p.add_argument('--mode', choices=['gpu', 'simulation'], default='gpu')
    p.add_argument('--worker-ref', default='soulx-lite-01')
    p.add_argument('--port', type=int, default=17087)
    p.add_argument('--management-port', type=int, default=17088)
    p.add_argument('--restore-lab', action='store_true')
    a = p.parse_args()
    try:
        result = install(a.bundle, a.root, lab_root=a.lab_root, python=a.python, mode=a.mode, worker_ref=a.worker_ref,
                         port=a.port, management_port=a.management_port, restore=a.restore_lab)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        allowed = {'RELEASE_OUTPUT_EXISTS', 'RELEASE_MANIFEST_INVALID', 'RELEASE_FILE_SET_MISMATCH', 'RELEASE_SHA256_MISMATCH',
                   'STOP_WORKER_BEFORE_UPGRADE', 'EXISTING_CONFIGURATION_CONFLICT', 'OFFLINE_LAYOUT_MISMATCH', 'INSTALLED_RELEASE_CHANGED',
                   'OFFLINE_RESTORE_REFUSES_EXISTING_LAB',
                   'OFFLINE_BASE_IMAGE_MISMATCH', 'OFFLINE_PAYLOAD_UNSAFE_MEMBER', 'SIMULATION_SAMPLE_MISSING'}
        print(json.dumps(dict(installed=False, error=str(exc) if str(exc) in allowed else 'INSTALL_FAILED')), file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
