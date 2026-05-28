This folder contains a minimal Next.js frontend converted from the existing Jinja templates.

Quick start (development):

1. cd frontend
2. npm install
3. npm run dev

Build & static export (for Netlify):

1. cd frontend
2. npm ci
3. npm run build

For production the build already points to the Render backend via `NEXT_PUBLIC_API_BASE=https://immo-web.onrender.com`.
If you use another backend URL, override that environment variable in Netlify.
