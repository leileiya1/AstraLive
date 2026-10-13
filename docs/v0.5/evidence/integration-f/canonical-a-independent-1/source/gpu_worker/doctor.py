"""Read-only, bounded preflight. Never installs dependencies or loads model weights."""
import argparse
import json
from pathlib import Path
import subprocess
from .config import Config, REVISION


def inspect(cfg):
    findings = []
    def record(name, ok, code):
        findings.append(dict(check=name, ok=bool(ok), code=code))
    try:
        cfg.verify_assets()
        record('assets', True, 'SIMULATION' if cfg.mode == 'simulation' else 'SHA256_VERIFIED')
    except Exception:
        record('assets', False, 'PINNED_ASSETS_MISSING_OR_CHANGED')
    py = Path(cfg.python)
    record('python', py.is_file(), 'PRESENT' if py.is_file() else 'PYTHON_MISSING')
    if py.is_file():
        script = '''
import importlib, json, sys
result = {'python': sys.version.split()[0], 'versions': {}, 'missing': []}
for name in ('torch', 'numpy', 'av', 'flash_attn'):
    try:
        mod = importlib.import_module(name)
        result['versions'][name] = mod.__version__
        if name == 'torch':
            result['cuda'] = mod.version.cuda
            result['available'] = mod.cuda.is_available()
            result['capability'] = list(mod.cuda.get_device_capability()) if result['available'] else None
    except Exception:
        result['missing'].append(name)
print(json.dumps(result))
'''
        # Same existing PyAV location; no ambient PYTHONPATH or business credentials.
        from .supervisor import child_environment
        env = child_environment()
        env['PYTHONPATH'] = str(Path(cfg.lab_root) / 'streaming/worker-deps')
        try:
            out = subprocess.run([cfg.python, '-c', script], env=env, capture_output=True, text=True, timeout=30, check=True)
            info = json.loads(out.stdout)
            versions = info['versions']
            required = ('torch', 'numpy', 'av') if cfg.mode == 'simulation' else ('torch', 'numpy', 'av', 'flash_attn')
            record('dependencies', all(n in versions for n in required), 'DEPENDENCIES_PRESENT' if all(n in versions for n in required) else 'DEPENDENCIES_MISSING')
            if cfg.mode == 'gpu':
                pinned = info['python'] == '3.12.3' and versions.get('torch') == '2.8.0+cu128' and versions.get('flash_attn') == '2.8.3' and info.get('cuda') == '12.8'
                record('environment', pinned, 'PINNED_ENVIRONMENT_MATCH' if pinned else 'PINNED_ENVIRONMENT_MISMATCH')
                cap = info.get('capability')
                compatible = info.get('available') and cap and cap[0] in (8, 9)
                record('gpuArchitecture', compatible, 'FLASH_ATTENTION_ARCHITECTURE_SUPPORTED' if compatible else 'GPU_ARCHITECTURE_UNSUPPORTED_OR_UNAVAILABLE')
        except Exception:
            record('dependencies', False, 'ENVIRONMENT_PROBE_FAILED')
    if cfg.mode == 'gpu':
        source = Path(cfg.lab_root) / 'repositories/SoulX-FlashHead'
        try:
            rev = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            dirty = subprocess.run(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], capture_output=True, timeout=5, check=True).stdout
            record('source', rev == REVISION and not dirty, 'PINNED_SOURCE_MATCH' if rev == REVISION and not dirty else 'PINNED_SOURCE_MISMATCH')
        except Exception:
            record('source', False, 'PINNED_SOURCE_MISSING')
    import shutil
    parent = Path(cfg.state_dir)
    while not parent.exists():
        parent = parent.parent
    record('disk', shutil.disk_usage(parent).free >= cfg.minimum_free_disk_bytes, 'DISK_CHECKED')
    return dict(workerRef=cfg.worker_ref, mode=cfg.mode, preflightPassed=all(f['ok'] for f in findings), modelLoaded=False, checks=findings)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    cfg = Config.load(p.parse_args().config)
    result = inspect(cfg)
    print(json.dumps(result))
    return 0 if result['preflightPassed'] else 78


if __name__ == '__main__':
    raise SystemExit(main())
