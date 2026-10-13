import { SettingsCenter } from "../features/settings/SettingsCenter";
import { useState } from "react";
import {
  AnimatePresence,
  LazyMotion,
  MotionConfig,
} from "motion/react";
import * as m from "motion/react-m";
const loadMotionFeatures = () => import("./motion-features").then(module => module.default);
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Activity,
  AudioLines,
  Boxes,
  LayoutDashboard,
  Menu,
  MonitorPlay,
  Radio,
  UserRound,
} from "lucide-react";
import { Dashboard } from "../pages/Dashboard";
import { Avatars } from "../features/avatars/Avatars";
import { Voices } from "../features/voices/Voices";
import { Products } from "../features/products/Products";
import { Rooms } from "../features/rooms/Rooms";
import { LiveConsole } from "../features/live-console/LiveConsole";
import { useUi } from "../stores/ui";
import { Button } from "../components/ui/button";
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10000 } },
});
type Page =
  | "dashboard"
  | "avatars"
  | "voices"
  | "products"
  | "rooms"
  | "console"
  | "settings";
const nav = [
  ["dashboard", "Dashboard", LayoutDashboard],
  ["avatars", "Avatars", UserRound],
  ["voices", "Voices", AudioLines],
  ["products", "Products", Boxes],
  ["rooms", "Live Rooms", Radio],
  ["console", "Live Console", MonitorPlay],
  ["settings", "用户配置中心", UserRound],
] as const;
function Shell() {
  const [page, setPage] = useState<Page>("dashboard");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const roomId = useUi((s) => s.selectedRoomId);
  const setRoom = useUi((s) => s.setSelectedRoomId);
  const open = useUi((s) => s.sidebarOpen);
  const setOpen = useUi((s) => s.setSidebarOpen);
  return (
    <div className="flex min-h-dvh min-w-[320px] w-full flex-col bg-slate-50 font-sans text-slate-800 md:flex-row [&_button]:cursor-pointer">
      <AnimatePresence initial={false}>
        {open && (
          <m.aside
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="w-full shrink-0 border-r border-slate-200/80 bg-white p-4 md:sticky md:top-0 md:h-dvh md:w-[clamp(12rem,15vw,15rem)] md:overflow-y-auto"
          >
            <div className="mb-8 flex items-center gap-2 text-lg font-bold text-sky-700">
              <Activity size={22} /> AstraLive
            </div>
            <nav
              aria-label="Main navigation"
              className="grid grid-cols-2 gap-1 sm:grid-cols-3 md:flex md:flex-col"
            >
              {nav.map(([id, label, Icon]) => (
                <button
                  key={id}
                  onClick={() => setPage(id)}
                  aria-current={page === id ? "page" : undefined}
                  className={`relative flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm transition-colors motion-reduce:transition-none ${page === id ? "font-semibold text-sky-800" : "text-slate-600 hover:bg-slate-100"}`}
                >
                  {page === id && (
                    <m.span
                      layoutId="navigation-active"
                      className="absolute inset-0 rounded-xl border border-sky-100 bg-sky-50"
                    />
                  )}
                  <Icon size={18} className="relative shrink-0" />
                  <span className="relative">{label}</span>
                </button>
              ))}
            </nav>
          </m.aside>
        )}
      </AnimatePresence>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center gap-3 border-b border-slate-200/80 bg-white/95 px-3 backdrop-blur sm:px-5">
          <Button
            variant="ghost"
            aria-label="Toggle sidebar"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <Menu size={18} />
          </Button>
          <span className="font-semibold">AstraLive Control</span>
          <span className="ml-auto text-xs text-slate-500">
            Go Control Plane
          </span>
        </header>
        <m.div
          key={page}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full min-w-0 flex-1 p-3 sm:p-5 lg:p-6"
        >
          {page === "settings" && <SettingsCenter />}
          {page === "dashboard" && <Dashboard sessionId={sessionId} />}{" "}
          {page === "avatars" && <Avatars />} {page === "voices" && <Voices />}{" "}
          {page === "products" && <Products />}{" "}
          {page === "rooms" && (
            <Rooms
              onConsole={(id) => {
                setRoom(id);
                setSessionId(null);
                setPage("console");
              }}
            />
          )}{" "}
          {page === "console" && (
            <LiveConsole
              roomId={roomId}
              sessionId={sessionId}
              onSession={setSessionId}
            />
          )}
        </m.div>
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
          <Shell />
        </MotionConfig>
      </LazyMotion>
    </QueryClientProvider>
  );
}
