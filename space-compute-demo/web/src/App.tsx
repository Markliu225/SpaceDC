import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { SatelliteTwinPage } from './pages/SatelliteTwinPage';
import { InteriorPage } from './pages/InteriorPage';
import { TaskExecutionPage } from './pages/TaskExecutionPage';
import { ControlComparePage } from './pages/ControlComparePage';
import './App.css';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="satellite" element={<SatelliteTwinPage />} />
          <Route path="interior" element={<InteriorPage />} />
          <Route path="task" element={<TaskExecutionPage />} />
          <Route path="control" element={<ControlComparePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
