# Ruth AI VAS Portal - Minimal Frontend

A minimal frontend portal for viewing live video feeds from VAS-MS-V2 devices via WebRTC.

## Quick Start

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

## Features

1. **Device Listing** - Left panel shows all devices from VAS
2. **Live Video Feed** - Right panel shows WebRTC video stream from selected device

## How It Works

### Device Listing

The device list calls `GET /api/v1/devices` to fetch all registered cameras from VAS. Each device shows:
- Device name
- Device ID (truncated)
- Location (if available)
- Status (Active/Inactive)

Click a device to view its live feed.

### WebRTC Stream Attachment

When a device is selected, the following sequence executes:

1. **Start Stream**: `POST /api/v1/devices/{device_id}/start-stream`
   - Returns `v2_stream_id` and `producers.video` (producer ID)
   - Handles `reconnect: true` if stream already running

2. **Wait for LIVE**: Polls `GET /v2/streams/{stream_id}` until state is `live`

3. **Get Router Capabilities**: `GET /v2/streams/{stream_id}/router-capabilities`
   - Returns RTP capabilities for mediasoup-client Device initialization

4. **Initialize mediasoup Device**: `device.load({ routerRtpCapabilities })`

5. **Attach Consumer**: `POST /v2/streams/{stream_id}/consume`
   - Sends client ID and RTP capabilities
   - Returns transport info (ICE, DTLS) and consumer ID

6. **Create RecvTransport**: Uses transport info from consume response

7. **DTLS Connect**: On transport `connect` event, calls:
   `POST /v2/streams/{stream_id}/consumers/{consumer_id}/connect`

8. **Consume Video**: `transport.consume()` with producer ID and RTP parameters

9. **Attach to Video Element**: Creates MediaStream from consumer track

### Switching Devices

When a new device is selected:
1. Previous consumer is closed locally
2. Previous consumer is detached from server via `DELETE /v2/streams/{stream_id}/consumers/{consumer_id}`
3. New connection sequence starts

## Configuration

The VAS backend URL is configured in `vite.config.ts`:

```typescript
const VAS_BASE_URL = 'http://10.30.250.245:8085'
```

API proxy routes `/api/*` and `/v2/*` to this backend.

## Authentication

The portal uses hardcoded credentials for simplicity:
- Client ID: `vas-portal`
- Client Secret: `vas-portal-secret-2024`

Tokens are automatically obtained and refreshed via `POST /v2/auth/token`.

## Error Handling

- Failed connections retry once after 2 seconds
- Console logs all WebRTC state transitions
- UI shows connection state and error messages

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── DeviceList.tsx     # Device listing component
│   │   ├── DeviceList.css
│   │   ├── VideoPlayer.tsx    # WebRTC video player
│   │   └── VideoPlayer.css
│   ├── services/
│   │   ├── api.ts             # VAS API client
│   │   └── webrtc.ts          # WebRTC/mediasoup connection logic
│   ├── types/
│   │   └── index.ts           # TypeScript type definitions
│   ├── App.tsx                # Main app component
│   ├── App.css
│   ├── index.css
│   └── main.tsx
├── vite.config.ts             # Vite config with API proxy
└── package.json
```

## Assumptions

1. VAS backend is running at `http://10.30.250.245:8085`
2. Valid API credentials exist (`vas-portal` / `vas-portal-secret-2024`)
3. At least one device is registered in VAS
4. Browser supports WebRTC (modern Chrome, Firefox, Safari, Edge)
5. Network allows UDP traffic for WebRTC media

## Limitations

- No persistent authentication (tokens are session-only)
- No stream stopping (streams continue running on server)
- No audio support (video only)
- No HLS fallback
- Minimal error recovery
