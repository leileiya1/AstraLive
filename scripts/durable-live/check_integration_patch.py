"""Apply shared wiring only to an owned temporary snapshot and run Go checks."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='astralive-agent2-integration-',dir='/tmp') as tmp:
    target=Path(tmp)
    archive=subprocess.check_output(['git','archive','HEAD'],cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(target,filter='data')
    for file in ['backend/db/migrate.go','backend/db/migrations/000006_durable_live.sql','backend/go.mod','backend/go.sum','runtime/app/durable_live_journal.py']:
        shutil.copy2(root/file,target/file)
    shutil.copytree(root/'backend/internal/durablelive',target/'backend/internal/durablelive',dirs_exist_ok=True)
    subprocess.run(['git','apply',str(root/'docs/v0.5/integration/agent-2-shared.patch')],cwd=target,check=True)
    files=['backend/internal/app/service.go','backend/internal/eventbus/consumer.go','backend/internal/httpapi/server.go']
    subprocess.run(['gofmt','-w',*files],cwd=target,check=True)
    env=os.environ.copy()
    for key in list(env):
        if ('DATABASE' in key or 'REDIS' in key or key.startswith('DURABLE_LIVE_')):env.pop(key)
    subprocess.run(['go','test','./...'],cwd=target/'backend',env=env,check=True)
    subprocess.run([os.environ.get('DURABLE_LIVE_TEST_PYTHON','python3'),'-m','py_compile','runtime/app/main.py','runtime/app/durable_live_journal.py'],cwd=target,check=True)
    print('PASS: shared patch applies to pinned snapshot; full Go regression and Python compilation passed; shared working files unchanged')
