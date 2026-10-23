import { SettingsCenter } from "../features/settings/SettingsCenter";
import { useState } from "react";
import {
  AnimatePresence,
  LazyMotion,
  MotionConfig,
} from "motion/react";
import * as m from "motion/react-m";
const loadMotionFeatures = () => import("./motion-features").then(module => module.default);
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Dashboard } from "../pages/Dashboard";
import { Avatars } from "../features/avatars/Avatars";
import { Voices } from "../features/voices/Voices";
import { Products } from "../features/products/Products";
import { Rooms } from "../features/rooms/Rooms";
import { LiveConsole } from "../features/live-console/LiveConsole";
import { useUi } from "../stores/ui";
import { TooltipProvider } from "../components/ui/tooltip";
import { MobileNav, Sidebar, pageTitles, type Page } from "./Sidebar";
import { Topbar } from "./Topbar";
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10000 } },
});
function Shell() {
  const [page, setPage] = useState<Page>("dashboard");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const roomId = useUi((s) => s.selectedRoomId);
  const setRoom = useUi((s) => s.setSelectedRoomId);
  const open = useUi((s) => s.sidebarOpen);
  const setOpen = useUi((s) => s.setSidebarOpen);
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, enabled: !!roomId });
  const roomName = rooms.data?.find((r) => r.roomId === roomId)?.name;
  return (
    <div className="flex min-h-dvh w-full min-w-[320px] text-fg">
      <Sidebar page={page} onNavigate={setPage} expanded={open} onToggle={() => setOpen(!open)} />
      <MobileNav page={page} onNavigate={setPage} open={drawer} onOpenChange={setDrawer} />
      <main className="flex min-w-0 flex-1 flex-col">
        <Topbar
          title={pageTitles[page]}
          sessionId={sessionId}
          roomName={roomName}
          onMenu={() => setDrawer(true)}
          onOpenConsole={() => setPage("console")}
        />
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={page}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className="mx-auto w-full max-w-[1600px] min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-7"
          >
            {page === "settings" && <SettingsCenter />}
            {page === "dashboard" && <Dashboard sessionId={sessionId} />}
            {page === "avatars" && <Avatars />}
            {page === "voices" && <Voices />}
            {page === "products" && <Products />}
            {page === "rooms" && (
              <Rooms
                onConsole={(id) => {
                  setRoom(id);
                  setSessionId(null);
                  setPage("console");
                }}
              />
            )}
            {page === "console" && (
              <LiveConsole
                roomId={roomId}
                sessionId={sessionId}
                onSession={setSessionId}
              />
            )}
          </m.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LazyMotion features={loadMotionFeatures} strict>
        <MotionConfig
          reducedMotion="user"
          transition={{ duration: 0.18, ease: "easeOut" }}
        >
          <TooltipProvider delayDuration={250}>
            <Shell />
          </TooltipProvider>
        </MotionConfig>
      </LazyMotion>
    </QueryClientProvider>
  );
}
