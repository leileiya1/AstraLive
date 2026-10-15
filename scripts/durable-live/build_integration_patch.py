"""Reproducible shared-file patch for Agent 4, based on the pinned main sources."""
from pathlib import Path
import difflib
root=Path(__file__).resolve().parents[2]
changes={}
def edit(path,fn):
 old=(root/path).read_text(); new=fn(old)
 assert new!=old,path
 changes[path]=(old,new)
def service(s):
 s=s.replace('"astralive/backend/internal/fsm"','"astralive/backend/internal/fsm"\n "astralive/backend/internal/durablelive"')
 s=s.replace('type Service struct {','type Service struct {\n Durable *durablelive.Store // nil keeps legacy behavior\n')
 for signature,empty in [('func (s *Service) Start(ctx context.Context, id, trace string) (string, error) {','""'),('func (s *Service) Stop(ctx context.Context, id, trace string) (string, error) {','""'),('func (s *Service) Interrupt(ctx context.Context, id, trace, reason string) (runtime.Operation, error) {','runtime.Operation{}'),('func (s *Service) Speak(ctx context.Context, id, text string, priority int32, policy, source, trace string, platform *runtimeapi.PlatformContext) (dbgen.Utterance, error) {','dbgen.Utterance{}'),('func (s *Service) speak(ctx context.Context, id, text string, priority int32, policy, source, trace string, platform *runtimeapi.PlatformContext) (dbgen.Utterance, error) {','dbgen.Utterance{}')]:
  assert signature in s
  s=s.replace(signature,signature+'\n if s.Durable!=nil {managed,err:=s.Durable.IsManagedSession(ctx,id);if err!=nil{return '+empty+',err};if managed{return '+empty+',ErrConflict}}')
 return s
edit('backend/internal/app/service.go',service)
def consumer(s):
 s=s.replace('"astralive/backend/internal/app"','"astralive/backend/internal/app"\n "astralive/backend/internal/durablelive"')
 s=s.replace('type Consumer struct {','type Consumer struct {\n Durable *durablelive.Store\n')
 s=s.replace('return &Consumer{r, s, stream, "astralive-go", fmt.Sprintf("backend-%d", time.Now().UnixNano()), l, map[string]int{}}','return &Consumer{Durable:s.Durable,Redis:r,Service:s,Stream:stream,Group:"astralive-go",Name:fmt.Sprintf("backend-%d",time.Now().UnixNano()),Log:l,failures:map[string]int{}}')
 s=s.replace('_, e = c.Service.ApplyEvent(ctx, ev)','''managed:=false
  if c.Durable!=nil { if e=ev.Validate();e==nil {managed,e=c.Durable.ObserveLegacyEvent(ctx,raw)} }
  if e==nil && !managed {_,e=c.Service.ApplyEvent(ctx,ev)}''')
 return s
edit('backend/internal/eventbus/consumer.go',consumer)
def http(s):
 s=s.replace('type Server struct {','type Server struct {\n DurableHandler http.Handler // already authenticates distinct v0.5 service roles\n')
 needle='func (h *Server) Router() http.Handler {'
 s=s.replace(needle,'''func (h *Server) Router() http.Handler {
 legacy:=h.legacyRouter()
 return http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  if strings.HasPrefix(r.URL.Path,"/internal/v0.5/") && h.DurableHandler!=nil {h.DurableHandler.ServeHTTP(w,r);return}
  legacy.ServeHTTP(w,r)
 })
}
func (h *Server) legacyRouter() http.Handler {''')
 return s
edit('backend/internal/httpapi/server.go',http)
def runtime(s):
 signature='def create_app(settings: Settings | None = None, publisher=None, factories=None) -> FastAPI:'
 assert signature in s
 s=s.replace(signature,'def create_app(settings: Settings | None = None, publisher=None, factories=None, durable_registration=None) -> FastAPI:')
 s=s.replace('    settings = settings or Settings.from_env()','''    durable_enabled = os.getenv("ASTRALIVE_DURABLE_LIVE_ENABLED", "false").lower() == "true"
    if durable_enabled and durable_registration is None:
        raise RuntimeError("Durable Live requires registered journal, guardian and exact-text adapters")
    settings = settings or Settings.from_env()''',1)
 # Router guards the unchanged legacy v1 calls for managed physical Sessions.
 idx=s.index('    return app\n')
 s=s[:idx]+'''    if durable_enabled:
        for durable_router in durable_registration.routers:
            app.include_router(durable_router)
        @app.middleware("http")
        async def durable_mode_guard(request: Request, call_next):
            prefix = "/internal/v1/sessions/"
            if request.url.path.startswith(prefix):
                sid = request.url.path[len(prefix):].split("/", 1)[0]
                if durable_registration.owns_session(sid):
                    return JSONResponse({"detail": "durable Session requires v0.5 control"}, status_code=409)
            return await call_next(request)
''' + s[idx:]
 return s
edit('runtime/app/main.py',runtime)
edit('runtime/requirements.txt',lambda s:s+'\n# v0.5 frozen request/response validation (default-off integration).\njsonschema>=4,<5\n')
patch=''.join(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='a/'+p,tofile='b/'+p)) for p,(a,b) in changes.items())
(root/'docs/v0.5/integration/agent-2-shared.patch').write_text(patch)
print('shared patch:',len(changes),'files')
