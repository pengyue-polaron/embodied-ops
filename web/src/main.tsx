import React from "react"
import ReactDOM from "react-dom/client"
import "@fontsource-variable/ibm-plex-sans"
import "@fontsource-variable/jetbrains-mono"
import "./index.css"

import { App } from "./App"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
