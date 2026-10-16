"""Apply Agent 4 Scheduler patch in a disposable CPU tree, never this worktree."""
from pathlib import Path
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
root = Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory(prefix='astralive-agent3-patch-') as tmp:
    dest = Path(tmp)
    archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        tree.extractall(dest)
    for package in ['contentplan', 'turnmanager']:
        target = dest / 'backend/internal' / package
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(root / 'backend/internal' / package, target)
    subprocess.run(['git', 'apply', '--unidiff-zero', str(root / 'docs/v0.5/agent-3/scheduler-members.patch')], cwd=dest, check=True)
    (dest / 'backend/internal/turnmanager/preserved_sources_test.go').write_text('''package turnmanager
import (
 "astralive/backend/internal/interaction"
 "astralive/backend/internal/platform"
 "context"
 "testing"
)
func TestPatchedSchedulerSelectsDuringBusyScript(t *testing.T){
 f:=newFake(t,3);m:=f.manager(t);assertNext(t,m,"SCRIPT",1)
 adapter:=&SelectionAdapter{m,PreservedSources{}}
 cfg:=interaction.DefaultConfig()
 mapping:=platform.Mapping{Platform:"mock",PlatformRoomID:"room",RoomID:"room",SessionID:"session"}
 scheduler,e:=interaction.New(cfg,mapping,"product",adapter,func(context.Context)(interaction.Gate,error){return interaction.Gate{Running:true,Busy:true,SelectionOnly:true,CurrentSource:"AUTO_SCRIPT",ProductID:"product"},nil},f.clock,nil);if e!=nil{t.Fatal(e)}
 for _,id:=range []string{"a","b","c"}{e:=scheduler.Receive(background,platform.Event{Platform:"mock",PlatformRoomID:"room",InternalRoomID:"room",SessionID:"session",EventType:platform.Comment,SourceEventID:id,UserExternalID:id,Transport:"mock",Content:"这款有XL吗？"});if e!=nil{t.Fatal(e)}}
 if e=scheduler.Tick(background);e!=nil{t.Fatal(e)}
 snap:=scheduler.Snapshot();if snap.Counters.Merged!=2||snap.Counters.Delivered!=1||len(snap.Current.Members)!=3{t.Fatal(snap)}
 if len(f.turns[snap.UtteranceID].SourceIdentities)!=3||f.claimCount!=1{t.Fatal("lost identity or concurrent media")}
 if choice:=step(t,m);choice.State!=YieldPending{t.Fatal(choice)}
}
''')
    subprocess.run(['go', 'test', '-race', './internal/interaction', './internal/contentplan/...', './internal/turnmanager/...'], cwd=dest / 'backend', check=True, env={k:v for k,v in os.environ.items() if k!='ASTRALIVE_DIRECTOR_EVIDENCE'})
print('PASS: unapplied Scheduler patch compiled/tested in disposable CPU tree; shared files untouched')
