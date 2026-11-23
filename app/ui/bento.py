"""Building blocks for the bento layout: tiles on a grid. Pure layout, no behaviour.

    grid = page_grid(widget)                          # the page's grid, with the app's margins and gaps
    grid.addWidget(header("Find a tutorial", back=self.back_button), 0, 0, 1, 3)
    box = Tile("Results", variant="soft"); box.body.addWidget(...); grid.addWidget(box, 1, 0)

A `Tile` is a rounded box with an optional heading; `ActionTile` is a whole tile that is also a button. Colours live in app/ui/style.py.
"""
from __future__ import annotations

import weakref

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .style import current_palette

GAP = 14
MARGIN = 20


def page_grid(widget: QWidget) -> QGridLayout:
    """Give a screen the app's canvas and a grid with even gaps. Columns and rows share space equally unless the screen says otherwise."""
    widget.setObjectName("page")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    grid = QGridLayout(widget)
    grid.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    grid.setSpacing(GAP)
    return grid


_SHADOWS: "weakref.WeakSet[QGraphicsDropShadowEffect]" = weakref.WeakSet()      # every soft shadow made, so a theme change can recolour them without searching the widgets


def recolour_shadows() -> None:
    """After a theme change: the soft shadows are not in the style sheet, so give each its new colour."""
    colour = QColor(current_palette()["shadow"])
    for fx in list(_SHADOWS):
        try:
            fx.setColor(colour)
        except RuntimeError:                                   # its widget is already gone
            pass


def soft_shadow(widget: QWidget, blur: int = 32, dy: int = 10, dx: int = 6) -> QGraphicsDropShadowEffect:
    """The soft outer shadow of a clay shape (a style sheet cannot draw one). Warm brown, offset to the bottom right."""
    fx = QGraphicsDropShadowEffect(widget)
    _SHADOWS.add(fx)
    fx.setBlurRadius(blur)
    fx.setOffset(dx, dy)
    fx.setColor(QColor(current_palette()["shadow"]))
    widget.setGraphicsEffect(fx)
    return fx


class Lift(QObject):
    """Hover animation: the shadow grows and moves away, so the shape looks as if it rises from the page. Only the shadow animates, so layouts never jump."""

    def __init__(self, widget: QWidget, fx: QGraphicsDropShadowEffect, grow: int = 16):
        super().__init__(widget)
        self.fx = fx
        self.rest = (fx.blurRadius(), fx.yOffset())
        self.grow = grow
        self.anims = [QPropertyAnimation(fx, b"blurRadius", self), QPropertyAnimation(fx, b"yOffset", self)]
        for a in self.anims:
            a.setDuration(180)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        t = event.type()
        if t == QEvent.Type.Enter:
            self._go(self.rest[0] + self.grow, self.rest[1] + self.grow // 2)
        elif t in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._go(*self.rest)
        return False

    def _go(self, blur: float, dy: float) -> None:
        for a, end in zip(self.anims, (blur, dy)):
            a.stop()
            a.setEndValue(end)
            a.start()


def raise_on_hover(widget: QWidget, blur: int = 30, dy: int = 9) -> None:
    """A clay shape: a soft shadow that grows when the pointer is over it."""
    Lift(widget, soft_shadow(widget, blur, dy))


class Tile(QFrame):
    """A rounded box. `body` is the vertical layout to put content in. `variant` is one of: "", soft, mint, amber, slate, accent, hero (a calm tinted fill with an accent outline)."""

    def __init__(self, title: str | None = None, hint: str | None = None, variant: str = "", padding: int = 18, shadow: bool = True):
        """`shadow=False` for a tile that holds a web view: Qt WebEngine cannot be drawn through a graphics effect (it crashes the application)."""
        super().__init__()
        self.setObjectName("tile")
        self.setProperty("variant", variant)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(10)
        self.title_label: QLabel | None = None
        if shadow:
            soft_shadow(self, 28, 8)
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("tileTitle")
            self.body.addWidget(self.title_label)
        if hint:
            h = QLabel(hint)
            h.setObjectName("tileHint")
            h.setWordWrap(True)
            self.body.addWidget(h)


class ActionTile(QPushButton):
    """A tile you click. Keeps the title as the button's text (for accessibility and tests) but paints its own two labels."""

    def __init__(self, title: str, hint: str = "", variant: str = "", min_height: int = 92, bottom: bool = False):
        super().__init__(title)
        self.setObjectName("action")
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        raise_on_hover(self, 24, 7)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("tileTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("tileHint")
        self.hint_label.setWordWrap(True)
        for lab in (self.title_label, self.hint_label):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)      # clicks go to the button underneath
        if bottom:
            box.addStretch()                      # tall tiles read better with their text sitting at the bottom
        box.addWidget(self.title_label)
        box.addWidget(self.hint_label)
        if not bottom:
            box.addStretch()

    def set_texts(self, title: str, hint: str) -> None:
        self.setText(title)
        self.title_label.setText(title)
        self.hint_label.setText(hint)


_MOVING: "weakref.WeakSet" = weakref.WeakSet()      # every widget with a drifting animation (the hero tiles and the window's backdrop)
_calm = False


def set_calm(on: bool) -> None:
    """Calm mode: nothing drifts. On while GuideWire watches another application (every repaint of the window is CPU that application could use)."""
    global _calm
    _calm = on
    for w in list(_MOVING):
        try:
            w.sync_animation()
        except RuntimeError:                              # the widget is already gone
            pass


def is_calm() -> bool:
    return _calm


def should_move(widget: QWidget) -> bool:
    return not _calm and widget.isVisible() and QApplication.applicationState() == Qt.ApplicationState.ApplicationActive


MIN_STEP = 0.05                                       # radians: the smallest change of a drifting animation that is worth a repaint


class HeroTile(Tile):
    """The one big slab on a screen (variant "hero"): amber clay with soft balls floating in it and, if given, a huge faint word or number behind the text."""

    def __init__(self, title: str | None = None, hint: str | None = None, padding: int = 24):
        super().__init__(title, hint, variant="hero", padding=padding)
        self.watermark = ""
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(6.2832)
        self._anim.setDuration(9000)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        QApplication.instance().applicationStateChanged.connect(self._app_state)
        _MOVING.add(self)

    def _tick(self, value) -> None:
        value = float(value)
        if abs(value - self._phase) >= MIN_STEP:          # a slow drift needs no more than about ten repaints a second
            self._phase = value
            self.update()

    def sync_animation(self) -> None:
        """Run only when it can be seen and costs nothing that matters: visible, GuideWire in use, and not in calm mode."""
        running = self._anim.state() == self._anim.State.Running
        if should_move(self) and not running:
            self._anim.start()
        elif not should_move(self) and running:
            self._anim.stop()

    def _app_state(self, _state) -> None:
        self.sync_animation()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._anim.start()
        super().showEvent(event)
        if is_calm():
            self._anim.stop()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._anim.stop()
        super().hideEvent(event)

    def set_watermark(self, text: str) -> None:
        self.watermark = text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        import math
        pal = current_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 32, 32)
        p.setClipPath(clip)
        w, h = self.width(), self.height()
        if self.watermark:
            f = p.font()
            f.setPixelSize(int(h * 0.9))
            f.setWeight(f.Weight.Black)
            p.setFont(f)
            c = QColor(pal["hi"])
            c.setAlpha(70)
            p.setPen(c)
            p.drawText(QRectF(0, h * 0.22, w - 18, h), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), self.watermark)
        wob = math.sin(self._phase) * 8
        for cx, cy, r, hi, lo in ((w - 40, 22 + wob, 62, pal["teal_hi"], pal["teal"]), (w * 0.55, h - 6 - wob, 30, pal["accent_hi"], pal["accent"])):
            g = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.35), r * 1.3)
            g.setColorAt(0, QColor(hi))
            g.setColorAt(1, QColor(lo))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


class ClayBall(QWidget):
    """A round icon moulded like a clay ball, with a simple white symbol: search, chat, plus, star or clock."""
    COLOURS = {"search": ("teal_hi", "teal"), "chat": ("hero_hi", "hero"), "plus": ("accent_hi", "accent"), "star": ("#e6d9ff", "#a98af0"), "clock": ("tile_hi", "hero_lo")}

    def __init__(self, kind: str, size: int = 34):
        super().__init__()
        self.kind = kind
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        import math
        pal = current_palette()
        hi, lo = (pal.get(c, c) for c in self.COLOURS.get(self.kind, self.COLOURS["search"]))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        g = QRadialGradient(QPointF(s * 0.35, s * 0.3), s * 0.85)
        g.setColorAt(0, QColor(hi))
        g.setColorAt(1, QColor(lo))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(2, 2, s - 4, s - 4))
        pen = QPen(QColor("#ffffff"), s * 0.075, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        u = s / 10.0
        path = QPainterPath()
        if self.kind == "search":
            path.addEllipse(QPointF(4.4 * u, 4.4 * u), 2.2 * u, 2.2 * u)
            path.moveTo(6.1 * u, 6.1 * u)
            path.lineTo(7.8 * u, 7.8 * u)
        elif self.kind == "chat":
            path.addRoundedRect(QRectF(2.2 * u, 2.6 * u, 5.6 * u, 4 * u), u, u)
            path.moveTo(3.8 * u, 6.6 * u)
            path.lineTo(3.4 * u, 8 * u)
            path.lineTo(5 * u, 6.6 * u)
        elif self.kind == "plus":
            path.moveTo(5 * u, 2.6 * u)
            path.lineTo(5 * u, 7.4 * u)
            path.moveTo(2.6 * u, 5 * u)
            path.lineTo(7.4 * u, 5 * u)
        elif self.kind == "clock":
            path.addEllipse(QPointF(5 * u, 5 * u), 2.8 * u, 2.8 * u)
            path.moveTo(5 * u, 3.4 * u)
            path.lineTo(5 * u, 5 * u)
            path.lineTo(6.2 * u, 5.8 * u)
        else:
            pts = [QPointF(5 * u + (3 * u if i % 2 == 0 else 1.3 * u) * math.sin(i * math.pi / 5), 5.2 * u - (3 * u if i % 2 == 0 else 1.3 * u) * math.cos(i * math.pi / 5)) for i in range(10)]
            path.moveTo(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            path.closeSubpath()
        p.drawPath(path)
        p.end()


class IconTile(ActionTile):
    """An action tile with a round clay icon above its title: the big, friendly buttons on Home."""

    def __init__(self, title: str, hint: str, kind: str, min_height: int = 112):
        super().__init__(title, hint, "", min_height=min_height)
        box = self.layout()
        box.setContentsMargins(26, 18, 22, 16)                 # roomy sideways: about 8 px more padding than a plain action tile
        self.title_label.setWordWrap(True)                  # long titles wrap instead of being cut off
        self.ball = ClayBall(kind)
        box.insertWidget(0, self.ball, 0, Qt.AlignmentFlag.AlignLeft)
        box.insertSpacing(1, 10)


def pill(text: str) -> QLabel:
    """A small rounded label ("Blender", "Step 3 of 18")."""
    lab = QLabel(text)
    lab.setObjectName("pill")
    lab.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lab


def tidy_list(lst) -> None:
    """A list that never scrolls sideways: long lines are trimmed with an ellipsis (the full text is the item's tooltip)."""
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lst.setTextElideMode(Qt.TextElideMode.ElideRight)
    lst.setWordWrap(False)


class Head(QWidget):
    """A page's top strip: no box, just a small label, a big title and the buttons on the right (the same look as the Home screen's greeting). `body` is its layout."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(6, 2, 6, 2)
        self.body.setSpacing(0)


def header(title: str, subtitle: str = "", back: QPushButton | None = None, extra: QWidget | None = None, kicker: str = "GuideWire") -> Head:
    """The page's top strip: a small label, the title and a one-line hint, with the Back button and anything else on the right."""
    head = Head()
    row = QHBoxLayout()
    texts = QVBoxLayout()
    texts.setSpacing(0)
    k = QLabel(kicker)
    k.setObjectName("kicker")
    texts.addWidget(k)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    texts.addWidget(t)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("tileHint")
        sub.setWordWrap(True)
        texts.addWidget(sub)
    row.addLayout(texts, 1)
    if extra is not None:
        row.addWidget(extra)
    if back is not None:
        row.addWidget(back, 0, Qt.AlignmentFlag.AlignVCenter)
    head.body.addLayout(row)
    head.page_title = t                       # type: ignore[attr-defined]
    return head
