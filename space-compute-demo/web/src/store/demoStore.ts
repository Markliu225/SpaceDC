import { create } from 'zustand';
import type {
  ClientMessageType, Envelope, Mode, Parameters,
  SatelliteConfig, StatePacket, TaskState,
} from '../types/messages';

const WS_URL = import.meta.env.VITE_BACKEND_WS ?? 'ws://localhost:8001/ws/state';

interface DemoStore {
  // connection
  ws: WebSocket | null;
  connected: boolean;

  // state
  lastState: StatePacket | null;
  task: TaskState | null;
  selectedPrim: string | null;
  parameters: Parameters;
  mode: Mode;
  cameraPreset: string;
  eventLog: string[];

  // actions
  connect: () => void;
  send: (type: ClientMessageType, payload?: Record<string, unknown>) => void;
  play: () => void;
  pause: () => void;
  reset: () => void;
  setMode: (m: Mode) => void;
  setParameters: (p: Parameters) => void;
  startTask: (caseId?: string) => void;
  selectObject: (primPath: string) => void;
  changeCamera: (preset: string) => void;
  sendSetConfig: (patch: Partial<SatelliteConfig>) => void;
  startMission: () => void;
  stopMission: () => void;
}

export const useDemoStore = create<DemoStore>((set, get) => ({
  ws: null,
  connected: false,
  lastState: null,
  task: null,
  selectedPrim: null,
  parameters: {},
  mode: 'on_orbit',
  cameraPreset: 'overview',
  eventLog: [],

  connect: () => {
    if (get().ws) return;
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => set({ connected: true });
    ws.onclose = () => {
      set({ connected: false, ws: null });
      setTimeout(() => get().connect(), 2000);
    };
    ws.onerror = () => {
      /* handled by onclose */
    };
    ws.onmessage = (ev) => {
      let env: Envelope;
      try { env = JSON.parse(ev.data); } catch { return; }
      switch (env.type) {
        case 'state_update': {
          set({ lastState: env.payload as unknown as StatePacket });
          break;
        }
        case 'task_update': {
          const p = env.payload as { task: TaskState };
          set((s) => ({ task: p.task, eventLog: [...s.eventLog.slice(-49), `task ${p.task.state}`] }));
          break;
        }
        case 'selection_changed': {
          const p = env.payload as { prim_path: string };
          set({ selectedPrim: p.prim_path });
          break;
        }
        case 'camera_changed': {
          const p = env.payload as { preset: string };
          set({ cameraPreset: p.preset });
          break;
        }
        case 'error': {
          const p = env.payload as { code: string; message: string };
          set((s) => ({ eventLog: [...s.eventLog.slice(-49), `err ${p.code}: ${p.message}`] }));
          break;
        }
        default:
          break;
      }
    };
    set({ ws });
  },

  send: (type, payload = {}) => {
    const ws = get().ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const env: Envelope = {
      type,
      ts: Date.now() / 1000,
      payload: payload as Record<string, never>,
      request_id: crypto.randomUUID(),
    };
    ws.send(JSON.stringify(env));
  },

  play: () => get().send('play'),
  pause: () => get().send('pause'),
  reset: () => get().send('reset'),
  setMode: (m) => { set({ mode: m }); get().send('set_mode', { mode: m }); },
  setParameters: (p) => {
    set((s) => ({ parameters: { ...s.parameters, ...p } }));
    get().send('set_parameters', p as Record<string, unknown>);
  },
  startTask: (caseId = 'maritime_case_01') => get().send('start_task', { case_id: caseId }),
  selectObject: (primPath) => {
    set({ selectedPrim: primPath });
    get().send('select_object', { prim_path: primPath });
  },
  changeCamera: (preset) => {
    set({ cameraPreset: preset });
    get().send('change_camera', { preset });
  },
  sendSetConfig: (patch) => {
    // Optimistic local state lives in useTelemetryStore.satConfig; this
    // method just fires the wire command. Backend echoes via state_update.
    get().send('set_config', patch as Record<string, unknown>);
  },
  startMission: () => get().send('start_mission'),
  stopMission: () => get().send('stop_mission'),
}));

// Dev-only handle so a prim selection can be driven without the Kit stream
// (used by the layout/popup screenshot checks). No-op in production builds.
if (import.meta.env.DEV) {
  ;(window as unknown as { __demoStore?: typeof useDemoStore }).__demoStore = useDemoStore
}
