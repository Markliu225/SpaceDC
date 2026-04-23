/**
 * SceneEmbed — a positioning slot for the globally-mounted WebRTC stream.
 *
 * The actual <video> element lives in <StreamMount /> rendered at app root
 * so it survives route changes. This component merely reserves space and
 * advertises its DOMRect via the id `scene-embed-slot` which StreamMount
 * uses to overlay the stream.
 */
import { useEffect, useState } from 'react';
import { useDemoStore } from '../store/demoStore';
import { getStreamStatus, getStreamMessage, subscribeStreamStatus } from './StreamMount';
import StreamConfig from '../../stream.config.json';

interface Props {
  cameraPreset?: string;
}

export function SceneEmbed({ cameraPreset }: Props) {
  const fallbackPreset = useDemoStore((s) => s.cameraPreset);
  const preset = cameraPreset ?? fallbackPreset;

  const [, setTick] = useState(0);
  useEffect(() => subscribeStreamStatus(() => setTick((t) => t + 1)), []);

  const status = getStreamStatus();
  const msg = getStreamMessage();

  return (
    <div id="scene-embed-slot" className="scene-embed">
      {status !== 'ready' && (
        <div className="scene-embed__placeholder">
          <div className="scene-embed__title">3D VIEWPORT</div>
          <div className="scene-embed__meta">
            <span>stream: {status}</span>
            <span>camera: {preset}</span>
          </div>
          {status === 'failed' && <div className="scene-embed__hint">Kit not reachable<br />{msg}</div>}
          {status === 'connecting' && <div className="scene-embed__hint">connecting to {StreamConfig.local.server}:{StreamConfig.local.signalingPort}...</div>}
        </div>
      )}
    </div>
  );
}
