# ResQLink — Cloudflare demo deployment

This branch deploys the existing FastAPI backend inside a Cloudflare Container and exposes it through a Cloudflare Worker. The existing Groq integration, SQLite repositories, API routes, and SACHET background collector remain in the Python app; this deployment does not replace Groq with Gemini.

## Cloudflare requirements

- A Cloudflare account with the **Workers Paid** plan. Cloudflare Containers are not available on the Free plan.
- Docker Desktop installed and running on the deployment computer.
- Node.js installed.
- A Groq API key for AI classification. Without it, the local multilingual classifier still works, but the Groq AI feature is unavailable.

## 1. Get this branch

From a terminal:

```powershell
git clone https://github.com/DkNabeel/Resqlink-emergency-response.git
cd Resqlink-emergency-response
git switch cloudflare-demo
```

If you already cloned the repository:

```powershell
git fetch origin
git switch cloudflare-demo
```

## 2. Install and connect Wrangler

Make sure Docker Desktop is running, then from the repository root:

```powershell
npm install
npx wrangler login
```

Complete the browser login using the Cloudflare account that has the Workers Paid plan enabled.

## 3. Add secrets

Add the Groq key. Wrangler will prompt you to paste it:

```powershell
npx wrangler secret put GROQ_API_KEY
```

Optional secrets:

```powershell
npx wrangler secret put OPENROUTESERVICE_API_KEY
npx wrangler secret put FACILITY_ADMIN_TOKEN
```

Only add the optional keys when those features are needed. Never put secrets in the mobile app or commit them to GitHub.

## 4. Deploy

From the repository root, with Docker Desktop still running:

```powershell
npx wrangler deploy
```

Wrangler builds the Docker image, uploads it to Cloudflare, and deploys the Worker. The first container deployment can take several minutes while Cloudflare provisions the service.

Wrangler prints the public URL. It will look like:

`https://resqlink-cloudflare-demo.<your-workers-subdomain>.workers.dev`

## 5. Test the API before opening the mobile app

Open these URLs in a browser, replacing the example host with the URL printed by Wrangler:

- `https://YOUR-WORKER.workers.dev/health`
- `https://YOUR-WORKER.workers.dev/system/status`
- `https://YOUR-WORKER.workers.dev/docs`

The health endpoint should return JSON with an `ok` status. In `/system/status`, confirm the AI provider is Groq and that the API is connected.

## 6. Connect Expo Go to the Cloudflare API

In the `mobile` folder, create a local file named `.env` (do not commit it) and put the public Worker URL in it:

```env
EXPO_PUBLIC_API_BASE_URL=https://YOUR-WORKER.workers.dev
```

Then run:

```powershell
cd mobile
npm install
npx expo start --tunnel
```

Scan the QR code in Expo Go. The tunnel is only for loading the development app onto the phone; all backend API calls go to the public Cloudflare URL.

After changing `.env`, restart Expo so it reloads the public URL.

## Demo limitations

This branch is intended for a college demonstration and end-to-end testing, not production emergency use. The existing SQLite file is included in the container image so the backend can start without a database migration. Changes written to the container's local SQLite file can be lost if Cloudflare replaces the container instance. The alert collector starts with the FastAPI app and refreshes while the container is running; it is not a guaranteed always-on alert service. The container is configured to stop after 30 minutes without requests and starts again on the next request.

Do not rely on this student prototype for real emergency dispatch or life-safety decisions. Call India's emergency number 112 when needed.
