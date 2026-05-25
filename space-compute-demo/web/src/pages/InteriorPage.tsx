import { useEffect } from 'react';
import { SceneEmbed } from '../components/SceneEmbed';
import { useDemoStore } from '../store/demoStore';

export function InteriorPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera);
  const connected = useDemoStore((s) => s.connected);
  useEffect(() => {
    if (connected) changeCamera('interior');
  }, [connected, changeCamera]);

  return (
    <div className="page page--satellite">
      <div className="page__toolbar">
        <span>INTERIOR</span>
        <em className="page__note">data-hall corridor</em>
      </div>
      <div className="page__scene"><SceneEmbed cameraPreset="interior" /></div>
    </div>
  );
}
