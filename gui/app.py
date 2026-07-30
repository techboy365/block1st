"""
ProMailer Pro — Main Application Window
Modern dark-themed GUI built with CustomTkinter.
"""
import os
import sys
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, List, Optional

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from core.config_manager import ConfigManager
from core.smtp_pool import SmartSMTPPool
from core.proxy_manager import ProxyManager
from core.email_engine import EmailEngine

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
DARK_BG        = "#0f0f1a"
CARD_BG        = "#1a1a2e"
SIDEBAR_BG     = "#13131f"
ACCENT         = "#4f8ef7"
ACCENT_HOVER   = "#6ba3ff"
SUCCESS_CLR    = "#2ecc71"
ERROR_CLR      = "#e74c3c"
WARN_CLR       = "#f39c12"
TEXT_CLR       = "#e8e8f0"
MUTED_CLR      = "#8888aa"
BORDER_CLR     = "#2a2a40"

FONT_H1  = ("Segoe UI", 22, "bold")
FONT_H2  = ("Segoe UI", 14, "bold")
FONT_H3  = ("Segoe UI", 12, "bold")
FONT_BODY = ("Segoe UI", 11)
FONT_MONO = ("Consolas", 10)
FONT_SM  = ("Segoe UI", 10)


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class StatCard(ctk.CTkFrame):
    """Metric card with label, large value, and optional sub-label."""

    def __init__(self, parent, title: str, value: str = "0",
                 color: str = ACCENT, **kw):
        super().__init__(parent, fg_color=CARD_BG, corner_radius=12,
                         border_width=1, border_color=BORDER_CLR, **kw)
        ctk.CTkLabel(self, text=title, font=FONT_SM,
                     text_color=MUTED_CLR).pack(anchor="w", padx=16, pady=(14, 0))
        self._val_lbl = ctk.CTkLabel(self, text=value, font=("Segoe UI", 32, "bold"),
                                     text_color=color)
        self._val_lbl.pack(anchor="w", padx=16, pady=(2, 14))

    def set(self, value: str):
        self._val_lbl.configure(text=str(value))


class SectionHeader(ctk.CTkFrame):
    def __init__(self, parent, title: str, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        ctk.CTkLabel(self, text=title, font=FONT_H2,
                     text_color=TEXT_CLR).pack(side="left")
        sep = ctk.CTkFrame(self, height=1, fg_color=BORDER_CLR)
        sep.pack(side="left", fill="x", expand=True, padx=(16, 0), pady=8)


def _make_treeview(parent, columns: List[tuple], height: int = 12) -> ttk.Treeview:
    """Create a dark-styled ttk.Treeview."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
                    background="#1a1a2e",
                    foreground=TEXT_CLR,
                    rowheight=28,
                    fieldbackground="#1a1a2e",
                    borderwidth=0,
                    font=FONT_BODY)
    style.configure("Dark.Treeview.Heading",
                    background="#13131f",
                    foreground=TEXT_CLR,
                    borderwidth=0,
                    font=FONT_H3)
    style.map("Dark.Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", "#ffffff")])

    col_ids = [c[0] for c in columns]
    tv = ttk.Treeview(parent, columns=col_ids, show="headings",
                      height=height, style="Dark.Treeview")
    for cid, label, width in columns:
        tv.heading(cid, text=label)
        tv.column(cid, width=width, anchor="w", stretch=True)
    return tv


# ---------------------------------------------------------------------------
# Sidebar button
# ---------------------------------------------------------------------------

class NavButton(ctk.CTkButton):
    def __init__(self, parent, text: str, icon: str, command, **kw):
        super().__init__(
            parent,
            text=f"  {icon}   {text}",
            font=FONT_BODY,
            height=44,
            anchor="w",
            corner_radius=10,
            fg_color="transparent",
            hover_color=BORDER_CLR,
            text_color=TEXT_CLR,
            command=command,
            **kw,
        )

    def set_active(self, active: bool):
        self.configure(fg_color=ACCENT if active else "transparent")


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class EmailSenderApp:
    def __init__(self):
        if not CTK_AVAILABLE:
            raise RuntimeError(
                "customtkinter is not installed.\n"
                "Run: pip install customtkinter"
            )

        self.root = ctk.CTk()
        self.root.title("ProMailer Pro")
        self.root.geometry("1380x860")
        self.root.minsize(1100, 700)
        self.root.configure(fg_color=DARK_BG)

        # Core objects
        self.config_mgr = ConfigManager()
        self.engine = EmailEngine()
        self.smtp_pool: Optional[SmartSMTPPool] = None
        self.proxy_mgr: Optional[ProxyManager] = None

        # GUI update queue (from worker threads → main thread)
        self._gui_queue: queue.Queue = queue.Queue()

        # Wire engine callbacks
        self.engine.on_progress = self._on_progress
        self.engine.on_log = self._on_log
        self.engine.on_complete = self._on_complete

        self._build_ui()
        self._poll_gui_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self.root, width=220, fg_color=SIDEBAR_BG,
                                    corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(20, 10))
        ctk.CTkLabel(logo_frame, text="ProMailer", font=("Segoe UI", 20, "bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(logo_frame, text=" Pro", font=("Segoe UI", 20, "bold"),
                     text_color=TEXT_CLR).pack(side="left")

        ctk.CTkFrame(self.sidebar, height=1, fg_color=BORDER_CLR).pack(
            fill="x", padx=16, pady=8)

        # Nav buttons
        nav_items = [
            ("Dashboard", "📊", "dashboard"),
            ("Campaign", "📧", "campaign"),
            ("SMTP Servers", "🔧", "smtp"),
            ("Proxies", "🔒", "proxies"),
            ("Settings", "⚙️", "settings"),
            ("Logs", "📝", "logs"),
        ]
        self._nav_buttons: Dict[str, NavButton] = {}
        for label, icon, key in nav_items:
            btn = NavButton(self.sidebar, label, icon,
                            command=lambda k=key: self.show_tab(k))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[key] = btn

        # Status bar at bottom of sidebar
        ctk.CTkFrame(self.sidebar, height=1, fg_color=BORDER_CLR).pack(
            fill="x", padx=16, pady=8, side="bottom")
        self._status_dot = ctk.CTkLabel(
            self.sidebar, text="● Idle", font=FONT_SM, text_color=MUTED_CLR)
        self._status_dot.pack(side="bottom", padx=16, pady=(0, 12))

        # Content area
        self.content = ctk.CTkFrame(self.root, fg_color=DARK_BG, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

        # Build tabs
        self._tabs: Dict[str, ctk.CTkFrame] = {}
        self._build_dashboard_tab()
        self._build_campaign_tab()
        self._build_smtp_tab()
        self._build_proxies_tab()
        self._build_settings_tab()
        self._build_logs_tab()

        self.show_tab("dashboard")

    def show_tab(self, key: str):
        for frame in self._tabs.values():
            frame.pack_forget()
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)
        self._tabs[key].pack(fill="both", expand=True, padx=0, pady=0)
        self._current_tab = key

    # ------------------------------------------------------------------
    # DASHBOARD TAB
    # ------------------------------------------------------------------

    def _build_dashboard_tab(self):
        tab = ctk.CTkScrollableFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["dashboard"] = tab

        pad = {"padx": 24, "pady": 8}

        ctk.CTkLabel(tab, text="Dashboard", font=FONT_H1,
                     text_color=TEXT_CLR).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(tab, text="Live campaign overview",
                     font=FONT_SM, text_color=MUTED_CLR).pack(anchor="w", padx=24, pady=(0, 16))

        # ── Stat cards ──────────────────────────────────────────
        cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        cards_frame.pack(fill="x", **pad)
        cards_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self._card_total  = StatCard(cards_frame, "Total Recipients", "0", MUTED_CLR)
        self._card_sent   = StatCard(cards_frame, "Sent", "0", SUCCESS_CLR)
        self._card_failed = StatCard(cards_frame, "Failed", "0", ERROR_CLR)
        self._card_rate   = StatCard(cards_frame, "Rate / sec", "0.0", ACCENT)

        for col, card in enumerate([self._card_total, self._card_sent,
                                     self._card_failed, self._card_rate]):
            card.grid(row=0, column=col, padx=6, pady=0, sticky="ew")

        # ── Progress ────────────────────────────────────────────
        prog_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=BORDER_CLR)
        prog_frame.pack(fill="x", padx=24, pady=8)

        prog_top = ctk.CTkFrame(prog_frame, fg_color="transparent")
        prog_top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(prog_top, text="Progress", font=FONT_H3,
                     text_color=TEXT_CLR).pack(side="left")
        self._pct_label = ctk.CTkLabel(prog_top, text="0%", font=FONT_H3,
                                        text_color=ACCENT)
        self._pct_label.pack(side="right")

        self._progress_bar = ctk.CTkProgressBar(prog_frame, height=14,
                                                 corner_radius=7,
                                                 fg_color=BORDER_CLR,
                                                 progress_color=ACCENT)
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x", padx=16, pady=(0, 8))

        eta_frame = ctk.CTkFrame(prog_frame, fg_color="transparent")
        eta_frame.pack(fill="x", padx=16, pady=(0, 14))
        self._elapsed_lbl = ctk.CTkLabel(eta_frame, text="Elapsed: —",
                                          font=FONT_SM, text_color=MUTED_CLR)
        self._elapsed_lbl.pack(side="left")
        self._eta_lbl = ctk.CTkLabel(eta_frame, text="ETA: —",
                                      font=FONT_SM, text_color=MUTED_CLR)
        self._eta_lbl.pack(side="right")

        # ── Control buttons ─────────────────────────────────────
        ctrl = ctk.CTkFrame(tab, fg_color="transparent")
        ctrl.pack(padx=24, pady=8, anchor="w")

        self._btn_start = ctk.CTkButton(
            ctrl, text="▶  Start Campaign", width=160, height=44,
            corner_radius=10, font=FONT_H3,
            fg_color=SUCCESS_CLR, hover_color="#27ae60",
            command=self._action_start)
        self._btn_start.pack(side="left", padx=(0, 8))

        self._btn_pause = ctk.CTkButton(
            ctrl, text="⏸  Pause", width=120, height=44,
            corner_radius=10, font=FONT_H3,
            fg_color=CARD_BG, hover_color=BORDER_CLR,
            border_width=1, border_color=BORDER_CLR,
            text_color=TEXT_CLR, state="disabled",
            command=self._action_pause)
        self._btn_pause.pack(side="left", padx=(0, 8))

        self._btn_stop = ctk.CTkButton(
            ctrl, text="⏹  Stop", width=120, height=44,
            corner_radius=10, font=FONT_H3,
            fg_color=CARD_BG, hover_color=BORDER_CLR,
            border_width=1, border_color=BORDER_CLR,
            text_color=TEXT_CLR, state="disabled",
            command=self._action_stop)
        self._btn_stop.pack(side="left")

        # ── Recent log feed ──────────────────────────────────────
        log_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=BORDER_CLR)
        log_frame.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(log_frame, text="Recent Activity",
                     font=FONT_H3, text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(12, 6))
        self._dash_log = ctk.CTkTextbox(
            log_frame, height=160, font=FONT_MONO,
            fg_color="#0d0d1a", text_color=TEXT_CLR,
            state="disabled", corner_radius=8)
        self._dash_log.pack(fill="x", padx=12, pady=(0, 12))

        # ── SMTP Pool status ─────────────────────────────────────
        pool_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12,
                                   border_width=1, border_color=BORDER_CLR)
        pool_frame.pack(fill="x", padx=24, pady=(8, 24))
        ctk.CTkLabel(pool_frame, text="SMTP Server Pool",
                     font=FONT_H3, text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(12, 6))

        cols = [("host", "Host", 160), ("port", "Port", 70),
                ("status", "Status", 100), ("sent", "Sent", 80),
                ("failed", "Failed", 80), ("rate", "Success %", 90), ("latency", "Avg ms", 80)]
        self._pool_tv = _make_treeview(pool_frame, cols, height=5)
        self._pool_tv.pack(fill="x", padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    # CAMPAIGN TAB
    # ------------------------------------------------------------------

    def _build_campaign_tab(self):
        tab = ctk.CTkScrollableFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["campaign"] = tab

        ctk.CTkLabel(tab, text="Campaign Setup", font=FONT_H1,
                     text_color=TEXT_CLR).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(tab, text="Configure your email campaign",
                     font=FONT_SM, text_color=MUTED_CLR).pack(anchor="w", padx=24, pady=(0, 16))

        def card(parent, title):
            f = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12,
                             border_width=1, border_color=BORDER_CLR)
            f.pack(fill="x", padx=24, pady=6)
            ctk.CTkLabel(f, text=title, font=FONT_H3,
                         text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(14, 8))
            return f

        # ── Recipients ───────────────────────────────────────────
        rec_card = card(tab, "Recipients & Links")
        self._recipients_var = tk.StringVar(value=self.config_mgr.get("recipient_list_file", ""))
        self._links_var = tk.StringVar(value=self.config_mgr.get("links_file", ""))

        self._file_row(rec_card, "Recipients File:", self._recipients_var,
                       "*.txt", "Select recipients file")
        self._file_row(rec_card, "Links File:", self._links_var,
                       "*.txt", "Select links file")
        ctk.CTkFrame(rec_card, height=10, fg_color="transparent").pack()

        # ── Sender ───────────────────────────────────────────────
        sender_card = card(tab, "Sender Identity")
        self._sender_name_var = tk.StringVar(value=self.config_mgr.get("sender_name", ""))
        self._subject_var = tk.StringVar(value=self.config_mgr.get("subject", ""))

        self._field_row(sender_card, "Sender Name:", self._sender_name_var)
        self._field_row(sender_card, "Subject:", self._subject_var)
        ctk.CTkFrame(sender_card, height=10, fg_color="transparent").pack()

        # ── Message Body ─────────────────────────────────────────
        body_card = card(tab, "Message Body")
        self._body_file_var = tk.StringVar(value=self.config_mgr.get("message_body_file", ""))
        self._file_row(body_card, "Body File (HTML):", self._body_file_var,
                       "*.html *.txt", "Select body file")

        ctk.CTkLabel(body_card, text="Or inline body (overridden by file above):",
                     font=FONT_SM, text_color=MUTED_CLR).pack(anchor="w", padx=16, pady=(8, 2))

        body_type_frame = ctk.CTkFrame(body_card, fg_color="transparent")
        body_type_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._body_type_var = tk.StringVar(value=self.config_mgr.get("message_body_type", "html"))
        ctk.CTkLabel(body_type_frame, text="Type:", font=FONT_SM,
                     text_color=MUTED_CLR).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(body_type_frame, values=["html", "plain"],
                          variable=self._body_type_var, width=100).pack(side="left")

        self._body_text = ctk.CTkTextbox(body_card, height=200, font=FONT_MONO,
                                          fg_color="#0d0d1a", text_color=TEXT_CLR,
                                          corner_radius=8)
        self._body_text.pack(fill="x", padx=16, pady=(0, 4))
        self._body_text.insert("1.0", self.config_mgr.get("message_body", ""))

        # Placeholder reference
        ref_frame = ctk.CTkFrame(body_card, fg_color=DARK_BG, corner_radius=8)
        ref_frame.pack(fill="x", padx=16, pady=(0, 12))
        tags = ("%EMAIL%  %FIRSTNAME%  %LAST%  %FULLNAME%  %DOMAIN%  "
                "%DATE%  %TIME%  %RANDOMENUM%  %LINK%")
        ctk.CTkLabel(ref_frame, text=f"📎 Tags: {tags}", font=("Consolas", 9),
                     text_color=MUTED_CLR, wraplength=700,
                     justify="left").pack(padx=12, pady=6)

        # ── Attachments ──────────────────────────────────────────
        att_card = card(tab, "Attachments")
        self._html2pdf_var = tk.BooleanVar(value=self.config_mgr.get("html2pdf", False))
        ctk.CTkSwitch(att_card, text="Generate PDF from HTML",
                      variable=self._html2pdf_var).pack(anchor="w", padx=16, pady=(0, 6))
        self._pdf_file_var = tk.StringVar(value=self.config_mgr.get("html2pdf_file", ""))
        self._pdf_name_var = tk.StringVar(
            value=self.config_mgr.get("html2pdf_attachment_name", "document.pdf"))
        self._file_row(att_card, "HTML Template:", self._pdf_file_var,
                       "*.html", "Select HTML template")
        self._field_row(att_card, "Attachment Name:", self._pdf_name_var)

        self._attach_file_var = tk.StringVar(value=self.config_mgr.get("attachment_path", ""))
        self._file_row(att_card, "Generic Attachment:", self._attach_file_var,
                       "*.*", "Select attachment file")
        ctk.CTkFrame(att_card, height=10, fg_color="transparent").pack()

        # ── Test & Save ──────────────────────────────────────────
        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(padx=24, pady=12, anchor="w")

        self._test_email_var = tk.StringVar(value=self.config_mgr.get("test_email", ""))
        ctk.CTkEntry(btn_row, textvariable=self._test_email_var,
                     placeholder_text="test@example.com", width=220).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Send Test Email", width=140, height=38,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._action_test_email).pack(side="left", padx=(0, 16))
        ctk.CTkButton(btn_row, text="Save Campaign", width=130, height=38,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=self._action_save_campaign).pack(side="left")

    # ------------------------------------------------------------------
    # SMTP SERVERS TAB
    # ------------------------------------------------------------------

    def _build_smtp_tab(self):
        tab = ctk.CTkFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["smtp"] = tab

        # Header
        hdr = ctk.CTkFrame(tab, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkLabel(hdr, text="SMTP Servers", font=FONT_H1,
                     text_color=TEXT_CLR).pack(side="left")

        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="+ Add Server", width=120, height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._smtp_add).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Edit", width=80, height=36,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=self._smtp_edit).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Delete", width=80, height=36,
                      fg_color=CARD_BG, border_width=1, border_color="#aa3333",
                      text_color=ERROR_CLR, hover_color="#2a1a1a",
                      command=self._smtp_delete).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Test Selected", width=110, height=36,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=self._smtp_test_selected).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Import JSON", width=110, height=36,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=self._smtp_import).pack(side="left", padx=4)

        # Rotation strategy
        rot_bar = ctk.CTkFrame(tab, fg_color="transparent")
        rot_bar.pack(fill="x", padx=24, pady=(8, 4))
        ctk.CTkLabel(rot_bar, text="Rotation:", font=FONT_SM,
                     text_color=MUTED_CLR).pack(side="left", padx=(0, 8))
        self._smtp_rotation_var = tk.StringVar(
            value=self.config_mgr.get("smtp_rotation", "weighted"))
        ctk.CTkOptionMenu(rot_bar,
                          values=["weighted", "round_robin", "random"],
                          variable=self._smtp_rotation_var, width=140).pack(side="left")

        # Table
        tbl_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=BORDER_CLR)
        tbl_frame.pack(fill="both", expand=True, padx=24, pady=(8, 24))

        cols = [("host", "SMTP Host", 180), ("port", "Port", 60),
                ("user", "Username", 180), ("from", "From Email", 180),
                ("sent", "Sent", 70), ("failed", "Failed", 70),
                ("rate", "Success %", 90), ("status", "Status", 110)]
        self._smtp_tv = _make_treeview(tbl_frame, cols, height=18)
        sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._smtp_tv.yview)
        self._smtp_tv.configure(yscrollcommand=sb.set)
        self._smtp_tv.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        sb.pack(side="right", fill="y", pady=8)

        self._smtp_refresh_table()

    # ------------------------------------------------------------------
    # PROXIES TAB
    # ------------------------------------------------------------------

    def _build_proxies_tab(self):
        tab = ctk.CTkFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["proxies"] = tab

        hdr = ctk.CTkFrame(tab, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        ctk.CTkLabel(hdr, text="Proxy Manager", font=FONT_H1,
                     text_color=TEXT_CLR).pack(side="left")

        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")
        for (label, cmd, clr, bclr) in [
            ("Import File", self._proxy_import_file, CARD_BG, BORDER_CLR),
            ("Paste / Text", self._proxy_import_text, CARD_BG, BORDER_CLR),
            ("Validate All", self._proxy_validate_all, ACCENT, ACCENT),
            ("Delete", self._proxy_delete, CARD_BG, "#aa3333"),
            ("Clear All", self._proxy_clear_all, CARD_BG, "#aa3333"),
        ]:
            ctk.CTkButton(btn_row, text=label, width=110, height=36,
                          fg_color=clr, hover_color=BORDER_CLR,
                          border_width=1, border_color=bclr,
                          text_color=TEXT_CLR,
                          command=cmd).pack(side="left", padx=4)

        # Options row
        opt = ctk.CTkFrame(tab, fg_color="transparent")
        opt.pack(fill="x", padx=24, pady=(8, 4))
        ctk.CTkLabel(opt, text="Proxy enabled:", font=FONT_SM,
                     text_color=MUTED_CLR).pack(side="left", padx=(0, 8))
        self._use_proxy_var = tk.BooleanVar(value=self.config_mgr.get("use_sock", False))
        ctk.CTkSwitch(opt, text="", variable=self._use_proxy_var).pack(side="left", padx=(0, 24))
        ctk.CTkLabel(opt, text="Type:", font=FONT_SM,
                     text_color=MUTED_CLR).pack(side="left", padx=(0, 8))
        self._proxy_type_var = tk.StringVar(value="socks5")
        ctk.CTkOptionMenu(opt, values=["socks5", "socks4", "http"],
                          variable=self._proxy_type_var, width=100).pack(side="left", padx=(0, 24))
        ctk.CTkLabel(opt, text="Rotation:", font=FONT_SM,
                     text_color=MUTED_CLR).pack(side="left", padx=(0, 8))
        self._proxy_rotation_var = tk.StringVar(
            value=self.config_mgr.get("proxy_rotation", "round_robin"))
        ctk.CTkOptionMenu(opt, values=["round_robin", "weighted", "random"],
                          variable=self._proxy_rotation_var, width=120).pack(side="left")

        # Summary bar
        self._proxy_summary = ctk.CTkLabel(tab, text="No proxies loaded",
                                            font=FONT_SM, text_color=MUTED_CLR)
        self._proxy_summary.pack(anchor="w", padx=24, pady=(4, 2))

        # Table
        tbl_frame = ctk.CTkFrame(tab, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=BORDER_CLR)
        tbl_frame.pack(fill="both", expand=True, padx=24, pady=(4, 24))

        cols = [("host", "Host", 160), ("port", "Port", 70),
                ("type", "Type", 80), ("status", "Status", 90),
                ("latency", "Latency ms", 100), ("success", "Success", 70),
                ("fail", "Fail", 70), ("rate", "Rate %", 80)]
        self._proxy_tv = _make_treeview(tbl_frame, cols, height=18)
        sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._proxy_tv.yview)
        self._proxy_tv.configure(yscrollcommand=sb.set)
        self._proxy_tv.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        sb.pack(side="right", fill="y", pady=8)

    # ------------------------------------------------------------------
    # SETTINGS TAB
    # ------------------------------------------------------------------

    def _build_settings_tab(self):
        tab = ctk.CTkScrollableFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["settings"] = tab

        ctk.CTkLabel(tab, text="Settings", font=FONT_H1,
                     text_color=TEXT_CLR).pack(anchor="w", padx=24, pady=(20, 4))

        def card(parent, title):
            f = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12,
                             border_width=1, border_color=BORDER_CLR)
            f.pack(fill="x", padx=24, pady=6)
            ctk.CTkLabel(f, text=title, font=FONT_H3,
                         text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(14, 8))
            return f

        def slider_row(parent, label, var, from_, to_, key, fmt="{:.0f}"):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=label, font=FONT_SM,
                         text_color=TEXT_CLR, width=200, anchor="w").pack(side="left")
            val_lbl = ctk.CTkLabel(row, text=fmt.format(var.get()),
                                   font=FONT_SM, text_color=ACCENT, width=50)
            val_lbl.pack(side="right")

            def _update(v):
                val_lbl.configure(text=fmt.format(float(v)))
                self.config_mgr.set(key, int(float(v)) if "{:.0f}" in fmt else float(v))

            sl = ctk.CTkSlider(row, from_=from_, to=to_, variable=var, command=_update)
            sl.pack(side="left", fill="x", expand=True, padx=8)
            return sl

        # Threading
        perf_card = card(tab, "Performance")
        self._threads_var = tk.DoubleVar(value=self.config_mgr.get("num_threads", 50))
        self._retries_var = tk.DoubleVar(value=self.config_mgr.get("max_retries", 3))
        self._max_errors_var = tk.DoubleVar(value=self.config_mgr.get("max_errors_before_stop", 100))
        slider_row(perf_card, "Worker Threads", self._threads_var, 1, 500, "num_threads")
        slider_row(perf_card, "Max Retries", self._retries_var, 0, 10, "max_retries")
        slider_row(perf_card, "Max Errors Before Stop", self._max_errors_var, 1, 5000, "max_errors_before_stop")
        ctk.CTkFrame(perf_card, height=10, fg_color="transparent").pack()

        # Connection pool
        pool_card = card(tab, "Connection Pool")
        self._timeout_var = tk.DoubleVar(value=self.config_mgr.get("connection_timeout", 15))
        self._max_reuse_var = tk.DoubleVar(value=self.config_mgr.get("max_reuse", 200))
        self._max_age_var = tk.DoubleVar(value=self.config_mgr.get("max_age", 600))
        self._max_conns_var = tk.DoubleVar(value=self.config_mgr.get("max_conns_per_server", 10))
        slider_row(pool_card, "Connection Timeout (s)", self._timeout_var, 5, 60, "connection_timeout")
        slider_row(pool_card, "Max Reuse per Connection", self._max_reuse_var, 10, 1000, "max_reuse")
        slider_row(pool_card, "Max Connection Age (s)", self._max_age_var, 60, 3600, "max_age")
        slider_row(pool_card, "Max Connections per Server", self._max_conns_var, 1, 50, "max_conns_per_server")
        ctk.CTkFrame(pool_card, height=10, fg_color="transparent").pack()

        # Exchange
        exch_card = card(tab, "Exchange (OWA)")
        self._use_exchange_var = tk.BooleanVar(value=self.config_mgr.get("use_exchange", False))
        ctk.CTkSwitch(exch_card, text="Use Exchange/OWA mode",
                      variable=self._use_exchange_var).pack(anchor="w", padx=16, pady=(0, 8))
        self._exch_json_btn = ctk.CTkButton(
            exch_card, text="Edit OWA Accounts (JSON)", width=200, height=36,
            fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
            text_color=TEXT_CLR, hover_color=BORDER_CLR,
            command=self._edit_owa_json)
        self._exch_json_btn.pack(anchor="w", padx=16, pady=(0, 14))

        # Save
        ctk.CTkButton(tab, text="Save All Settings", width=180, height=44,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=FONT_H3,
                      command=self._action_save_settings).pack(padx=24, pady=(12, 24), anchor="w")

    # ------------------------------------------------------------------
    # LOGS TAB
    # ------------------------------------------------------------------

    def _build_logs_tab(self):
        tab = ctk.CTkFrame(self.content, fg_color=DARK_BG, corner_radius=0)
        self._tabs["logs"] = tab

        hdr = ctk.CTkFrame(tab, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(hdr, text="Logs", font=FONT_H1,
                     text_color=TEXT_CLR).pack(side="left")
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")

        self._log_filter_var = tk.StringVar(value="ALL")
        ctk.CTkOptionMenu(btn_row, values=["ALL", "INFO", "WARNING", "ERROR"],
                          variable=self._log_filter_var, width=100,
                          command=lambda _: None).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Export", width=80, height=36,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=self._export_logs).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Clear", width=80, height=36,
                      fg_color=CARD_BG, border_width=1, border_color="#aa3333",
                      text_color=ERROR_CLR, hover_color="#2a1a1a",
                      command=self._clear_logs).pack(side="left", padx=4)

        self._log_text = ctk.CTkTextbox(
            tab, font=FONT_MONO, fg_color="#0a0a14",
            text_color=TEXT_CLR, state="disabled", corner_radius=8,
            scrollbar_button_color=BORDER_CLR)
        self._log_text.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        # Color tags via underlying tk.Text
        self._log_text._textbox.tag_configure("INFO",    foreground="#7ecbff")
        self._log_text._textbox.tag_configure("WARNING", foreground=WARN_CLR)
        self._log_text._textbox.tag_configure("ERROR",   foreground=ERROR_CLR)
        self._log_text._textbox.tag_configure("SUCCESS", foreground=SUCCESS_CLR)
        self._log_text._textbox.tag_configure("TS",      foreground="#555577")

        self._log_entries = []  # (level, ts, msg)

    # ------------------------------------------------------------------
    # Actions — Campaign
    # ------------------------------------------------------------------

    def _action_start(self):
        if self.engine.is_running:
            return
        if not self._build_engine():
            return

        recipient_file = self._recipients_var.get().strip()
        if not recipient_file or not os.path.exists(recipient_file):
            messagebox.showerror("Error", "Recipients file not found or not set.")
            return

        try:
            with open(recipient_file, "r", encoding="utf-8") as f:
                recipients = [ln.strip() for ln in f if ln.strip()]
        except Exception as e:
            messagebox.showerror("Error", f"Could not read recipients: {e}")
            return

        if not recipients:
            messagebox.showwarning("Warning", "Recipients file is empty.")
            return

        links_file = self._links_var.get().strip()
        links_list = []
        if links_file and os.path.exists(links_file):
            with open(links_file, "r", encoding="utf-8") as f:
                links_list = [ln.strip() for ln in f if ln.strip()]

        self._save_campaign_state()
        self.engine.start(recipients)

        self._card_total.set(str(len(recipients)))
        self._progress_bar.set(0)
        self._btn_start.configure(state="disabled")
        self._btn_pause.configure(state="normal")
        self._btn_stop.configure(state="normal")
        self._set_status("● Running", SUCCESS_CLR)
        self.show_tab("dashboard")

    def _action_pause(self):
        if self.engine.is_paused:
            self.engine.resume()
            self._btn_pause.configure(text="⏸  Pause")
            self._set_status("● Running", SUCCESS_CLR)
        else:
            self.engine.pause()
            self._btn_pause.configure(text="▶  Resume")
            self._set_status("● Paused", WARN_CLR)

    def _action_stop(self):
        self.engine.stop()
        self._btn_start.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸  Pause")
        self._btn_stop.configure(state="disabled")
        self._set_status("● Stopped", ERROR_CLR)

    def _action_test_email(self):
        test_addr = self._test_email_var.get().strip()
        if not test_addr:
            messagebox.showwarning("Warning", "Enter a test email address.")
            return
        if not self._build_engine():
            return

        def _run():
            self._log("INFO", f"Sending test email to {test_addr} …")
            self.engine.start([test_addr])

        threading.Thread(target=_run, daemon=True).start()

    def _action_save_campaign(self):
        self._save_campaign_state()
        if self.config_mgr.save():
            self._log("INFO", "Campaign settings saved to config.json")
        else:
            messagebox.showerror("Error", "Failed to save config.json")

    def _save_campaign_state(self):
        cfg = {
            "recipient_list_file": self._recipients_var.get(),
            "links_file": self._links_var.get(),
            "sender_name": self._sender_name_var.get(),
            "subject": self._subject_var.get(),
            "message_body_file": self._body_file_var.get(),
            "message_body": self._body_text.get("1.0", "end-1c"),
            "message_body_type": self._body_type_var.get(),
            "html2pdf": self._html2pdf_var.get(),
            "html2pdf_file": self._pdf_file_var.get(),
            "html2pdf_attachment_name": self._pdf_name_var.get(),
            "attachment_path": self._attach_file_var.get(),
            "test_email": self._test_email_var.get(),
        }
        self.config_mgr.update(cfg)

    # ------------------------------------------------------------------
    # Actions — SMTP
    # ------------------------------------------------------------------

    def _smtp_refresh_table(self):
        for row in self._smtp_tv.get_children():
            self._smtp_tv.delete(row)
        for srv in self.config_mgr.get_smtp_servers():
            self._smtp_tv.insert("", "end", values=(
                srv.get("smtp_server", ""), srv.get("port", 587),
                srv.get("username", ""), srv.get("from_email", ""),
                0, 0, "—", "—",
            ))
        if self.smtp_pool:
            for i, info in enumerate(self.smtp_pool.get_stats()["servers"]):
                items = self._smtp_tv.get_children()
                if i < len(items):
                    self._smtp_tv.set(items[i], "sent", info["sent"])
                    self._smtp_tv.set(items[i], "failed", info["failed"])
                    self._smtp_tv.set(items[i], "rate", f"{info['success_rate']}%")
                    self._smtp_tv.set(items[i], "status", info["status"])

    def _smtp_add(self):
        self._smtp_dialog()

    def _smtp_edit(self):
        sel = self._smtp_tv.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a server to edit.")
            return
        idx = self._smtp_tv.index(sel[0])
        servers = self.config_mgr.get_smtp_servers()
        if idx < len(servers):
            self._smtp_dialog(existing=servers[idx], index=idx)

    def _smtp_delete(self):
        sel = self._smtp_tv.selection()
        if not sel:
            return
        idx = self._smtp_tv.index(sel[0])
        if messagebox.askyesno("Confirm", "Delete selected SMTP server?"):
            self.config_mgr.remove_smtp_server(idx)
            self.config_mgr.save()
            self._smtp_refresh_table()

    def _smtp_test_selected(self):
        sel = self._smtp_tv.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a server to test.")
            return
        idx = self._smtp_tv.index(sel[0])
        servers = self.config_mgr.get_smtp_servers()
        if idx >= len(servers):
            return
        srv_cfg = servers[idx]

        def _run():
            self._log("INFO", f"Testing {srv_cfg.get('smtp_server')}:{srv_cfg.get('port')} …")
            from core.smtp_pool import create_smtp_connection
            try:
                conn = create_smtp_connection(srv_cfg, timeout=10)
                if conn:
                    conn.quit()
                    self._log("INFO", f"✓ Connection to {srv_cfg.get('smtp_server')} successful")
                    self._gui_queue.put(("msg", "info", "SMTP Test OK",
                                         f"Connected to {srv_cfg.get('smtp_server')} successfully!"))
                else:
                    self._log("ERROR", f"✗ Failed to connect to {srv_cfg.get('smtp_server')}")
            except Exception as e:
                self._log("ERROR", f"✗ {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _smtp_import(self):
        path = filedialog.askopenfilename(
            title="Import SMTP Servers JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for srv in data:
                    self.config_mgr.add_smtp_server(srv)
            elif isinstance(data, dict) and "smtp_servers" in data:
                for srv in data["smtp_servers"]:
                    self.config_mgr.add_smtp_server(srv)
            self.config_mgr.save()
            self._smtp_refresh_table()
            self._log("INFO", f"Imported SMTP servers from {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def _smtp_dialog(self, existing: Optional[dict] = None, index: Optional[int] = None):
        """Add / Edit SMTP server dialog."""
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Add SMTP Server" if existing is None else "Edit SMTP Server")
        dlg.geometry("480x460")
        dlg.grab_set()
        dlg.configure(fg_color=CARD_BG)

        fields = {}
        field_defs = [
            ("smtp_server", "SMTP Host *", "smtp.example.com"),
            ("port", "Port *", "587"),
            ("username", "Username", "user@example.com"),
            ("password", "Password", ""),
            ("from_email", "From Email", "noreply@example.com"),
        ]
        for key, label, placeholder in field_defs:
            ctk.CTkLabel(dlg, text=label, font=FONT_SM,
                         text_color=TEXT_CLR).pack(anchor="w", padx=20, pady=(10, 2))
            var = tk.StringVar(value=(existing or {}).get(key, ""))
            show = "*" if key == "password" else ""
            ent = ctk.CTkEntry(dlg, textvariable=var, placeholder_text=placeholder,
                               show=show, width=440)
            ent.pack(padx=20)
            fields[key] = var

        enabled_var = tk.BooleanVar(value=(existing or {}).get("enabled", True))
        ctk.CTkSwitch(dlg, text="Enabled", variable=enabled_var).pack(
            anchor="w", padx=20, pady=10)

        def _save():
            srv = {k: v.get() for k, v in fields.items()}
            try:
                srv["port"] = int(srv["port"])
            except ValueError:
                messagebox.showerror("Error", "Port must be a number.")
                return
            if not srv.get("smtp_server"):
                messagebox.showerror("Error", "SMTP Host is required.")
                return
            srv["enabled"] = enabled_var.get()
            if index is not None:
                servers = self.config_mgr.get_smtp_servers()
                servers[index] = srv
                self.config_mgr.set_smtp_servers(servers)
            else:
                self.config_mgr.add_smtp_server(srv)
            self.config_mgr.save()
            self._smtp_refresh_table()
            dlg.destroy()

        ctk.CTkButton(dlg, text="Save", width=200, height=40,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=_save).pack(pady=16)

    # ------------------------------------------------------------------
    # Actions — Proxies
    # ------------------------------------------------------------------

    def _proxy_import_file(self):
        path = filedialog.askopenfilename(
            title="Select proxy file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self._proxy_add_from_text(text)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _proxy_import_text(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Paste Proxies")
        dlg.geometry("500x400")
        dlg.grab_set()
        dlg.configure(fg_color=CARD_BG)
        ctk.CTkLabel(dlg, text="Paste proxies (one per line):", font=FONT_SM,
                     text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(dlg, text="Formats: IP:PORT  |  IP:PORT:USER:PASS  |  socks5://user:pass@host:port",
                     font=("Consolas", 9), text_color=MUTED_CLR).pack(anchor="w", padx=16)
        txt = ctk.CTkTextbox(dlg, fg_color="#0d0d1a", text_color=TEXT_CLR, font=FONT_MONO)
        txt.pack(fill="both", expand=True, padx=16, pady=8)

        def _do():
            self._proxy_add_from_text(txt.get("1.0", "end"))
            dlg.destroy()

        ctk.CTkButton(dlg, text="Import", width=160, height=38,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=_do).pack(pady=8)

    def _proxy_add_from_text(self, text: str):
        default_type = self._proxy_type_var.get() if hasattr(self, "_proxy_type_var") else "socks5"
        entries = ProxyManager.parse_text(text, default_type=default_type)
        existing = {(p.get("host"), p.get("port")) for p in self.config_mgr.get_proxies()}
        added = 0
        for e in entries:
            if (e.host, e.port) not in existing:
                self.config_mgr.add_proxy(e.to_dict())
                existing.add((e.host, e.port))
                added += 1
        self.config_mgr.save()
        self._proxy_refresh_table()
        self._log("INFO", f"Imported {added} new proxies")

    def _proxy_validate_all(self):
        proxies_raw = self.config_mgr.get_proxies()
        if not proxies_raw:
            messagebox.showwarning("Warning", "No proxies to validate.")
            return

        from core.proxy_manager import ProxyEntry, validate_proxy
        entries = [ProxyEntry.from_dict(p) for p in proxies_raw]
        self._log("INFO", f"Validating {len(entries)} proxies …")

        def _run():
            def _cb(entry, lat):
                status = f"✓ {lat:.0f}ms" if lat >= 0 else "✗ dead"
                self._gui_queue.put(("proxy_result", entry.host, entry.port, lat, status))

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                list(ex.map(lambda e: _cb(e, validate_proxy(e)), entries))
            self._gui_queue.put(("proxy_refresh",))

        threading.Thread(target=_run, daemon=True).start()

    def _proxy_delete(self):
        sel = self._proxy_tv.selection()
        if not sel:
            return
        for item in reversed(self._proxy_tv.selection()):
            idx = self._proxy_tv.index(item)
            self.config_mgr.remove_proxy(idx)
        self.config_mgr.save()
        self._proxy_refresh_table()

    def _proxy_clear_all(self):
        if messagebox.askyesno("Confirm", "Remove all proxies?"):
            self.config_mgr.set_proxies([])
            self.config_mgr.save()
            self._proxy_refresh_table()

    def _proxy_refresh_table(self):
        for row in self._proxy_tv.get_children():
            self._proxy_tv.delete(row)
        proxies = self.config_mgr.get_proxies()
        for p in proxies:
            self._proxy_tv.insert("", "end", values=(
                p.get("host", ""), p.get("port", ""),
                p.get("type", "socks5"), "—", "—", 0, 0, "—",
            ))
        total = len(proxies)
        self._proxy_summary.configure(text=f"{total} proxies loaded")

    # ------------------------------------------------------------------
    # Actions — Settings
    # ------------------------------------------------------------------

    def _action_save_settings(self):
        cfg = {
            "num_threads": int(self._threads_var.get()),
            "max_retries": int(self._retries_var.get()),
            "max_errors_before_stop": int(self._max_errors_var.get()),
            "connection_timeout": int(self._timeout_var.get()),
            "max_reuse": int(self._max_reuse_var.get()),
            "max_age": int(self._max_age_var.get()),
            "max_conns_per_server": int(self._max_conns_var.get()),
            "use_exchange": self._use_exchange_var.get(),
            "smtp_rotation": self._smtp_rotation_var.get(),
            "use_sock": self._use_proxy_var.get(),
            "proxy_rotation": self._proxy_rotation_var.get(),
        }
        self.config_mgr.update(cfg)
        self.config_mgr.save()
        self._log("INFO", "Settings saved")

    def _edit_owa_json(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("OWA Accounts (JSON)")
        dlg.geometry("540x420")
        dlg.grab_set()
        dlg.configure(fg_color=CARD_BG)
        ctk.CTkLabel(dlg, text="OWA account list (JSON array):", font=FONT_SM,
                     text_color=TEXT_CLR).pack(anchor="w", padx=16, pady=(14, 4))
        txt = ctk.CTkTextbox(dlg, fg_color="#0d0d1a", text_color=TEXT_CLR, font=FONT_MONO)
        txt.pack(fill="both", expand=True, padx=16, pady=8)
        current = self.config_mgr.get("exchange", {}).get("owas", [])
        txt.insert("1.0", json.dumps(current, indent=2))

        def _save():
            try:
                data = json.loads(txt.get("1.0", "end"))
                exch = self.config_mgr.get("exchange", {})
                exch["owas"] = data
                self.config_mgr.set("exchange", exch)
                self.config_mgr.save()
                dlg.destroy()
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON Error", str(e))

        ctk.CTkButton(dlg, text="Save", width=160, height=38,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=_save).pack(pady=8)

    # ------------------------------------------------------------------
    # Actions — Logs
    # ------------------------------------------------------------------

    def _export_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if path:
            try:
                lines = [f"[{lvl}] {ts} {msg}" for lvl, ts, msg in self._log_entries]
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                self._log("INFO", f"Logs exported to {path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _clear_logs(self):
        self._log_entries.clear()
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        self._dash_log.configure(state="normal")
        self._dash_log.delete("1.0", "end")
        self._dash_log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Engine callbacks (called from worker threads → via gui_queue)
    # ------------------------------------------------------------------

    def _on_progress(self, sent: int, failed: int, total: int):
        self._gui_queue.put(("progress", sent, failed, total))

    def _on_log(self, level: str, msg: str):
        self._gui_queue.put(("log", level, msg))

    def _on_complete(self, sent: int, failed: int, total: int, elapsed: float):
        self._gui_queue.put(("complete", sent, failed, total, elapsed))

    # ------------------------------------------------------------------
    # GUI queue polling (main thread)
    # ------------------------------------------------------------------

    def _poll_gui_queue(self):
        try:
            while True:
                item = self._gui_queue.get_nowait()
                kind = item[0]

                if kind == "progress":
                    _, sent, failed, total = item
                    self._update_progress(sent, failed, total)

                elif kind == "log":
                    _, level, msg = item
                    self._append_log(level, msg)

                elif kind == "complete":
                    _, sent, failed, total, elapsed = item
                    self._on_complete_gui(sent, failed, total, elapsed)

                elif kind == "msg":
                    _, mtype, title, body = item
                    if mtype == "info":
                        messagebox.showinfo(title, body)
                    elif mtype == "error":
                        messagebox.showerror(title, body)

                elif kind == "proxy_result":
                    self._proxy_update_row(*item[1:])

                elif kind == "proxy_refresh":
                    self._proxy_refresh_table()

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_gui_queue)

        # Refresh SMTP pool table periodically
        if self.smtp_pool and hasattr(self, "_smtp_tv"):
            self._smtp_refresh_table()
            self._update_pool_table()

    def _update_progress(self, sent: int, failed: int, total: int):
        self._card_sent.set(str(sent))
        self._card_failed.set(str(failed))
        if total > 0:
            pct = (sent + failed) / total
            self._progress_bar.set(pct)
            self._pct_label.configure(text=f"{pct*100:.1f}%")

        stats = self.engine.get_stats()
        rate = stats.get("rate", 0)
        self._card_rate.set(f"{rate:.1f}")
        elapsed = stats.get("elapsed_s", 0)
        eta = stats.get("eta_s", 0)
        self._elapsed_lbl.configure(text=f"Elapsed: {self._fmt_time(elapsed)}")
        self._eta_lbl.configure(text=f"ETA: {self._fmt_time(eta)}")

    def _on_complete_gui(self, sent: int, failed: int, total: int, elapsed: float):
        self._btn_start.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸  Pause")
        self._btn_stop.configure(state="disabled")
        self._set_status("● Completed", SUCCESS_CLR)
        self._append_log("INFO",
            f"Campaign complete — {sent} sent, {failed} failed in {self._fmt_time(elapsed)}")
        messagebox.showinfo("Complete",
            f"Campaign finished!\n\nSent: {sent}\nFailed: {failed}\nDuration: {self._fmt_time(elapsed)}")

    def _append_log(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log_entries.append((level, ts, msg))

        filter_val = self._log_filter_var.get() if hasattr(self, "_log_filter_var") else "ALL"
        if filter_val != "ALL" and level != filter_val:
            return

        for widget in [self._log_text, self._dash_log]:
            widget.configure(state="normal")
            tb = widget._textbox
            tb.insert("end", ts + " ", ("TS",))
            tb.insert("end", f"[{level}] ", (level,))
            tb.insert("end", msg + "\n")
            tb.see("end")
            widget.configure(state="disabled")

    def _proxy_update_row(self, host, port, lat, status):
        for item in self._proxy_tv.get_children():
            vals = self._proxy_tv.item(item)["values"]
            if str(vals[0]) == host and str(vals[1]) == str(port):
                self._proxy_tv.set(item, "status", "alive" if lat >= 0 else "dead")
                self._proxy_tv.set(item, "latency", f"{lat:.0f}" if lat >= 0 else "—")
                break

    def _update_pool_table(self):
        if not self.smtp_pool:
            return
        stats = self.smtp_pool.get_stats()
        items = self._pool_tv.get_children()
        for row in items:
            self._pool_tv.delete(row)
        for s in stats["servers"]:
            self._pool_tv.insert("", "end", values=(
                s["host"], s["port"], s["status"],
                s["sent"], s["failed"],
                f"{s['success_rate']}%", f"{s['avg_latency_ms']}",
            ))

    # ------------------------------------------------------------------
    # Engine builder
    # ------------------------------------------------------------------

    def _build_engine(self) -> bool:
        """(Re)create SMTP pool and proxy manager from current config."""
        smtp_servers = self.config_mgr.get_smtp_servers()
        if not smtp_servers and not self.config_mgr.get("use_exchange", False):
            messagebox.showerror("Error", "No SMTP servers configured.\nGo to SMTP Servers tab.")
            return False

        # Proxy manager
        self.proxy_mgr = None
        if self.config_mgr.get("use_sock", False):
            proxies_raw = self.config_mgr.get_proxies()
            if not proxies_raw:
                messagebox.showerror("Error", "Proxy enabled but no proxies loaded.")
                return False
            self.proxy_mgr = ProxyManager(
                proxies_raw,
                rotation=self.config_mgr.get("proxy_rotation", "round_robin"),
            )

        # Shut down previous pool
        if self.smtp_pool:
            try:
                self.smtp_pool.shutdown()
            except Exception:
                pass

        self.smtp_pool = SmartSMTPPool(
            smtp_configs=smtp_servers,
            proxy_manager=self.proxy_mgr,
            rotation=self.config_mgr.get("smtp_rotation", "weighted"),
            max_conns_per_server=self.config_mgr.get("max_conns_per_server", 10),
            max_reuse=self.config_mgr.get("max_reuse", 200),
            max_age=self.config_mgr.get("max_age", 600),
            timeout=self.config_mgr.get("connection_timeout", 15),
        )

        links_file = self._links_var.get().strip() if hasattr(self, "_links_var") else ""
        links_list = []
        if links_file and os.path.exists(links_file):
            with open(links_file, "r", encoding="utf-8") as f:
                links_list = [ln.strip() for ln in f if ln.strip()]

        self._save_campaign_state()
        cfg = self.config_mgr.get_all()

        self.engine.configure(
            config=cfg,
            smtp_pool=self.smtp_pool,
            proxy_manager=self.proxy_mgr,
            links_list=links_list,
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, level: str, msg: str):
        self._gui_queue.put(("log", level, msg))

    def _set_status(self, text: str, color: str):
        self._status_dot.configure(text=text, text_color=color)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds <= 0:
            return "—"
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h:
            return f"{h}h {m:02d}m {s:02d}s"
        if m:
            return f"{m}m {s:02d}s"
        return f"{s}s"

    def _file_row(self, parent, label: str, var: tk.StringVar,
                  filetypes: str, dialog_title: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, font=FONT_SM,
                     text_color=MUTED_CLR, width=150, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=var, width=360).pack(side="left", padx=(0, 8))

        def _browse():
            pairs = [(t, t) for t in filetypes.split()]
            pairs.append(("All files", "*.*"))
            path = filedialog.askopenfilename(title=dialog_title, filetypes=pairs)
            if path:
                var.set(path)

        ctk.CTkButton(row, text="Browse", width=70, height=30,
                      fg_color=CARD_BG, border_width=1, border_color=BORDER_CLR,
                      text_color=TEXT_CLR, hover_color=BORDER_CLR,
                      command=_browse).pack(side="left")

    def _field_row(self, parent, label: str, var: tk.StringVar, show: str = ""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, font=FONT_SM,
                     text_color=MUTED_CLR, width=150, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=var, width=440, show=show).pack(side="left")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()
