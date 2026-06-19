# Fuel Route Planner — Frontend

React + Vite + react-leaflet map UI for the Django fuel-route API.
Dark "dispatch-console" theme; renders the route polyline, fuel-stop markers,
and a cost summary.

## Run

The backend must be running first (`http://127.0.0.1:8000`):

```bash
# terminal 1 — backend
cd ../backend && source .venv/bin/activate && python manage.py runserver

# terminal 2 — frontend
npm install
npm run dev          # http://localhost:5173
```

Vite proxies `/api/*` to the Django backend (see `vite.config.js`), so there is
no CORS configuration to manage in development.

## Build for production

```bash
npm run build        # outputs static assets to dist/
npm run preview      # serve the production build locally
```

For a single-origin deploy, serve `dist/` from any static host (or Django's
`staticfiles`) and point it at the API base URL.

## Stack

| Package | Why |
|---|---|
| `react` / `react-dom` 18 | UI |
| `react-leaflet` 4 + `leaflet` 1.9 | Map rendering |
| `vite` 5 + `@vitejs/plugin-react` | Dev server, proxy, build |

Fonts (Google Fonts, loaded in `index.html`): Bricolage Grotesque (display),
JetBrains Mono (data), Archivo (body).
