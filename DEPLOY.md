# Deployment

Two-service setup: frontend on Vercel, backend on Render.

## Backend (Render)

1. Push the repo to GitHub (already done if you cloned this)
2. Go to https://dashboard.render.com → New → Blueprint
3. Connect the repo, select `backend/render.yaml`
4. Render will pick up the service config automatically
5. Set environment variables in the Render dashboard (the `sync: false` ones in render.yaml):
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY` (optional)
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` (set to your Render URL + `/auth/callback`)
   - `FRONTEND_URL` (set to your Vercel URL)
6. Deploy. You'll get a URL like `https://calendar-agent-backend.onrender.com`
7. Add that URL + `/auth/callback` as an authorized redirect URI in your Google Cloud OAuth client

## Frontend (Vercel)

1. https://vercel.com/new → import the same repo
2. Set **Root Directory** to `frontend`
3. Framework auto-detects as Next.js
4. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = your Render backend URL (no trailing slash)
5. Deploy. You'll get a URL like `https://calendar-agent.vercel.app`
6. Update the backend's `FRONTEND_URL` env var on Render to match
7. Add the Vercel URL to your Google Cloud OAuth consent screen as an authorized domain

## Quick reference for env vars

| Env var | Where | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | Render | Your Anthropic key |
| `OPENAI_API_KEY` | Render | Your OpenAI key (optional) |
| `GOOGLE_CLIENT_ID` | Render | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Render | From Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | Render | `https://<your-backend>.onrender.com/auth/callback` |
| `FRONTEND_URL` | Render | `https://<your-frontend>.vercel.app` |
| `NEXT_PUBLIC_API_URL` | Vercel | `https://<your-backend>.onrender.com` |

## Cold starts

Render's free tier sleeps after 15 min of inactivity. First request after sleep takes ~30 sec to wake. Acceptable for demo purposes.
