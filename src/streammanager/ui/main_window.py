import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from ..app import StreamManagerApp
from ..models.stream import StreamConfig, StreamStatus
from ..services.facebook import PERSONAL_PROFILE, FacebookPage


def _asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent.parent.parent))
    return base / "assets" / name


class MainWindow:
    _OBS_POLL_INTERVAL_MS = 5000
    _UI_PUMP_INTERVAL_MS = 50

    def __init__(self, app: StreamManagerApp) -> None:
        self._app = app
        self._is_live = False
        self._pages: list[FacebookPage] = []
        self._stream_status: StreamStatus | None = None
        self._ui_queue: queue.Queue[Callable[[], object]] = queue.Queue()
        self._root = tk.Tk()
        self._build_ui()
        self._load_saved_settings()
        self._root.after(self._UI_PUMP_INTERVAL_MS, self._pump_ui)
        self._schedule_obs_poll()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._root.title("StreamManager")
        self._root.geometry("540x520")
        self._root.minsize(460, 400)
        self._root.resizable(True, True)

        try:
            self._icon = tk.PhotoImage(file=_asset("icon.png"))
            self._root.iconphoto(True, self._icon)
        except Exception:
            pass

        ttk.Style().configure("TNotebook.Tab", padding=[16, 6])

        notebook = ttk.Notebook(self._root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._stream_tab = ttk.Frame(notebook, padding=20)
        self._status_tab = ttk.Frame(notebook, padding=0)
        self._settings_tab = ttk.Frame(notebook, padding=0)
        notebook.add(self._stream_tab, text="Stream")
        notebook.add(self._status_tab, text="Status")
        notebook.add(self._settings_tab, text="Settings")
        self._notebook = notebook

        self._build_stream_tab()
        self._build_status_tab()
        self._build_settings_tab()

    def _make_scrollable_frame(self, parent: ttk.Frame) -> tuple[ttk.Frame, tk.Canvas]:
        """Wrap parent in a Canvas+Scrollbar; return (inner frame, canvas)."""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas, padding=20)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win, width=e.width),
        )

        return inner, canvas

    def _bind_mousewheel(
        self, widget: tk.Widget | tk.Toplevel, canvas: tk.Canvas
    ) -> None:
        """Bind mousewheel/trackpad scrolling on widget and all its descendants."""

        def scroll(event: tk.Event) -> None:
            # macOS trackpad sends small deltas; mouse wheel sends multiples of 120.
            delta = event.delta
            units = int(-1 * (delta / 120)) if abs(delta) >= 120 else int(-1 * delta)
            if units != 0:
                canvas.yview_scroll(units, "units")

        widget.bind("<MouseWheel>", scroll)
        for child in widget.winfo_children():
            self._bind_mousewheel(child, canvas)

    def _make_meta_text(self, parent: ttk.Frame, height: int = 3) -> tk.Text:
        """Read-only selectable text widget styled to look like a label."""
        return tk.Text(
            parent,
            height=height,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            state="disabled",
            cursor="arrow",
            padx=0,
            pady=2,
            bg="white",
            fg="#222222",
        )

    def _set_meta_text(self, widget: tk.Text, content: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.config(state="disabled")

    def _set_link(self, btn: ttk.Button, url: str | None, text: str) -> None:
        if url and url.startswith("http"):
            btn.config(text=text, command=lambda: webbrowser.open(url))
            btn.grid()
        else:
            btn.grid_remove()

    def _copy_meta(self, widget: tk.Text) -> None:
        content = widget.get("1.0", tk.END).strip()
        self._root.clipboard_clear()
        self._root.clipboard_append(content)

    def _build_stream_tab(self) -> None:
        f = self._stream_tab

        # ── Platform selection ────────────────────────────────────────────
        self._yt_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f,
            text="YouTube",
            variable=self._yt_enabled,
            command=self._on_platform_toggle,
        ).grid(row=0, column=0, sticky=tk.W)

        self._yt_account_label = ttk.Label(f, text="Not authorized", foreground="gray")
        self._yt_account_label.grid(row=0, column=1, sticky=tk.W, padx=(8, 0))

        self._fb_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f,
            text="Facebook",
            variable=self._fb_enabled,
            command=self._on_platform_toggle,
        ).grid(row=1, column=0, sticky=tk.W, pady=(6, 0))

        self._page_var = tk.StringVar()
        self._page_dropdown = ttk.Combobox(
            f, textvariable=self._page_var, state="disabled", width=36
        )
        self._page_dropdown.grid(
            row=1, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 0)
        )
        self._page_dropdown.bind("<<ComboboxSelected>>", self._on_page_selected)

        ttk.Label(f, text="Privacy").grid(row=2, column=0, sticky=tk.W, pady=(4, 0))
        self._fb_privacy_var = tk.StringVar(value="Public")
        privacy_dropdown = ttk.Combobox(
            f,
            textvariable=self._fb_privacy_var,
            values=["Public", "Friends", "Only Me"],
            state="readonly",
            width=12,
        )
        privacy_dropdown.grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(4, 0))

        self._fb_status_var = tk.StringVar(value="Not connected")
        ttk.Label(f, textvariable=self._fb_status_var, foreground="gray").grid(
            row=3, column=1, sticky=tk.W, padx=(8, 0), pady=(2, 0)
        )

        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky=tk.EW, pady=(14, 0)
        )

        # ── Stream title ──────────────────────────────────────────────────
        ttk.Label(f, text="Stream Title").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(12, 4)
        )
        self._title_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._title_var, width=54).grid(
            row=6, column=0, columnspan=2, sticky=tk.EW
        )

        # ── Description ───────────────────────────────────────────────────
        ttk.Label(f, text="Description").grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=(12, 4)
        )
        self._description = tk.Text(f, height=5, width=54)
        self._description.grid(row=8, column=0, columnspan=2, sticky=tk.EW)

        # ── Go Live ───────────────────────────────────────────────────────
        self._live_btn = ttk.Button(
            f, text="Go Live", command=self._toggle_live, width=20, state="disabled"
        )
        self._live_btn.grid(row=9, column=0, columnspan=2, pady=(20, 0))

        self._stream_status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._stream_status_var, foreground="gray").grid(
            row=10, column=0, columnspan=2, pady=(6, 0)
        )

        f.columnconfigure(1, weight=1)

    def _build_status_tab(self) -> None:
        f, _status_canvas = self._make_scrollable_frame(self._status_tab)

        # ── Overall status ────────────────────────────────────────────────
        self._overall_status_var = tk.StringVar(value="Offline")
        ttk.Label(f, textvariable=self._overall_status_var, font=("", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 16)
        )

        # ── YouTube ───────────────────────────────────────────────────────
        ttk.Label(f, text="YouTube", font=("", 11, "bold")).grid(
            row=1, column=0, sticky=tk.W
        )
        self._yt_indicator = tk.Label(f, text="  Offline", foreground="gray")
        self._yt_indicator.grid(row=1, column=1, sticky=tk.E)

        yt_meta_frame = ttk.Frame(f)
        yt_meta_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))
        yt_meta_frame.columnconfigure(0, weight=1)

        self._yt_meta_text = self._make_meta_text(yt_meta_frame)
        self._yt_meta_text.grid(row=0, column=0, sticky=tk.EW)
        self._set_meta_text(self._yt_meta_text, "—")

        ttk.Button(
            yt_meta_frame,
            text="Copy",
            width=6,
            command=lambda: self._copy_meta(self._yt_meta_text),
        ).grid(row=0, column=1, sticky=tk.NE, padx=(6, 0))

        self._yt_link = ttk.Button(yt_meta_frame, text="Watch on YouTube →")
        self._yt_link.grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._yt_link.grid_remove()

        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky=tk.EW, pady=16
        )

        # ── Facebook ──────────────────────────────────────────────────────
        ttk.Label(f, text="Facebook", font=("", 11, "bold")).grid(
            row=4, column=0, sticky=tk.W
        )
        self._fb_indicator = tk.Label(f, text="  Offline", foreground="gray")
        self._fb_indicator.grid(row=4, column=1, sticky=tk.E)

        fb_meta_frame = ttk.Frame(f)
        fb_meta_frame.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))
        fb_meta_frame.columnconfigure(0, weight=1)

        self._fb_meta_text = self._make_meta_text(fb_meta_frame)
        self._fb_meta_text.grid(row=0, column=0, sticky=tk.EW)
        self._set_meta_text(self._fb_meta_text, "—")

        ttk.Button(
            fb_meta_frame,
            text="Copy",
            width=6,
            command=lambda: self._copy_meta(self._fb_meta_text),
        ).grid(row=0, column=1, sticky=tk.NE, padx=(6, 0))

        self._fb_link = ttk.Button(fb_meta_frame, text="Watch on Facebook →")
        self._fb_link.grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._fb_link.grid_remove()

        ttk.Separator(f, orient="horizontal").grid(
            row=6, column=0, columnspan=2, sticky=tk.EW, pady=16
        )

        # ── OBS ───────────────────────────────────────────────────────────
        ttk.Label(f, text="OBS", font=("", 11, "bold")).grid(
            row=7, column=0, sticky=tk.W
        )
        self._obs_indicator = tk.Label(f, text="  Disconnected", foreground="gray")
        self._obs_indicator.grid(row=7, column=1, sticky=tk.E)

        self._stop_btn = ttk.Button(
            f, text="Stop Streaming", command=self._on_stop_streaming, state="disabled"
        )
        self._stop_btn.grid(row=8, column=0, columnspan=2, pady=(24, 0))

        f.columnconfigure(0, weight=1)
        self._bind_mousewheel(f, _status_canvas)

    def _build_settings_tab(self) -> None:
        f, _settings_canvas = self._make_scrollable_frame(self._settings_tab)

        # ── OBS ───────────────────────────────────────────────────────────
        ttk.Label(f, text="OBS WebSocket", font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )

        ttk.Label(f, text="Host").grid(row=1, column=0, sticky=tk.W)
        self._obs_host_var = tk.StringVar(value="localhost")
        ttk.Entry(f, textvariable=self._obs_host_var, width=24).grid(
            row=1, column=1, sticky=tk.EW, padx=(8, 0)
        )

        ttk.Label(f, text="Port").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        self._obs_port_var = tk.StringVar(value="4455")
        ttk.Entry(f, textvariable=self._obs_port_var, width=10).grid(
            row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(6, 0)
        )

        ttk.Label(f, text="Password").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        self._obs_password_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._obs_password_var, show="*", width=24).grid(
            row=3, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 0)
        )

        obs_btn_frame = ttk.Frame(f)
        obs_btn_frame.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Button(
            obs_btn_frame, text="Save OBS Settings", command=self._save_obs
        ).pack(side=tk.LEFT)
        ttk.Button(obs_btn_frame, text="Test Connection", command=self._test_obs).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self._obs_status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._obs_status_var, foreground="gray").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        ttk.Separator(f, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky=tk.EW, pady=16
        )

        # ── YouTube ───────────────────────────────────────────────────────
        ttk.Label(f, text="YouTube", font=("", 11, "bold")).grid(
            row=7, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )

        ttk.Label(f, text="Client ID").grid(row=8, column=0, sticky=tk.W)
        self._yt_client_id_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._yt_client_id_var, width=36).grid(
            row=8, column=1, sticky=tk.EW, padx=(8, 0)
        )

        ttk.Label(f, text="Client Secret").grid(
            row=9, column=0, sticky=tk.W, pady=(6, 0)
        )
        self._yt_client_secret_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._yt_client_secret_var, show="*", width=36).grid(
            row=9, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 0)
        )

        yt_btn_frame = ttk.Frame(f)
        yt_btn_frame.grid(row=10, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        self._yt_login_btn = ttk.Button(
            yt_btn_frame, text="Authorize YouTube", command=self._login_youtube
        )
        self._yt_login_btn.pack(side=tk.LEFT)
        ttk.Button(
            yt_btn_frame, text="Test Connection", command=self._test_youtube
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._yt_status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._yt_status_var, foreground="gray").grid(
            row=11, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        ttk.Separator(f, orient="horizontal").grid(
            row=12, column=0, columnspan=3, sticky=tk.EW, pady=16
        )

        # ── Facebook ──────────────────────────────────────────────────────
        ttk.Label(f, text="Facebook", font=("", 11, "bold")).grid(
            row=13, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )

        ttk.Label(f, text="App ID").grid(row=14, column=0, sticky=tk.W)
        self._fb_app_id_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._fb_app_id_var, width=36).grid(
            row=14, column=1, sticky=tk.EW, padx=(8, 0)
        )

        ttk.Label(f, text="App Secret").grid(row=15, column=0, sticky=tk.W, pady=(6, 0))
        self._fb_app_secret_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._fb_app_secret_var, show="*", width=36).grid(
            row=15, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 0)
        )

        ttk.Button(
            f, text="1. Open Graph API Explorer", command=self._open_fb_token_page
        ).grid(row=16, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

        ttk.Label(
            f,
            text="Generate a token with these permissions: pages_show_list,\n"
            "pages_read_engagement, pages_manage_posts, publish_video",
            foreground="gray",
        ).grid(row=17, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        ttk.Label(f, text="2. Paste token here").grid(
            row=18, column=0, columnspan=2, sticky=tk.W, pady=(12, 4)
        )
        self._fb_token_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._fb_token_var, width=46, show="*").grid(
            row=19, column=0, columnspan=2, sticky=tk.EW
        )

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=20, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Button(btn_frame, text="Save Token", command=self._login_facebook).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_frame, text="Test Connection", command=self._test_facebook).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self._fb_auth_status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._fb_auth_status_var, foreground="gray").grid(
            row=21, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        ttk.Separator(f, orient="horizontal").grid(
            row=22, column=0, columnspan=3, sticky=tk.EW, pady=16
        )

        ttk.Label(f, text="Personal Stream Key", font=("", 10, "bold")).grid(
            row=23, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(
            f,
            text="Optional — bypasses the Page API. Get your key from\n"
            "facebook.com/live/producer (personal profile).\n"
            "The key is only valid while a live event is in preview there.",
            foreground="gray",
        ).grid(row=24, column=0, columnspan=2, sticky=tk.W, pady=(4, 8))

        self._fb_stream_key_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._fb_stream_key_var, width=46).grid(
            row=25, column=0, columnspan=2, sticky=tk.EW
        )

        self._fb_stream_key_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f,
            text="Use stream key (bypasses Page / Personal Profile API)",
            variable=self._fb_stream_key_enabled_var,
        ).grid(row=26, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        ttk.Button(f, text="Save Stream Key", command=self._save_fb_stream_key).grid(
            row=27, column=0, columnspan=2, sticky=tk.W, pady=(8, 0)
        )

        f.columnconfigure(1, weight=1)
        self._bind_mousewheel(f, _settings_canvas)

    # ── Load saved state ──────────────────────────────────────────────────

    def _load_saved_settings(self) -> None:
        cfg = self._app.config.config

        # Stream defaults
        if cfg.stream.last_title:
            self._title_var.set(cfg.stream.last_title)
        if cfg.stream.last_description:
            self._description.insert("1.0", cfg.stream.last_description)
        self._yt_enabled.set(cfg.stream.youtube_enabled)
        self._fb_enabled.set(cfg.stream.facebook_enabled)
        self._fb_privacy_var.set(cfg.stream.fb_privacy)

        # OBS
        self._obs_host_var.set(cfg.obs.host)
        self._obs_port_var.set(str(cfg.obs.port))
        self._obs_password_var.set(cfg.obs.password)
        # YouTube
        self._yt_client_id_var.set(cfg.youtube.client_id)
        self._yt_client_secret_var.set(cfg.youtube.client_secret)
        if self._app.youtube.is_authenticated():
            self._yt_status_var.set("Authorized")
            self._yt_account_label.config(text="Authorized", foreground="#00aa00")

        # Facebook App credentials
        self._fb_app_id_var.set(cfg.facebook.app_id)
        self._fb_app_secret_var.set(cfg.facebook.app_secret)
        self._fb_stream_key_var.set(cfg.facebook.stream_key_override)
        self._fb_stream_key_enabled_var.set(cfg.facebook.stream_key_enabled)

        # Facebook auth status and Pages
        if self._app.facebook.is_authenticated():
            days = self._app.config.days_until_facebook_expiry()
            self._fb_auth_status_var.set(
                f"Logged in - token expires in {days} days" if days else "Logged in"
            )
            self._run_async(self._load_facebook_pages)

    # ── Settings actions ──────────────────────────────────────────────────

    def _test_obs(self) -> None:
        self._save_obs(silent=True)
        self._run_async(self._do_test_obs)

    def _do_test_obs(self) -> None:
        self._on_main(lambda: self._obs_status_var.set("Connecting..."))
        try:
            cfg = self._app.config.config.obs
            obs = __import__("obsws_python", fromlist=["ReqClient"]).ReqClient(
                host=cfg.host,
                port=cfg.port,
                password=cfg.password,
                timeout=5,
            )
            version = obs.get_version()
            obs.disconnect()
            v = version.obs_version
            self._on_main(lambda: self._obs_status_var.set(f"Connected - OBS {v}"))
        except Exception as exc:
            msg = str(exc)

            def _obs_err() -> None:
                self._obs_status_var.set(f"Failed: {msg}")

            self._on_main(_obs_err)

    def _test_youtube(self) -> None:
        self._run_async(self._do_test_youtube)

    def _do_test_youtube(self) -> None:
        self._on_main(lambda: self._yt_status_var.set("Checking..."))
        try:
            authenticated = self._app.youtube.is_authenticated()
            if authenticated:
                self._on_main(lambda: self._yt_status_var.set("Authorized"))
            else:
                self._on_main(
                    lambda: self._yt_status_var.set(
                        "Not authorized - click Authorize YouTube"
                    )
                )
        except Exception as exc:
            msg = str(exc)

            def _yt_test_err() -> None:
                self._yt_status_var.set(f"Failed: {msg}")

            self._on_main(_yt_test_err)

    def _save_obs(self, silent: bool = False) -> None:
        cfg = self._app.config.config.obs
        cfg.host = self._obs_host_var.get().strip()
        cfg.password = self._obs_password_var.get()
        try:
            cfg.port = int(self._obs_port_var.get())
        except ValueError:
            messagebox.showwarning("Invalid Port", "Port must be a number.")
            return
        self._app.config.save()
        if not silent:
            messagebox.showinfo("Saved", "OBS settings saved.")

    def _login_youtube(self) -> None:
        yt = self._app.config.config.youtube
        yt.client_id = self._yt_client_id_var.get().strip()
        yt.client_secret = self._yt_client_secret_var.get().strip()
        self._app.config.save()
        self._run_async(self._do_login_youtube)

    def _do_login_youtube(self) -> None:
        def _starting() -> None:
            self._yt_status_var.set("Opening browser...")
            self._yt_login_btn.config(state="disabled")

        self._on_main(_starting)
        try:
            self._app.login_youtube()
            channel = self._app.get_youtube_channel_name()
            if channel:
                self._app.config.config.youtube.channel_name = channel
                self._app.config.save()

            def _success() -> None:
                self._yt_account_label.config(text="Authorized", foreground="#00aa00")
                self._yt_status_var.set("Authorized")
                self._yt_login_btn.config(state=tk.NORMAL)
                self._check_go_live_ready()

            self._on_main(_success)
        except Exception as exc:
            msg = str(exc)

            def _err(m: str = msg) -> None:
                messagebox.showerror("YouTube Error", m)
                self._yt_status_var.set("Authorization failed")
                self._yt_login_btn.config(state=tk.NORMAL)

            self._on_main(_err)

    def _open_fb_token_page(self) -> None:
        fb = self._app.config.config.facebook
        fb.app_id = self._fb_app_id_var.get().strip()
        fb.app_secret = self._fb_app_secret_var.get().strip()
        self._app.config.save()
        self._app.open_facebook_token_page()

    def _login_facebook(self) -> None:
        token = self._fb_token_var.get().strip()
        if not token:
            messagebox.showwarning(
                "Missing Token", "Paste your token from Graph API Explorer."
            )
            return
        fb = self._app.config.config.facebook
        fb.app_id = self._fb_app_id_var.get().strip()
        fb.app_secret = self._fb_app_secret_var.get().strip()
        self._app.config.save()
        self._run_async(self._do_login_facebook, token)

    def _do_login_facebook(self, token: str) -> None:
        self._on_main(lambda: self._fb_auth_status_var.set("Exchanging token..."))
        try:
            self._app.login_facebook_with_token(token)
            days = self._app.config.days_until_facebook_expiry()
            status_msg = (
                f"Connected - token expires in {days} days" if days else "Connected"
            )

            def _success(m: str = status_msg) -> None:
                self._fb_auth_status_var.set(m)
                self._fb_token_var.set("")

            self._on_main(_success)
            self._load_facebook_pages()
        except Exception as exc:
            msg = str(exc)

            def _err(m: str = msg) -> None:
                messagebox.showerror("Facebook Error", m)
                self._fb_auth_status_var.set("Login failed")

            self._on_main(_err)

    # ── Facebook Page loading ─────────────────────────────────────────────

    def _save_fb_stream_key(self) -> None:
        fb = self._app.config.config.facebook
        fb.stream_key_override = self._fb_stream_key_var.get().strip()
        fb.stream_key_enabled = self._fb_stream_key_enabled_var.get()
        self._app.config.save()
        messagebox.showinfo("Saved", "Facebook stream key saved.")

    def _test_facebook(self) -> None:
        self._run_async(self._do_test_facebook)

    def _do_test_facebook(self) -> None:
        self._on_main(lambda: self._fb_auth_status_var.set("Testing connection..."))
        try:
            pages = self._app.fetch_facebook_pages()
            names = ", ".join(p.name for p in pages)

            def _fb_test_ok() -> None:
                self._fb_auth_status_var.set(f"Connected - found: {names}")

            self._on_main(_fb_test_ok)
        except Exception as exc:
            msg = str(exc)

            def _fb_test_err() -> None:
                self._fb_auth_status_var.set(f"Failed: {msg}")

            self._on_main(_fb_test_err)

    def _load_facebook_pages(self) -> None:
        try:
            pages = self._app.fetch_facebook_pages()
            pages = [PERSONAL_PROFILE] + pages

            def _apply(p: list[FacebookPage] = pages) -> None:
                self._pages = p
                self._apply_facebook_pages(p)

            self._on_main(_apply)
        except Exception as exc:
            msg = str(exc)

            def _pages_err() -> None:
                self._fb_status_var.set(f"Could not load pages: {msg}")

            self._on_main(_pages_err)

    def _apply_facebook_pages(self, pages: list[FacebookPage]) -> None:
        names = [p.name for p in pages]
        dropdown_state = "readonly" if self._fb_enabled.get() else "disabled"
        self._page_dropdown.config(values=names, state=dropdown_state)

        last_name = self._app.config.config.facebook.last_page_name
        if last_name and last_name in names:
            self._page_dropdown.set(last_name)
            page = next(p for p in pages if p.name == last_name)
            self._app.select_facebook_page(page)
        elif names:
            self._page_dropdown.set(names[0])
            self._app.select_facebook_page(pages[0])

        self._fb_status_var.set(f"{len(pages)} page(s) available")
        self._check_go_live_ready()

    def _on_platform_toggle(self) -> None:
        fb_on = self._fb_enabled.get()
        dropdown_state = "readonly" if fb_on and self._pages else "disabled"
        self._page_dropdown.config(state=dropdown_state)
        self._check_go_live_ready()

    def _on_page_selected(self, _event: object) -> None:
        name = self._page_var.get()
        page = next((p for p in self._pages if p.name == name), None)
        if page:
            self._app.select_facebook_page(page)

    # ── Stream tab actions ────────────────────────────────────────────────

    def _toggle_live(self) -> None:
        if self._is_live:
            self._run_async(self._do_end_stream)
        else:
            # Capture all UI state on the main thread before handing off
            title = self._title_var.get().strip()
            description = self._description.get("1.0", tk.END).strip()
            youtube_on = self._yt_enabled.get()
            facebook_on = self._fb_enabled.get()
            privacy_label = self._fb_privacy_var.get()
            self._run_async(
                self._do_go_live,
                title,
                description,
                youtube_on,
                facebook_on,
                privacy_label,
            )

    def _do_go_live(
        self,
        title: str,
        description: str,
        youtube_on: bool,
        facebook_on: bool,
        privacy_label: str,
    ) -> None:
        if not title:
            self._on_main(
                lambda: messagebox.showwarning(
                    "Missing Title", "Please enter a stream title."
                )
            )
            return

        stream_cfg = self._app.config.config.stream
        stream_cfg.last_title = title
        stream_cfg.last_description = description
        stream_cfg.youtube_enabled = youtube_on
        stream_cfg.facebook_enabled = facebook_on
        stream_cfg.fb_privacy = privacy_label
        self._app.config.save()

        self._on_main(self._reset_status_tab)

        if youtube_on:
            self._on_main(
                lambda: self._set_stream_status("Authorizing YouTube...", busy=True)
            )
            try:
                self._app.login_youtube()
            except Exception as exc:
                msg = str(exc)

                def _yt_err(m: str = msg) -> None:
                    messagebox.showerror("YouTube Error", m)
                    self._set_stream_status("Error starting stream")
                    self._live_btn.config(state=tk.NORMAL)

                self._on_main(_yt_err)
                return

        self._on_main(lambda: self._set_stream_status("Creating streams...", busy=True))
        try:
            privacy_map = {
                "Public": "EVERYONE",
                "Friends": "FRIENDS",
                "Only Me": "SELF",
            }
            status = self._app.go_live(
                StreamConfig(
                    title=title,
                    description=description,
                    fb_privacy=privacy_map.get(privacy_label, "EVERYONE"),
                ),
                youtube=youtube_on,
                facebook=facebook_on,
            )

            def _apply(s: StreamStatus = status) -> None:
                self._stream_status = s
                self._update_status_tab(s)
                self._notebook.select(1)  # type: ignore[no-untyped-call]
                if s.any_live:
                    self._is_live = True
                    self._live_btn.config(text="End Stream", state=tk.NORMAL)
                    self._set_stream_status(s.summary)
                else:
                    self._set_stream_status("All platforms failed — see Status tab")
                    self._live_btn.config(state=tk.NORMAL)

            self._on_main(_apply)
        except Exception as exc:
            msg = str(exc)

            def _err(m: str = msg) -> None:
                messagebox.showerror("Error", m)
                self._set_stream_status("Error starting stream")
                self._live_btn.config(state=tk.NORMAL)

            self._on_main(_err)

    def _do_end_stream(self) -> None:
        self._on_main(lambda: self._set_stream_status("Ending stream...", busy=True))
        try:
            self._app.end_stream()

            def _done() -> None:
                self._is_live = False
                self._stream_status = None
                self._live_btn.config(text="Go Live")
                self._set_stream_status("")
                self._reset_status_tab()
                self._check_go_live_ready()

            self._on_main(_done)
        except Exception as exc:
            msg = str(exc)

            def _err(m: str = msg) -> None:
                messagebox.showerror("Error", m)
                self._set_stream_status("Error - check logs")
                self._live_btn.config(state=tk.NORMAL)

            self._on_main(_err)

    # ── Status tab updates ────────────────────────────────────────────────

    def _on_stop_streaming(self) -> None:
        self._stop_btn.config(state="disabled")
        self._run_async(self._do_end_stream)

    def _reset_status_tab(self) -> None:
        self._is_live = False
        self._overall_status_var.set("Offline")
        self._yt_indicator.config(text="  Offline", foreground="gray")
        self._set_meta_text(self._yt_meta_text, "—")
        self._yt_link.grid_remove()
        self._fb_indicator.config(text="  Offline", foreground="gray")
        self._set_meta_text(self._fb_meta_text, "—")
        self._fb_link.grid_remove()
        self._obs_indicator.config(text="  Disconnected", foreground="gray")
        self._stop_btn.config(state="disabled")

    def _update_status_tab(self, status: StreamStatus) -> None:
        self._overall_status_var.set(status.summary)

        # YouTube
        yt = status.youtube
        if not yt.attempted:
            self._yt_indicator.config(text="  Skipped", foreground="gray")
            self._set_meta_text(self._yt_meta_text, "—")
            self._yt_link.grid_remove()
        elif yt.live:
            self._yt_indicator.config(text="  ● Live", foreground="red")
            self._set_meta_text(
                self._yt_meta_text, f"Title: {yt.title}\nStarted: {yt.started_at}"
            )
            self._set_link(self._yt_link, yt.url, "Watch on YouTube →")
        elif yt.error:
            self._yt_indicator.config(text="  Failed", foreground="orange")
            self._set_meta_text(self._yt_meta_text, f"Error: {yt.error}")
            self._yt_link.grid_remove()
        else:
            self._yt_indicator.config(text="  Not started", foreground="gray")
            self._set_meta_text(self._yt_meta_text, "—")
            self._yt_link.grid_remove()

        # Facebook
        fb = status.facebook
        if not fb.attempted:
            self._fb_indicator.config(text="  Skipped", foreground="gray")
            self._set_meta_text(self._fb_meta_text, "—")
            self._fb_link.grid_remove()
        elif fb.live:
            self._fb_indicator.config(text="  ● Live", foreground="red")
            page = f"Page: {fb.page_name}\n" if fb.page_name else ""
            self._set_meta_text(
                self._fb_meta_text,
                f"{page}Title: {fb.title}\nStarted: {fb.started_at}",
            )
            self._set_link(self._fb_link, fb.url, "Watch on Facebook →")
        elif fb.error:
            self._fb_indicator.config(text="  Failed", foreground="orange")
            self._set_meta_text(self._fb_meta_text, f"Error: {fb.error}")
            self._fb_link.grid_remove()
        else:
            self._fb_indicator.config(text="  Not started", foreground="gray")
            self._set_meta_text(self._fb_meta_text, "—")
            self._fb_link.grid_remove()

        # OBS
        self._is_live = status.any_live
        self._obs_indicator.config(text="  Connected", foreground="green")
        self._stop_btn.config(state=tk.NORMAL if status.any_live else "disabled")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _check_go_live_ready(self) -> None:
        yt_ok = self._yt_enabled.get()
        fb_ok = (
            self._fb_enabled.get() and bool(self._pages) and bool(self._page_var.get())
        )
        ready = yt_ok or fb_ok
        self._live_btn.config(state=tk.NORMAL if ready else "disabled")

    def _set_stream_status(self, message: str, busy: bool = False) -> None:
        self._stream_status_var.set(message)
        if busy:
            self._live_btn.config(state="disabled")

    def _run_async(self, fn: object, *args: object) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()  # type: ignore[arg-type]

    def _on_main(self, fn: Callable[[], object]) -> None:
        """Schedule fn to run on the main thread. Safe to call from any thread."""
        self._ui_queue.put(fn)

    def _pump_ui(self) -> None:
        while True:
            try:
                self._ui_queue.get_nowait()()
            except queue.Empty:
                break
        self._root.after(self._UI_PUMP_INTERVAL_MS, self._pump_ui)

    # ── OBS status polling ────────────────────────────────────────────────

    def _schedule_obs_poll(self) -> None:
        threading.Thread(target=self._do_obs_poll, daemon=True).start()
        self._root.after(self._OBS_POLL_INTERVAL_MS, self._schedule_obs_poll)

    def _do_obs_poll(self) -> None:
        if self._is_live:
            return
        connected, streaming = self._app.check_obs_status()

        def _poll_cb() -> None:
            self._apply_obs_poll(connected, streaming)

        self._on_main(_poll_cb)

    def _apply_obs_poll(self, connected: bool, streaming: bool) -> None:
        if self._is_live:
            return
        if streaming:
            self._is_live = True
            self._obs_indicator.config(
                text="  Streaming (external)", foreground="orange"
            )
            self._overall_status_var.set("OBS streaming (external)")
            self._stop_btn.config(state=tk.NORMAL)
        elif connected:
            self._obs_indicator.config(text="  Connected", foreground="green")
        else:
            self._obs_indicator.config(text="  Not running", foreground="gray")

    def run(self) -> None:
        self._root.mainloop()
