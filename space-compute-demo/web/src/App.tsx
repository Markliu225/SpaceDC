import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { SatelliteTwinPage } from './pages/SatelliteTwinPage';
import './App.css';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="satellite" element={<SatelliteTwinPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
