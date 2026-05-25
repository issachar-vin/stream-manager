# Privacy Policy

**Last updated:** May 2026

StreamManager is a free, open-source desktop application that helps you go live on YouTube and Facebook simultaneously via OBS.

## What data is collected

StreamManager does not collect, transmit, or store any user data on external servers. There are no analytics, tracking, or third-party data collection of any kind.

## What is stored locally

The following is stored on your machine only, in `~/Library/Application Support/StreamManager/`:

- OBS WebSocket connection details (host, port, password)
- YouTube OAuth credentials and session token
- Facebook OAuth credentials and session token
- Your last-used Facebook Page selection

This data never leaves your machine except as part of direct API calls to Google and Meta on your behalf (see below).

## Third-party API calls

When you use StreamManager, it communicates directly with:

- **YouTube Data API v3** (Google) — to create live broadcasts on your YouTube account
- **Facebook Graph API** (Meta) — to create live videos on your Facebook Page

These calls are made using your own developer credentials and OAuth tokens. StreamManager acts on your behalf — it does not proxy, log, or intercept the data exchanged. Google and Meta's own privacy policies govern how they handle that data.

## Data deletion

To remove all locally stored data, delete the folder:

```
~/Library/Application Support/StreamManager/
```

## Contact

This is a personal open-source project. For questions or concerns open an issue on GitHub.
