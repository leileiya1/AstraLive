import { create } from 'zustand'
type Ui = { sidebarOpen:boolean;selectedRoomId:string|null;consolePanelOpen:boolean;muted:boolean;setSidebarOpen:(v:boolean)=>void;setSelectedRoomId:(v:string|null)=>void;setConsolePanelOpen:(v:boolean)=>void;setMuted:(v:boolean)=>void }
export const useUi = create<Ui>((set)=>({sidebarOpen:true,selectedRoomId:null,consolePanelOpen:true,muted:false,setSidebarOpen:(sidebarOpen)=>set({sidebarOpen}),setSelectedRoomId:(selectedRoomId)=>set({selectedRoomId}),setConsolePanelOpen:(consolePanelOpen)=>set({consolePanelOpen}),setMuted:(muted)=>set({muted})}))
