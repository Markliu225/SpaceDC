/**
 * StreamMount — renders the WebRTC <video>+<audio> elements ONCE at app root.
 *
 * Each page's <SceneEmbed> is a positioning slot; an effect below observes
 * the slot's DOMRect and absolutely-positions the shared <video> on top of it.
 * This survives React route changes (which would otherwise unmount/remount the
 * video element and kill the attached MediaStream track).
 */
import { useEffect, useRef, useState } from 'react';
import { AppStreamer, StreamType } from '@nvidia/omniverse-webrtc-streaming-library';
import type { StreamEvent } from '@nvidia/omniverse-webrtc-streaming-library';
import StreamConfig from '../../stream.config.json';

type Status = 'idle' | 'connecting' | 'ready' | 'failed';

let connectRequested = false;

export interface SharedStreamState {
  status: Status;
  message: string;
  subscribe: (fn: () => void) => () => void;
}

// Module-level state so multiple consumers see the same status.
const state: { status: Status; message: string } = { status: 'idle', message: '' };
const listeners = new Set<() => void>();

function notify() { listeners.forEach((fn) => fn()); }
function setState(s: Status, m = '') { state.status = s; state.message = m; notify(); }

export function getStreamStatus(): Status { return state.status; }
export function getStreamMessage(): string { return state.message; }
export function subscribeStreamStatus(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

function connectOnce() {
  if (connectRequested) return;
  connectRequested = true;
  setState('connecting');

  if (StreamConfig.source !== 'local') {
    setState('failed', 'stream.config.json source must be "local"');
    return;
  }

  AppStreamer.connect({
    streamSource: StreamType.DIRECT,
    streamConfig: {
      videoElementId: 'remote-video',
      audioElementId: 'remote-audio',
      authenticate: true,
      maxReconnects: 5,
      signalingServer: StreamConfig.local.server,
      signalingPort: StreamConfig.local.signalingPort,
      mediaServer: StreamConfig.local.server,
      ...(StreamConfig.local.mediaPort != null && { mediaPort: StreamConfig.local.mediaPort }),
      nativeTouchEvents: true,
      width: 1280, height: 720, fps: 30,
      onStart: (e: StreamEvent) => {
        if (e.action === 'start' && e.status === 'success') setState('ready');
        if (e.status === 'error') setState('failed', String((e as StreamEvent & { info?: string }).info ?? 'stream error'));
      },
      onUpdate: () => {},
      onCustomEvent: () => {},
      onStop: () => setState('idle'),
      onTerminate: () => setState('idle'),
    },
  } as Parameters<typeof AppStreamer.connect>[0]).catch((err: unknown) => {
    setState('failed', err instanceof Error ? err.message : String(err));
  });
}

export function StreamMount() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    connectOnce();
    const unsub = subscribeStreamStatus(() => setTick((t) => t + 1));
    return () => { unsub(); };
  }, []);

  // Poll the slot position so CSS overlays it (cheaper than ResizeObserver for a single div).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let raf = 0;
    const update = () => {
      const slot = document.getElementById('scene-embed-slot');
      if (slot) {
        const r = slot.getBoundingClientRect();
        el.style.left = `${r.left}px`;
        el.style.top = `${r.top}px`;
        el.style.width = `${r.width}px`;
        el.style.height = `${r.height}px`;
        el.style.display = 'block';
      } else {
        el.style.display = 'none';
      }
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed', left: 0, top: 0, width: 0, height: 0,
        // Parent div ignores events (so clicks fall through to page UI outside the scene slot).
        pointerEvents: 'none', zIndex: 5,
      }}
    >
      <video
        id="remote-video"
        style={{
          width: '100%', height: '100%', display: 'block', background: '#000',
          // Video itself accepts pointer events so AppStreamer can forward them to Kit.
          pointerEvents: 'auto',
        }}
        tabIndex={0}
        autoPlay
        playsInline
        muted
      />
      <audio id="remote-audio" muted style={{ display: 'none' }} />
    </div>
  );
}
