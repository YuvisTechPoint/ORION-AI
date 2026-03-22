import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

const ORION_API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
window.__ORION_API_BASE__ = ORION_API_BASE;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
