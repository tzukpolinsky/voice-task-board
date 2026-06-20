import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
// Self-hosted fonts (bundled by Vite as local woff2) so the WebView makes no
// outbound CDN request — see the CSP in index.html. Weights match the former
// Google Fonts <link>: Inter 400/500/600/700, Space Grotesk 500/600/700.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
