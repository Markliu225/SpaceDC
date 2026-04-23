import { useEffect } from 'react';
import { SceneEmbed } from '../components/SceneEmbed';
import { StatusCardGrid } from '../components/StatusCardGrid';
import { useDemoStore } from '../store/demoStore';

export function SatelliteTwinPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera);
  const connected = useDemoStore((s) => s.connected);
  useEffect(() => {
    if (connected) changeCamera('satellite');
  }, [connected, changeCamera]);

  return (
    <div className="page page--satellite">
      <div className="page__toolbar">
        <span>VIEW MODE</span>
        <button disabled>Structure</button>
        <button disabled>Power</button>
        <button disabled>Thermal</button>
        <button disabled>Compute</button>
        <em className="page__note">(view-mode wiring lands in Phase 2)</em>
      </div>
      <div className="page__scene"><SceneEmbed cameraPreset="satellite" /></div>
      <div className="page__side"><StatusCardGrid /></div>
    </div>
  );
}
