"""
FinPlus+ Native Desktop HUD Floater
===================================
Module: finplus_index_breadth.desktop_floater.finplus_floater
Author: FinPlus+ Enterprise Infrastructure
Standard: Always-On-Top, Draggable, Frameless, Zero Laptop Server Needed

Presents the core market decision indicators:
1. Overall Market Trend (Strong Uptrend / Choppy / Downtrend)
2. Equities Directive (Buy / Sit Cash / Short)
3. Options Directive (Buy Calls / Do Not Buy Options / Buy Puts)
4. All-NSE 2,266 Breadth & 3:10 PM BTST Radar
"""

import sys
import time
import threading
import tkinter as tk
from tkinter import ttk
import requests

CLOUD_API_URL = "http://127.0.0.1:8000"


class FinPlusFloater(tk.Tk):
    def __init__(self, api_url=CLOUD_API_URL):
        super().__init__()
        self.api_url = api_url.rstrip("/")
        
        # Frameless & Always On Top
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.94)
        
        # Dimensions & Position (Top Right Corner)
        w, h = 360, 95
        sw = self.winfo_screenwidth()
        x = sw - w - 24
        y = 24
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#070b12")
        
        # Dragging Bindings
        self._offset_x = 0
        self._offset_y = 0
        self.bind("<Button-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Button-3>", self._show_context_menu)
        
        self._build_ui()
        
        # Start Background Poller
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _start_drag(self, event):
        self._offset_x = event.x
        self._offset_y = event.y

    def _on_drag(self, event):
        x = self.winfo_pointerx() - self._offset_x
        y = self.winfo_pointery() - self._offset_y
        self.geometry(f"+{x}+{y}")

    def _show_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0, bg="#1e293b", fg="#e2e8f0", activebackground="#334155")
        menu.add_command(label="Close Floater", command=self.destroy)
        menu.post(event.x_root, event.y_root)

    def _build_ui(self):
        self.border_frame = tk.Frame(self, bg="#1e293b", padx=1, pady=1)
        self.border_frame.pack(fill="both", expand=True)
        
        self.inner_frame = tk.Frame(self.border_frame, bg="#070b12", padx=8, pady=4)
        self.inner_frame.pack(fill="both", expand=True)

        # Top Bar: Brand & Clock
        top_bar = tk.Frame(self.inner_frame, bg="#070b12")
        top_bar.pack(fill="x")
        
        self.brand_lbl = tk.Label(top_bar, text="⨁ FinPlus+ Intraday HUD", font=("Segoe UI", 9, "bold"), fg="#10b981", bg="#070b12")
        self.brand_lbl.pack(side="left")
        
        self.clock_lbl = tk.Label(top_bar, text="--:--:--", font=("Consolas", 8), fg="#64748b", bg="#070b12")
        self.clock_lbl.pack(side="right")
        
        # Mid Bar: 3 Decision Cards (Trend, Equities, Options)
        mid_bar = tk.Frame(self.inner_frame, bg="#070b12")
        mid_bar.pack(fill="x", pady=3)
        
        # Card 1: Trend
        f_trend = tk.Frame(mid_bar, bg="#0f172a", padx=4, pady=2, highlightbackground="#1e293b", highlightthickness=1)
        f_trend.pack(side="left", fill="both", expand=True, padx=1)
        tk.Label(f_trend, text="TREND", font=("Segoe UI", 7, "bold"), fg="#64748b", bg="#0f172a").pack()
        self.trend_lbl = tk.Label(f_trend, text="CHOPPY", font=("Consolas", 8, "bold"), fg="#f59e0b", bg="#0f172a")
        self.trend_lbl.pack()

        # Card 2: Equities
        f_eq = tk.Frame(mid_bar, bg="#0f172a", padx=4, pady=2, highlightbackground="#1e293b", highlightthickness=1)
        f_eq.pack(side="left", fill="both", expand=True, padx=1)
        tk.Label(f_eq, text="EQUITIES", font=("Segoe UI", 7, "bold"), fg="#64748b", bg="#0f172a").pack()
        self.eq_lbl = tk.Label(f_eq, text="AVOID BUYS", font=("Consolas", 8, "bold"), fg="#f59e0b", bg="#0f172a")
        self.eq_lbl.pack()

        # Card 3: Options
        f_opt = tk.Frame(mid_bar, bg="#0f172a", padx=4, pady=2, highlightbackground="#1e293b", highlightthickness=1)
        f_opt.pack(side="left", fill="both", expand=True, padx=1)
        tk.Label(f_opt, text="OPTIONS", font=("Segoe UI", 7, "bold"), fg="#64748b", bg="#0f172a").pack()
        self.opt_lbl = tk.Label(f_opt, text="NO OPTIONS", font=("Consolas", 8, "bold"), fg="#f43f5e", bg="#0f172a")
        self.opt_lbl.pack()
        
        # Bottom Bar: Breadth & BTST Status Pill
        self.footer_frame = tk.Frame(self.inner_frame, bg="#451a03", padx=4, pady=2)
        self.footer_frame.pack(fill="x", pady=1)
        
        self.footer_lbl = tk.Label(
            self.footer_frame,
            text="NSE: ADR 0.50 : 1 • 3:10 PM BTST: HOLD CASH",
            font=("Consolas", 8, "bold"),
            fg="#fde68a",
            bg="#451a03"
        )
        self.footer_lbl.pack(fill="x")

    def _poll_loop(self):
        while self._running:
            try:
                b_resp = requests.get(f"{self.api_url}/api/breadth", timeout=4)
                if b_resp.status_code == 200:
                    data = b_resp.json()
                    regime = data.get("market_regime", {})
                    bm = data.get("broad_market", {}).get("broad_market", {})
                    self.after(0, self._update_ui_data, regime, bm)
            except Exception:
                self.after(0, self._update_error_ui)

            time.sleep(3)

    def _update_ui_data(self, regime, bm):
        self.clock_lbl.config(text=time.strftime("%H:%M:%S"))
        
        trend = regime.get("trend", {})
        eq_dir = regime.get("equities_directive", {})
        opt_dir = regime.get("options_directive", {})
        
        # 1. Trend
        t_label = trend.get("label", "CHOPPY").split(" ")[0]
        t_color = "#10b981" if trend.get("color") == "emerald" else ("#f43f5e" if trend.get("color") == "rose" else "#f59e0b")
        self.trend_lbl.config(text=t_label, fg=t_color)
        
        # 2. Equities
        eq_badge = eq_dir.get("badge", "SIT CASH")
        eq_color = "#10b981" if eq_dir.get("color") == "emerald" else ("#f43f5e" if eq_dir.get("color") == "rose" else "#f59e0b")
        self.eq_lbl.config(text=eq_badge, fg=eq_color)
        
        # 3. Options
        opt_badge = opt_dir.get("badge", "NO OPTIONS")
        if "DO NOT" in opt_badge:
            opt_badge = "NO OPTIONS"
        opt_color = "#10b981" if opt_dir.get("color") == "emerald" else ("#f43f5e" if opt_dir.get("color") == "rose" else "#f59e0b")
        self.opt_lbl.config(text=opt_badge, fg=opt_color)
        
        # 4. Footer Pill
        adr = bm.get("advance_decline_ratio", 0.50)
        if trend.get("color") == "emerald":
            self.footer_frame.config(bg="#064e3b")
            self.footer_lbl.config(text=f"NSE: ADR {adr}:1 (BULLISH) • BTST: WATCH CALLS", fg="#a7f3d0", bg="#064e3b")
        elif trend.get("color") == "rose":
            self.footer_frame.config(bg="#4c0519")
            self.footer_lbl.config(text=f"NSE: ADR {adr}:1 (BEARISH) • BTST: HOLD CASH", fg="#fecdd3", bg="#4c0519")
        else:
            self.footer_frame.config(bg="#451a03")
            self.footer_lbl.config(text=f"NSE: ADR {adr}:1 (DIVERGENT) • BTST: HOLD CASH", fg="#fde68a", bg="#451a03")

    def _update_error_ui(self):
        self.clock_lbl.config(text=time.strftime("%H:%M:%S"))
        self.footer_lbl.config(text="RECONNECTING CLOUD...", fg="#f59e0b")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else CLOUD_API_URL
    app = FinPlusFloater(api_url=url)
    app.mainloop()
