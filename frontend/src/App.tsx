import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CardioidBackdrop } from "./components/CardioidBackdrop";
import { AdminLogin } from "./pages/AdminLogin";
import { PublicLookup } from "./pages/PublicLookup";
import { StudioShell } from "./pages/StudioShell";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <CardioidBackdrop />
      <div className="app-foreground">
        <Routes>
          <Route path="/" element={<PublicLookup />} />
          <Route path="/login" element={<AdminLogin />} />
          <Route path="/studio" element={<StudioShell />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
};

export default App;
