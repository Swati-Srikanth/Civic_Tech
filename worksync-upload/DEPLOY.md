# Deploying WorkSync to one public link

The backend serves the built website **and** the API, so the whole app is one address (for example
`https://worksync.onrender.com`). Judges open the link; nothing needs installing.

## What you need
- A GitHub account (the repository), and a [Render](https://render.com) account (hosting).
- About 15 minutes.

## Steps
1. **Put the project on GitHub.** In this folder:
   ```bash
   git init && git add . && git commit -m "WorkSync"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   `.gitignore` already keeps out `.venv`, `node_modules`, `.tools` and the local database.
2. **Create the service on Render.** *New → Blueprint*, choose the repository. Render reads `render.yaml`
   (a Docker web service with a 1 GB disk for the database). It asks for two values:
   - `WORKSYNC_STAFF_PASSWORD`: the one password every staff account will use on this site. Choose a strong one
     (at least 8 characters, letters and numbers or symbols) and put it in the README you give to judges.
   - `WORKSYNC_GOOGLE_CLIENT_ID`: leave empty unless you set up Google sign-in (guests and local accounts need nothing).
3. **Wait for the first deploy** (a few minutes). Open the address Render shows. The first start loads the invented
   sample works and complaints around Chennai (`WORKSYNC_DEMO_SCENARIO`), so the home page is not empty.
4. **Check it**: search "Anna Nagar Chennai", open a road, report a problem, track it, sign in as `admin`
   (or any name in `backend/DEMO_CREDENTIALS.md`) with the password you chose.

### Free plan instead of a disk
Render's free plan has no disk and sleeps when idle. Delete the `disk:` block in `render.yaml` and set `plan: free`.
The sample data is then reloaded on every start, but anything judges enter is lost on a restart, and the first
visit after a sleep takes about a minute. For a judged demo, the paid plan with a disk is the stable choice.

## Settings (environment variables)
| Variable | Meaning |
|---|---|
| `WORKSYNC_DB` | Where the database file lives (`/data/worksync.db`, on the disk) |
| `WORKSYNC_BEHIND_PROXY=1` | The host's proxy is in front: use the address it added for throttling, and keep the demo clock closed |
| `WORKSYNC_DEMO_SCENARIO="LAT,LNG"` | Load the sample works and complaints around this point on the first start only |
| `WORKSYNC_STAFF_PASSWORD` | One password for every seeded staff account (replaces the published demo passwords) |
| `WORKSYNC_GOOGLE_CLIENT_ID` | Turns on Google sign-in (also add the site address in Google's console) |
| `WORKSYNC_ALLOW_REMOTE_CLOCK=1` | Lets signed-in staff advance the simulated clock on the public site. Off by default: the clock is shared and only moves forward, so one visitor would change it for everyone |
| `WORKSYNC_STATIC_DIR` | Folder of the built website (set by the Dockerfile) |

## Running the same thing locally
```bash
cd frontend && VITE_API_BASE_URL="" npm run build && cd ..
cd backend && .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000     # website + API at http://localhost:8000
```
Or with Docker: `docker build -t worksync . && docker run -p 8000:8000 worksync`.

## What was and was not checked
- Checked: the production build served by the backend at one address (home, a deep link such as `/report`, the API,
  sign-in, sample data on first start), the staff-password setting, the closed clock behind a proxy, path-traversal
  probes, and 140 backend tests.
- **Not checked: the Docker image and the Render deployment itself** (Docker is not installed on the machine this was
  built on, and no hosting account was used). The first deploy may need small fixes; the build logs will say what.
- This is a demonstrator: shared staff password, no e-mail, no password reset, one SQLite file. See the README's limits.
