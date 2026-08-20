"""AI Studio 디자인 시스템.

어두운 배경 + 보라/시안 그라디언트를 기본으로 하는 모던 다크 테마.
색상, 폰트, ttk 스타일 정의를 한곳에 모아두어 모든 화면이 같은 톤을 유지한다.
"""

from __future__ import annotations

from tkinter import font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------- 색상 팔레트
C = {
    "bg": "#070A12",          # 앱 전체 배경 (가장 어두움)
    "sidebar": "#0A0E1A",     # 좌측 내비게이션
    "surface": "#0F1421",     # 카드 배경
    "surface_alt": "#141A2A",  # 카드 안쪽 영역 / 리스트
    "surface_hi": "#1B2338",  # 입력창, 트랙
    "border": "#222C44",
    "border_hi": "#313D5C",
    "text": "#E9EEFA",
    "text_dim": "#98A5C0",
    "text_faint": "#65718F",
    "accent": "#7C6BFF",      # 그라디언트 시작 (보라)
    "accent_2": "#22D3EE",    # 그라디언트 끝 (시안)
    "accent_soft": "#1D2140",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
}

TONES = {
    "neutral": C["text_dim"],
    "ok": C["success"],
    "warn": C["warning"],
    "bad": C["danger"],
    "info": C["accent_2"],
}


def hex_to_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(c1: str, c2: str, t: float) -> str:
    """두 색을 t(0~1) 비율로 섞는다."""
    t = max(0.0, min(1.0, t))
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def lighten(color: str, amount: float) -> str:
    return mix(color, "#FFFFFF", amount)


# ------------------------------------------------------------------- 폰트
_UI_FAMILY = "TkDefaultFont"
_MONO_FAMILY = "TkFixedFont"
_FONT_CACHE: dict = {}

_UI_CANDIDATES = [
    "Malgun Gothic", "맑은 고딕", "Segoe UI Variable Text", "Segoe UI",
    "Noto Sans KR", "Noto Sans CJK KR", "Apple SD Gothic Neo", "DejaVu Sans",
]
_MONO_CANDIDATES = [
    "Cascadia Mono", "D2Coding", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New",
]


def _pick_family(candidates, fallback):
    available = {f.strip() for f in tkfont.families()}
    for name in candidates:
        if name in available:
            return name
    return fallback


def init_fonts(root):
    """루트 윈도우가 만들어진 뒤 한 번 호출한다."""
    global _UI_FAMILY, _MONO_FAMILY
    default = tkfont.nametofont("TkDefaultFont").actual("family")
    fixed = tkfont.nametofont("TkFixedFont").actual("family")
    _UI_FAMILY = _pick_family(_UI_CANDIDATES, default)
    _MONO_FAMILY = _pick_family(_MONO_CANDIDATES, fixed)
    _FONT_CACHE.clear()


def ui_font(size: int = 10, weight: str = "normal", slant: str = "roman"):
    key = ("ui", size, weight, slant)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = tkfont.Font(family=_UI_FAMILY, size=size, weight=weight, slant=slant)
    return _FONT_CACHE[key]


def mono_font(size: int = 9, weight: str = "normal"):
    key = ("mono", size, weight)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = tkfont.Font(family=_MONO_FAMILY, size=size, weight=weight)
    return _FONT_CACHE[key]


# --------------------------------------------------------------- ttk 스타일
def apply_theme(root):
    """ttk 위젯(입력창, 표, 스크롤바 등)에 다크 테마를 입힌다."""
    root.configure(bg=C["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=C["surface"])
    style.configure("TLabel", background=C["surface"], foreground=C["text"], font=ui_font(10))

    # 입력창
    style.configure(
        "AI.TEntry",
        fieldbackground=C["surface_hi"],
        foreground=C["text"],
        insertcolor=C["accent_2"],
        bordercolor=C["border"],
        lightcolor=C["border"],
        darkcolor=C["border"],
        borderwidth=1,
        relief="flat",
        padding=7,
    )
    style.map(
        "AI.TEntry",
        bordercolor=[("focus", C["accent"])],
        lightcolor=[("focus", C["accent"])],
        darkcolor=[("focus", C["accent"])],
        fieldbackground=[("disabled", C["surface_alt"])],
        foreground=[("disabled", C["text_faint"])],
    )

    # 숫자 입력
    style.configure(
        "AI.TSpinbox",
        fieldbackground=C["surface_hi"],
        background=C["surface_hi"],
        foreground=C["text"],
        insertcolor=C["accent_2"],
        bordercolor=C["border"],
        lightcolor=C["border"],
        darkcolor=C["border"],
        arrowcolor=C["text_dim"],
        borderwidth=1,
        relief="flat",
        padding=5,
    )
    style.map(
        "AI.TSpinbox",
        bordercolor=[("focus", C["accent"])],
        background=[("readonly", C["surface_hi"]), ("active", C["border"]),
                    ("disabled", C["surface_alt"])],
        fieldbackground=[("disabled", C["surface_alt"])],
        foreground=[("disabled", C["text_faint"])],
        arrowcolor=[("active", C["accent_2"]), ("disabled", C["text_faint"])],
    )

    # 콤보박스
    style.configure(
        "AI.TCombobox",
        fieldbackground=C["surface_hi"],
        background=C["surface_hi"],
        foreground=C["text"],
        arrowcolor=C["text_dim"],
        bordercolor=C["border"],
        lightcolor=C["border"],
        darkcolor=C["border"],
        borderwidth=1,
        relief="flat",
        padding=5,
    )
    style.map(
        "AI.TCombobox",
        fieldbackground=[("readonly", C["surface_hi"])],
        background=[("readonly", C["surface_hi"]), ("active", C["border"])],
        foreground=[("readonly", C["text"])],
        selectbackground=[("readonly", C["surface_hi"])],
        selectforeground=[("readonly", C["text"])],
        bordercolor=[("focus", C["accent"]), ("hover", C["border_hi"])],
        arrowcolor=[("active", C["accent_2"])],
    )
    # 콤보박스 화살표 버튼은 clam 기본 스타일에서 밝은 회색이라 기본 스타일까지 함께 덮어쓴다
    for element_style in ("TCombobox", "TSpinbox"):
        style.configure(element_style, background=C["surface_hi"], arrowcolor=C["text_dim"],
                        bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"])
        style.map(element_style,
                  background=[("readonly", C["surface_hi"]), ("active", C["border"])],
                  arrowcolor=[("active", C["accent_2"])])

    root.option_add("*TCombobox*Listbox.background", C["surface_hi"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # 표(Treeview)
    style.configure(
        "AI.Treeview",
        background=C["surface_alt"],
        fieldbackground=C["surface_alt"],
        foreground=C["text"],
        bordercolor=C["border"],
        borderwidth=0,
        rowheight=27,
        font=ui_font(9),
    )
    style.configure(
        "AI.Treeview.Heading",
        background=C["surface_hi"],
        foreground=C["text_dim"],
        relief="flat",
        borderwidth=0,
        padding=(8, 7),
        font=ui_font(9, "bold"),
    )
    style.map(
        "AI.Treeview",
        background=[("selected", C["accent_soft"])],
        foreground=[("selected", C["text"])],
    )
    style.map("AI.Treeview.Heading", background=[("active", C["border"])])
    style.layout("AI.Treeview", [("AI.Treeview.treearea", {"sticky": "nswe"})])

    # 스크롤바
    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"AI.{orient}.TScrollbar",
            background=C["border"],
            troughcolor=C["surface_alt"],
            bordercolor=C["surface_alt"],
            lightcolor=C["border"],
            darkcolor=C["border"],
            arrowcolor=C["text_faint"],
            relief="flat",
            borderwidth=0,
        )
        style.map(
            f"AI.{orient}.TScrollbar",
            background=[("active", C["border_hi"]), ("pressed", C["accent"]),
                        ("disabled", C["surface_hi"])],
            arrowcolor=[("disabled", C["surface_hi"])],
        )

    style.configure("AI.TSeparator", background=C["border"])
    return style
