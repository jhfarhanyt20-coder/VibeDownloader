"""VibeDownloader's own window frame: themed title bar, border and dialogs.

Windows' native caption is removed from every app window (overrideredirect)
and replaced by a title bar drawn in the app's theme colors. The window keeps
its taskbar button, can be dragged, minimized, maximized (to the monitor's
work area), resized from the edges and closed.

Message boxes (info / warning / error / yes-no / text input) are themed too;
`themed_messagebox` and `themed_simpledialog` are drop-in replacements for
tkinter.messagebox / tkinter.simpledialog.
"""

import os
import tkinter as tk
from tkinter import font as tkfont

# --------------------------------------------------------------------- theme
COLORS = {
    "bg": "#202327", "bar": "#25292D", "text": "#F2F2F2", "muted": "#A9AFB5",
    "border": "#4A4F55", "hover": "#3C4248", "button": "#30353A",
    "accent": "#6A3DF5", "accent2": "#00B8F0", "close_hover": "#C42B1C",
    "input": "#17191C", "sheen": "#2E3138",
}
ICON_PATH = ""
FONT = ("Segoe UI", 9)
BAR_HEIGHT = 32
GRIP = 6                      # resize zone thickness (px)

_icon_cache = {}


def configure(colors=None, icon_path=""):
    """Called once by the app with its palette and the .ico path."""
    global ICON_PATH
    COLORS.update(colors or {})
    if icon_path:
        ICON_PATH = icon_path


# ------------------------------------------------------------ win32 helpers
def _user32():
    import ctypes
    return ctypes.windll.user32


def _hwnd(win):
    return _user32().GetParent(win.winfo_id())


def _show_in_taskbar(win):
    """Give an overrideredirect window a taskbar button and Alt-Tab entry."""
    if os.name != "nt":
        return
    try:
        user32 = _user32()
        hwnd = _hwnd(win)
        gwl_exstyle, appwindow, toolwindow = -20, 0x00040000, 0x00000080
        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(hwnd, gwl_exstyle, (style & ~toolwindow) | appwindow)
        if getattr(win, "_vibe_can_minimize", True):
            # WS_MINIMIZEBOX | WS_SYSMENU without a caption: no Windows frame is
            # drawn, but the taskbar button minimizes / restores the window and
            # Win+Down works, like any normal app.
            gwl_style, minimizebox, sysmenu = -16, 0x00020000, 0x00080000
            base = user32.GetWindowLongW(hwnd, gwl_style)
            user32.SetWindowLongW(hwnd, gwl_style, base | minimizebox | sysmenu)
        win._vibe_round_key = None               # new/changed HWND: round it again
        _round_corners(win)
        if tk.Wm.wm_state(win) == "normal":
            # The taskbar only notices the new style when the window is re-shown.
            # Plain Tk calls on purpose: CustomTkinter's withdraw() override can
            # decide to keep a window hidden for good (an invisible window that
            # still holds the mouse grab freezes the whole app).
            tk.Wm.wm_withdraw(win)
            tk.Wm.wm_deiconify(win)
            _bring_to_front(win)
    except Exception:                            # noqa: BLE001
        pass


CORNER_RADIUS = 10


def _round_corners(win, _event=None):
    """Rounded window corners (square while maximized). Re-done on every resize."""
    if os.name != "nt":
        return
    try:
        width, height = win.winfo_width(), win.winfo_height()
        bar = getattr(win, "_vibe_title_bar", None)
        square = bar is not None and bar._maximized
        key = (width, height, square)
        if width < 20 or getattr(win, "_vibe_round_key", None) == key:
            return
        win._vibe_round_key = key
        import ctypes
        hwnd = _hwnd(win)
        if square:
            ctypes.windll.user32.SetWindowRgn(hwnd, None, True)
            return
        diameter = CORNER_RADIUS * 2
        region = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1,
                                                        diameter, diameter)
        # the window owns the region from now on - it must not be deleted here
        ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    except Exception:                            # noqa: BLE001
        pass


def _center_if_unplaced(win):
    """A window nobody positioned lands in the screen's top-left corner: center
    it over the window it belongs to (or the screen) instead."""
    try:
        if win.winfo_rootx() > 8 or win.winfo_rooty() > 8:
            return                               # the app placed it itself
        win.update_idletasks()
        width, height = win.winfo_width(), win.winfo_height()
        parent = win.master if isinstance(win.master, (tk.Tk, tk.Toplevel)) else None
        if parent is not None and parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
        else:
            x = (win.winfo_screenwidth() - width) // 2
            y = (win.winfo_screenheight() - 40 - height) // 2
        _set_geometry(win, f"+{max(0, x)}+{max(0, y)}")
    except tk.TclError:
        pass


def _bring_to_front(win):
    """A new window opens above the window it came from (never underneath)."""
    try:
        was_topmost = bool(win.attributes("-topmost"))
        win.lift()
        if not was_topmost:
            win.attributes("-topmost", True)
            win.after(400, lambda: _drop_topmost(win))
        win.focus_force()
    except tk.TclError:
        pass


def _drop_topmost(win):
    try:
        win.attributes("-topmost", False)
    except tk.TclError:
        pass


def _work_area(win):
    """(x, y, w, h) of the work area of the monitor the window is on."""
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = _user32()
        monitor = user32.MonitorFromWindow(_hwnd(win), 2)   # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:                            # noqa: BLE001
        pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def _set_geometry(win, text):
    # bypass CustomTkinter's DPI re-scaling: we always work in real pixels
    tk.Wm.wm_geometry(win, text)


def _icon_image(win, size=16):
    key = (str(win), size)
    if key in _icon_cache:
        return _icon_cache[key]
    image = None
    if ICON_PATH and os.path.isfile(ICON_PATH):
        try:
            from PIL import Image, ImageTk
            pil = Image.open(ICON_PATH).convert("RGBA")
            image = ImageTk.PhotoImage(pil.resize((size, size), Image.LANCZOS), master=win)
        except Exception:                        # noqa: BLE001
            image = None
    _icon_cache[key] = image
    return image


def _glyph_font():
    """Windows' own caption glyph font if present (crisp - and +), else Segoe UI."""
    try:
        families = set(tkfont.families())
    except Exception:                            # noqa: BLE001
        families = set()
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return (name, 8), {"min": "", "max": "", "restore": "",
                               "close": ""}
    return ("Segoe UI", 10), {"min": "—", "max": "□", "restore": "❐",
                              "close": "✕"}


# ------------------------------------------------------------------ title bar
class TitleBar(tk.Frame):
    def __init__(self, win, minimize=True, maximize=True, on_close=None):
        super().__init__(win, bg=COLORS["bar"], height=BAR_HEIGHT, highlightthickness=0)
        self.win = win
        self.on_close = on_close or win.destroy
        self._maximized = False
        self._normal_geometry = None
        self._drag = None
        self.pack_propagate(False)
        # 1 px highlight on the top edge: the glossy look of the bar
        tk.Frame(self, bg=COLORS.get("sheen", COLORS["border"]), height=1).place(
            relx=0, rely=0, relwidth=1.0)

        glyph_font, self._glyphs = _glyph_font()

        icon = _icon_image(win)
        self.icon = tk.Label(self, image=icon, bg=COLORS["bar"], bd=0) if icon else None
        if self.icon:
            self.icon.image = icon
            self.icon.pack(side="left", padx=(10, 6))
        self.title_label = tk.Label(self, text=win.wm_title(), bg=COLORS["bar"],
                                    fg=COLORS["text"], font=FONT, anchor="w")
        self.title_label.pack(side="left", fill="x", expand=True,
                              padx=(0 if self.icon else 12, 0))

        self.buttons = []
        self.close_btn = self._button(self._glyphs["close"], glyph_font, self._close,
                                      COLORS["close_hover"], "#FFFFFF")
        self.max_btn = None
        if maximize:
            self.max_btn = self._button(self._glyphs["max"], glyph_font, self.toggle_maximize)
        if minimize:
            self._button(self._glyphs["min"], glyph_font, self.minimize)

        # brand line under the bar
        self.accent = tk.Canvas(win, height=2, highlightthickness=0, bd=0, bg=COLORS["bar"])
        self.accent.bind("<Configure>", self._draw_accent)

        for widget in (self, self.title_label) + ((self.icon,) if self.icon else ()):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._move)
            widget.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None))
            if maximize:
                widget.bind("<Double-Button-1>", lambda _e: self.toggle_maximize())

        win.bind("<FocusIn>", lambda _e: self._set_active(True), add="+")
        # A frameless window that is minimized only gets *activated* by the first
        # taskbar click; restore it right then so one click is enough.
        win.bind("<FocusIn>", self._restore_if_minimized, add="+")
        win.bind("<FocusOut>", lambda _e: self._set_active(False), add="+")
        self._sync_title()

    # -------------------------------------------------------------- widgets
    def _button(self, text, glyph_font, command, hover_bg=None, hover_fg=None):
        btn = tk.Label(self, text=text, bg=COLORS["bar"], fg=COLORS["text"],
                       font=glyph_font, width=5, cursor="hand2")
        btn.pack(side="right", fill="y")
        hover_bg = hover_bg or COLORS["hover"]
        hover_fg = hover_fg or COLORS["text"]
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover_bg, fg=hover_fg))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=COLORS["bar"], fg=COLORS["text"]))
        btn.bind("<ButtonRelease-1>", lambda e: command()
                 if 0 <= e.x <= btn.winfo_width() and 0 <= e.y <= btn.winfo_height() else None)
        self.buttons.append(btn)
        return btn

    def _draw_accent(self, _event=None):
        canvas = self.accent
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        a = tuple(int(COLORS["accent"][i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(COLORS["accent2"][i:i + 2], 16) for i in (1, 3, 5))
        steps = 48
        for i in range(steps):
            t = i / (steps - 1)
            color = "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))
            x0 = int(width * i / steps)
            x1 = int(width * (i + 1) / steps) + 1
            canvas.create_rectangle(x0, 0, x1, 3, fill=color, width=0)

    def _restore_if_minimized(self, _event=None):
        win = self.win
        try:
            if tk.Wm.wm_state(win) == "iconic" and win.overrideredirect():
                if os.name == "nt":
                    _user32().ShowWindow(_hwnd(win), 9)    # SW_RESTORE
                else:
                    win.deiconify()
        except Exception:                        # noqa: BLE001
            pass

    def _set_active(self, active):
        try:
            self.title_label.configure(fg=COLORS["text"] if active else COLORS["muted"])
        except tk.TclError:
            pass

    def _sync_title(self):
        # windows set their own title (e.g. "37% file.zip") -> mirror it
        try:
            text = self.win.wm_title()
            if self.title_label.cget("text") != text:
                self.title_label.configure(text=text)
            self.after(400, self._sync_title)
        except tk.TclError:
            pass

    # -------------------------------------------------------------- actions
    def _close(self):
        self.on_close()

    def _start_move(self, event):
        self._drag = (event.x_root, event.y_root,
                      self.win.winfo_rootx(), self.win.winfo_rooty())

    def _move(self, event):
        if not self._drag:
            return
        if self._maximized:
            # drag a maximized window: restore it under the cursor, like Windows does
            ratio = event.x / max(1, self.winfo_width())
            self.toggle_maximize()
            self.win.update_idletasks()
            width = self.win.winfo_width()
            x = int(event.x_root - width * ratio)
            self._drag = (event.x_root, event.y_root, x, event.y_root - event.y)
        sx, sy, wx, wy = self._drag
        _set_geometry(self.win, f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

    def toggle_maximize(self):
        win = self.win
        if self._maximized:
            if self._normal_geometry:
                _set_geometry(win, self._normal_geometry)
            self._maximized = False
            if self.max_btn:
                self.max_btn.configure(text=self._glyphs["max"])
        else:
            self._normal_geometry = (f"{win.winfo_width()}x{win.winfo_height()}"
                                     f"+{win.winfo_rootx()}+{win.winfo_rooty()}")
            x, y, w, h = _work_area(win)
            _set_geometry(win, f"{w}x{h}+{x}+{y}")
            self._maximized = True
            if self.max_btn:
                self.max_btn.configure(text=self._glyphs["restore"])

    def minimize(self):
        win = self.win
        # Our window carries WS_MINIMIZEBOX (see _show_in_taskbar), so Windows
        # can minimize it directly - same as the taskbar button does.
        if os.name == "nt":
            try:
                _user32().ShowWindow(_hwnd(win), 6)        # SW_MINIMIZE
                return
            except Exception:                    # noqa: BLE001
                pass
        # Fallback: give the window a frame while it is minimized, take it away
        # again when it comes back. Windows parks minimized windows at -32000.
        self._before_minimize = tk.Wm.wm_geometry(win)
        win.overrideredirect(False)
        win.iconify()
        if not getattr(self, "_map_bound", False):
            win.bind("<Map>", self._restored, add="+")
            self._map_bound = True

    def _restored(self, event):
        win = self.win
        if event.widget is not win or win.state() != "normal":
            return
        if not win.overrideredirect():
            win.after(10, self._reapply_frame)

    def _reapply_frame(self):
        win = self.win
        try:
            win.overrideredirect(True)
            saved = getattr(self, "_before_minimize", None)
            if saved and "-32000" not in saved:
                _set_geometry(win, saved)
            _show_in_taskbar(win)
        except tk.TclError:
            pass


# --------------------------------------------------------------- resizing
def _add_resize_grips(win, bg):
    """Invisible 6 px zones on the right, bottom and bottom-right edges."""
    zones = (("e", dict(relx=1.0, rely=0, relheight=1.0, width=GRIP, anchor="ne"), "size_we"),
             ("s", dict(relx=0, rely=1.0, relwidth=1.0, height=GRIP, anchor="sw"), "size_ns"),
             ("se", dict(relx=1.0, rely=1.0, width=GRIP * 2, height=GRIP * 2, anchor="se"),
              "size_nw_se"))
    state = {}
    grips = []

    def press(event, edge):
        state.update(edge=edge, x=event.x_root, y=event.y_root,
                     w=win.winfo_width(), h=win.winfo_height())

    def motion(event):
        if not state:
            return
        min_w, min_h = win.wm_minsize()
        min_w, min_h = max(min_w, 320), max(min_h, 200)
        w, h = state["w"], state["h"]
        if "e" in state["edge"]:
            w = max(min_w, w + event.x_root - state["x"])
        if "s" in state["edge"]:
            h = max(min_h, h + event.y_root - state["y"])
        _set_geometry(win, f"{w}x{h}")

    for edge, place, cursor in zones:
        grip = tk.Frame(win, bg=bg, cursor=cursor, highlightthickness=0)
        grip.place(**place)
        grip.bind("<ButtonPress-1>", lambda e, edge=edge: press(e, edge))
        grip.bind("<B1-Motion>", motion)
        grip.bind("<ButtonRelease-1>", lambda _e: state.clear())
        grips.append(grip)

    def keep_on_top(_event=None):
        for grip in grips:
            try:
                grip.lift()
            except tk.TclError:
                pass
    win.bind("<Configure>", keep_on_top, add="+")
    win.after(300, keep_on_top)
    return grips


# ---------------------------------------------------------------- public API
def apply(win, minimize=True, maximize=None, resizable=None, on_close=None):
    """Replace the native caption of `win` with VibeDownloader's title bar.

    Call it right after creating the window, before packing its content, or
    later - the bar is always packed above everything else.
    """
    try:
        can_w, can_h = win.resizable()
    except tk.TclError:
        can_w = can_h = False
    if resizable is None:
        resizable = bool(can_w or can_h)
    if maximize is None:
        maximize = resizable

    win._vibe_can_minimize = bool(minimize)
    bar = TitleBar(win, minimize=minimize, maximize=maximize,
                   on_close=on_close or _close_handler(win))
    first = next(iter(win.pack_slaves()), None)
    if first is not None:
        bar.pack(side="top", fill="x", before=first)
        bar.accent.pack(side="top", fill="x", before=first)
    else:
        bar.pack(side="top", fill="x")
        bar.accent.pack(side="top", fill="x")

    try:
        win.configure(highlightthickness=1, highlightbackground=COLORS["border"],
                      highlightcolor=COLORS["border"])
    except tk.TclError:
        pass

    # A CustomTkinter window created with a fixed size ("760x470") would lose the
    # bar's height from its content: grow it by that much (CustomTkinter keeps the
    # requested size, unscaled, in _current_width/_current_height). Plain Tk
    # windows here are auto-sized and grow by themselves.
    cur_w = getattr(win, "_current_width", None)
    cur_h = getattr(win, "_current_height", None)
    if cur_w and cur_h and cur_h > 200:
        try:
            win.geometry(f"{int(cur_w)}x{int(cur_h) + BAR_HEIGHT + 4}")
        except tk.TclError:
            pass
    if resizable:
        try:
            bg = win.cget("bg")
        except tk.TclError:
            bg = COLORS["bg"]
        _add_resize_grips(win, bg)

    win.overrideredirect(True)
    win.after(30, lambda: _show_in_taskbar(win))
    win.after(60, lambda: _center_if_unplaced(win))
    win._vibe_title_bar = bar
    # rounded corners, kept up to date when the window is resized or maximized
    win.bind("<Configure>", lambda e: _round_corners(win) if e.widget is win else None, add="+")
    return bar


def _close_handler(win):
    """Whatever WM_DELETE_WINDOW does for this window (e.g. hide to tray)."""
    def close():
        try:
            command = win.tk.call("wm", "protocol", win._w, "WM_DELETE_WINDOW")
        except tk.TclError:
            command = ""
        if command:
            win.tk.eval(command)
        else:
            win.destroy()
    return close


# ------------------------------------------------------------- themed dialogs
def _dialog(parent, title, message, buttons, kind="info", entry=None):
    """Modal themed dialog. buttons: list of (label, value, is_default)."""
    parent = parent or tk._default_root
    top = tk.Toplevel(parent)
    top.withdraw()
    top.title(title)
    top.configure(bg=COLORS["bg"])
    top.resizable(False, False)
    try:
        if parent is not None and parent.winfo_viewable():
            top.transient(parent)
    except tk.TclError:
        pass
    result = {"value": buttons[-1][1] if buttons else None}

    def finish(value):
        if entry is not None and value is not None and value is not False:
            value = entry_var.get()
        result["value"] = value
        try:
            top.grab_release()
        except tk.TclError:
            pass
        top.destroy()

    cancel_value = None if entry is not None else (
        False if any(v is False for _l, v, _d in buttons) else buttons[-1][1])
    top.protocol("WM_DELETE_WINDOW", lambda: finish(cancel_value))
    apply(top, minimize=False, maximize=False, resizable=False,
          on_close=lambda: finish(cancel_value))

    body = tk.Frame(top, bg=COLORS["bg"])
    body.pack(fill="both", expand=True, padx=18, pady=(16, 8))
    badge_color = {"info": COLORS["accent2"], "warning": "#E4A11B",
                   "error": "#E46A61", "question": COLORS["accent"]}.get(kind, COLORS["accent2"])
    badge_text = {"info": "i", "warning": "!", "error": "✕", "question": "?"}.get(kind, "i")
    badge = tk.Canvas(body, width=34, height=34, bg=COLORS["bg"], highlightthickness=0)
    badge.create_oval(1, 1, 33, 33, fill=badge_color, width=0)
    badge.create_text(17, 17, text=badge_text, fill="#FFFFFF", font=("Segoe UI", 13, "bold"))
    badge.pack(side="left", anchor="n", padx=(0, 14))
    text_col = tk.Frame(body, bg=COLORS["bg"])
    text_col.pack(side="left", fill="both", expand=True)
    tk.Label(text_col, text=message, bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 10),
             justify="left", anchor="w", wraplength=380).pack(fill="x", anchor="w")

    entry_var = tk.StringVar(value=entry or "")
    field = None
    if entry is not None:
        field = tk.Entry(text_col, textvariable=entry_var, bg=COLORS["input"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 10),
                         highlightthickness=1, highlightbackground=COLORS["border"],
                         highlightcolor=COLORS["accent2"])
        field.pack(fill="x", pady=(10, 0), ipady=4)

    row = tk.Frame(top, bg=COLORS["bg"])
    row.pack(fill="x", padx=18, pady=(4, 16))
    default_value = None
    for label, value, is_default in reversed(buttons):
        bg = COLORS["accent"] if is_default else COLORS["button"]
        hover = COLORS["accent2"] if is_default else COLORS["hover"]
        btn = tk.Label(row, text=label, bg=bg, fg="#FFFFFF" if is_default else COLORS["text"],
                       font=("Segoe UI", 9), padx=16, pady=5, cursor="hand2")
        btn.pack(side="right", padx=(8, 0))
        btn.bind("<Enter>", lambda _e, b=btn, h=hover: b.configure(bg=h))
        btn.bind("<Leave>", lambda _e, b=btn, c=bg: b.configure(bg=c))
        btn.bind("<ButtonRelease-1>", lambda _e, v=value: finish(v))
        if is_default:
            default_value = value
    top.bind("<Return>", lambda _e: finish(default_value))
    top.bind("<Escape>", lambda _e: finish(cancel_value))

    top.update_idletasks()
    w, h = max(top.winfo_reqwidth(), 360), top.winfo_reqheight()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if not parent.winfo_viewable() or pw < 50:
            raise tk.TclError
        x, y = px + (pw - w) // 2, py + (ph - h) // 3
    except (tk.TclError, AttributeError):
        x, y = (top.winfo_screenwidth() - w) // 2, (top.winfo_screenheight() - h) // 3
    _set_geometry(top, f"{w}x{h}+{max(0, x)}+{max(0, y)}")
    top.deiconify()
    top.attributes("-topmost", True)
    top.lift()
    try:
        top.grab_set()
    except tk.TclError:
        pass
    (field or top).focus_force()
    top.wait_window()
    return result["value"]


class themed_messagebox:                         # noqa: N801 - mirrors tkinter's module
    @staticmethod
    def showinfo(title=None, message=None, parent=None, **_kw):
        _dialog(parent, title or "", message or "", [("OK", "ok", True)], "info")
        return "ok"

    @staticmethod
    def showwarning(title=None, message=None, parent=None, **_kw):
        _dialog(parent, title or "", message or "", [("OK", "ok", True)], "warning")
        return "ok"

    @staticmethod
    def showerror(title=None, message=None, parent=None, **_kw):
        _dialog(parent, title or "", message or "", [("OK", "ok", True)], "error")
        return "ok"

    @staticmethod
    def askyesno(title=None, message=None, parent=None, **_kw):
        return bool(_dialog(parent, title or "", message or "",
                            [("Yes", True, True), ("No", False, False)], "question"))

    @staticmethod
    def askokcancel(title=None, message=None, parent=None, **_kw):
        return bool(_dialog(parent, title or "", message or "",
                            [("OK", True, True), ("Cancel", False, False)], "question"))


class themed_simpledialog:                       # noqa: N801
    @staticmethod
    def askstring(title=None, prompt=None, parent=None, initialvalue="", **_kw):
        value = _dialog(parent, title or "", prompt or "",
                        [("OK", "ok", True), ("Cancel", None, False)], "question",
                        entry=initialvalue or "")
        return value if isinstance(value, str) else None
