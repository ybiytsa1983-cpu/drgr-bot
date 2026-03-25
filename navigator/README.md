# 🧭 DRGRNav — Android Navigator

A complete **Progressive Web App (PWA)** navigator that works **online and offline** on Android.

## Features

| Feature | Details |
|---------|---------|
| 🗺 Online maps | OpenStreetMap tiles via Leaflet |
| 🌑 Dark map | CartoDB dark basemap option |
| 📍 GPS tracking | High-accuracy `watchPosition`, accuracy circle |
| 🔍 Address search | Nominatim geocoding with autocomplete |
| 🛣 Turn-by-turn routing | OSRM open-source routing engine |
| 🚗🚲🚶 Transport modes | Car / Bike / Walk OSRM profiles |
| 📴 Offline tiles | Service Worker caches up to 2000 map tiles |
| 💾 Saved routes | IndexedDB persistence — routes survive app restarts |
| 📌 Long-press | Touch-hold on map to set destination + reverse geocode |
| 📱 Install on Android | Web App Manifest — "Add to Home Screen" in Chrome |

## How to run

### Option A — Use with the Code VM (recommended)

```bash
python vm/server.py
```

Then open `http://localhost:5000/navigator/` in Chrome on your phone/emulator.

### Option B — Standalone

Serve from any static file server:

```bash
python -m http.server 8080 --directory navigator/
# → open http://YOUR_IP:8080/ in Chrome on Android
```

To install as an app on Android:
1. Open in Chrome
2. Tap ⋮ → **"Add to Home Screen"**
3. The app installs with full-screen mode and offline support

## Android setup

- Enable **GPS / Location** permission for Chrome
- Grant **background location** for continuous navigation
- Use **Chrome 88+** for full PWA + Service Worker support

## Offline behaviour

The Service Worker (`sw.js`) caches:
- **App shell** (HTML) — always available offline
- **Map tiles** — up to 2000 tiles cached, stale-while-revalidate
- **Routes** — last 200 routes cached, served on reconnect

When offline:
- Previously visited map areas are visible
- Cached routes can be replayed
- GPS still works (device hardware)
- New routing requests show "Офлайн" message
