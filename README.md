# StreamManager

Go live on YouTube and Facebook simultaneously from a single click. StreamManager creates the broadcast on each platform with your title and description, pushes the stream keys to OBS, and starts streaming — no manual setup on each platform required.

---

## How it works

1. Enter your OBS connection details in Settings (once)
2. Paste your Google and Facebook developer credentials in Settings (once)
3. Click "Authorize YouTube" and "Login with Facebook" — browser handles the rest
4. On the Stream tab: pick your Facebook Page, enter a title and description, click **Go Live**

When streaming to both platforms, StreamManager starts a local ffmpeg RTMP relay. OBS streams once to the relay, which fans the single stream out to YouTube and Facebook simultaneously. No OBS plugins required.

All credentials and auth tokens are saved to `~/Library/Application Support/StreamManager/config.json` so nothing needs to be re-entered between sessions. Stream title, description, platform selection, and privacy setting are also remembered between sessions.

---

## How long does auth last?

| Platform | Token lifetime | Re-auth needed |
|---|---|---|
| YouTube | Indefinite — refresh tokens never expire and are renewed silently | Only if you revoke access in your Google account |
| Facebook | ~60 days — short-lived tokens are automatically exchanged for long-lived ones | Once every ~2 months; the app shows days remaining |

---

## Requirements

- macOS (M1/M2 or Intel)
- [OBS Studio](https://obsproject.com) 28 or later
- ffmpeg — required for streaming to both platforms simultaneously (installed automatically by the setup script below)
- A Google account with YouTube enabled
- A Facebook Page you manage

---

## Setup

There are two ways to run StreamManager: as a pre-built app (no Python needed) or from source.

### Option A — Pre-built app (recommended for most users)

1. Download `StreamManager-macOS-arm64.zip` from the [latest release](https://github.com/your-username/StreamManager/releases)
2. Unzip and move `StreamManager.app` to your Applications folder
3. Right-click → **Open** the first time to bypass the Gatekeeper warning (the app is not code-signed)
4. Install dependencies by running this command in Terminal:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/issachar-vin/stream-manager/main/scripts/install-deps.sh)"
   ```
   This installs Homebrew (if missing) and ffmpeg. The Xcode Command Line Tools are the only prerequisite — macOS will prompt you to install them if needed.
5. Launch the app and follow the Settings tab to connect your accounts

### Option B — Run from source

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/your-username/StreamManager.git
cd StreamManager
make setup
make run
```

---

## Settings

All configuration is done inside the app's **Settings tab**. Nothing needs to be set in a config file manually.

### OBS WebSocket

StreamManager controls OBS via its built-in WebSocket server.

**Enable it in OBS:**
1. Open OBS → **Tools** → **WebSocket Server Settings**
2. Check **Enable WebSocket server**
3. Set a password and note the port (default: `4455`)

Enter the host, port, and password in the Settings tab and click **Save OBS Settings**.

---

### YouTube

StreamManager uses the YouTube Data API v3 with OAuth 2.0. You need to create a Google Cloud project once to get a Client ID and Secret.

**Get your Client ID and Secret:**

1. Go to the [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services** → **Library** and enable **YouTube Data API v3**
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Choose **Desktop app** as the application type
6. Copy the **Client ID** and **Client Secret** shown
7. Go to **APIs & Services** → **OAuth consent screen** and add your Google account as a test user

Paste the Client ID and Secret into the Settings tab and click **Authorize YouTube**. A browser window will open for you to log in. After that, the token is saved and YouTube will never ask again (it renews automatically in the background).

---

### Facebook

StreamManager uses the Facebook Graph API with OAuth 2.0. You need to create a Meta developer app once.

**Get your App ID and Secret:**

1. Go to [Meta for Developers](https://developers.facebook.com) and click **Create App**
2. Choose **Business** as the app type
3. From your app dashboard, copy the **App ID** and **App Secret** (under Settings → Basic)
4. Add the **Facebook Login** product to your app
5. Under Facebook Login → Settings, add `http://localhost:8765` to **Valid OAuth Redirect URIs**
6. Add your Facebook account as a test user under **Roles → Test Users** (until the app is approved for public use)

Paste the App ID and Secret into the Settings tab and click **Login with Facebook**. A browser window will open to authorize access. The app exchanges the token for a long-lived one (~60 days) and saves it. The Settings tab shows how many days remain.

**Selecting a Page:** After logging in, the Stream tab's Page dropdown will populate with all Pages you manage. Your last-used Page is remembered automatically.

---

## Makefile Reference

| Command | Description |
|---|---|
| `make deps` | Install ffmpeg and Homebrew (if missing) |
| `make setup` | Create venv, install deps, install pre-commit |
| `make run` | Start the app |
| `make lint` | Run ruff formatter, linter, and mypy |
| `make build` | Build `dist/StreamManager.app` via PyInstaller |
| `make bump-patch` | Bump patch version in VERSION file (1.0.0 → 1.0.1) |
| `make bump-minor` | Bump minor version in VERSION file (1.0.0 → 1.1.0) |
| `make bump-major` | Bump major version in VERSION file (1.0.0 → 2.0.0) |
| `make clean` | Remove build artifacts and virtual environment |

---

## Building a Standalone App

```bash
make build
```

The output is `dist/StreamManager.app`. No Python required to run it.

> **Note:** The app is not code-signed. macOS will show an "unidentified developer" warning on first launch. Right-click → **Open** to bypass it once.

### Automated builds via GitHub Actions

Every merge to `main` triggers a build and publishes a GitHub Release using the version in the `VERSION` file. To cut a new release, bump the version in your PR:

```bash
make bump-patch   # 1.0.0 → 1.0.1
make bump-minor   # 1.0.0 → 1.1.0
make bump-major   # 1.0.0 → 2.0.0
```

---

## Where data is stored

All app data lives in `~/Library/Application Support/StreamManager/`:

| File | Contents |
|---|---|
| `config.json` | OBS settings, Facebook/YouTube credentials, last-used Page, auth tokens |
| `youtube_token.json` | YouTube OAuth session (auto-managed) |

---

## Project Structure

```
src/streammanager/
├── main.py                    # entry point
├── app.py                     # orchestrator
├── config/
│   └── config_manager.py      # persistent JSON config
├── models/stream.py           # StreamConfig dataclass
├── services/
│   ├── interfaces.py          # Protocol definitions
│   ├── obs.py                 # OBS WebSocket service
│   ├── rtmp_relay.py          # ffmpeg RTMP relay for dual-platform streaming
│   ├── youtube.py             # YouTube API + OAuth
│   └── facebook.py            # Facebook API + OAuth
└── ui/main_window.py          # tkinter UI (Stream + Settings tabs)
```
