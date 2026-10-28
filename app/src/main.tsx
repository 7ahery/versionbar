import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "@/App";
import { PRODUCT_NAME } from "@/product";
import "@/index.css";

document.title = PRODUCT_NAME;

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing #root");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
