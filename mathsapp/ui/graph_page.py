"""Vue graphe : le cursus comme un graphe de prerequis."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import status as st_mod
from ..status import AVAILABLE, LOCKED, MASTERED, READY, STARTED, Status
from ..syllabus import Syllabus
from . import theme

NODE_W, NODE_H = 168.0, 46.0
COL_GAP, ROW_GAP = 224.0, 20.0

STATE_STYLE = {
    MASTERED: ("ok_soft", "ok", "fg"),
    STARTED: ("warn_soft", "warn", "fg"),
    READY: ("bg2", "line2", "fg"),
    AVAILABLE: ("accent_soft", "accent", "accent"),
    LOCKED: ("bg2", "line", "locked"),
}


class Node(QGraphicsItem):
    def __init__(self, course_id: str, title: str, domain_color: str, state: str):
        super().__init__()
        self.course_id = course_id
        self.title = title
        self.domain_color = domain_color
        self.state = state
        self.dimmed = False
        self.highlighted = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(2)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, NODE_W, NODE_H)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:  # noqa: N802
        pal = theme.palette()
        bg_key, border_key, fg_key = STATE_STYLE[self.state]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        alpha = 60 if self.dimmed else 255

        bg = QColor(pal[bg_key])
        border = QColor(pal[border_key])
        fg = QColor(pal[fg_key])
        for col in (bg, border, fg):
            col.setAlpha(alpha)

        rect = QRectF(0, 0, NODE_W, NODE_H)
        painter.setBrush(QBrush(bg))
        pen = QPen(border, 2.4 if (self.highlighted or self.isSelected()) else 1.2)
        if self.isSelected():
            pen = QPen(QColor(pal["accent"]), 2.6)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 8, 8)

        stripe = QColor(self.domain_color)
        stripe.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(stripe)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 10, NODE_H), 8, 8)
        path.addRect(QRectF(5, 0, 5, NODE_H))
        painter.drawPath(path)

        painter.setPen(QPen(fg))
        font = QFont()
        font.setPointSizeF(8.6)
        font.setBold(self.state == MASTERED)
        painter.setFont(font)
        painter.drawText(QRectF(16, 4, NODE_W - 22, NODE_H - 8),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                             | Qt.TextFlag.TextWordWrap),
                         self.title)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        scene = self.scene()
        if isinstance(scene, GraphScene):
            scene.focus_on(self.course_id)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        scene = self.scene()
        if isinstance(scene, GraphScene):
            scene.focus_on(None)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        scene = self.scene()
        if isinstance(scene, GraphScene):
            scene.node_activated.emit(self.course_id)
        super().mouseDoubleClickEvent(event)


class GraphScene(QGraphicsScene):
    node_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes: Dict[str, Node] = {}
        self.edges: List[tuple] = []   # (item, source_id, target_id)
        self.syl: Optional[Syllabus] = None

    def focus_on(self, course_id: Optional[str]) -> None:
        if course_id is None or self.syl is None:
            for node in self.nodes.values():
                node.dimmed = False
                node.highlighted = False
                node.update()
            for item, _s, _t in self.edges:
                item.setOpacity(1.0)
            return
        related: Set[str] = {course_id}
        related.update(self.syl.ancestors(course_id))
        related.update(self.syl.descendants(course_id))
        for cid, node in self.nodes.items():
            node.dimmed = cid not in related
            node.highlighted = cid == course_id
            node.update()
        for item, source, target in self.edges:
            item.setOpacity(1.0 if (source in related and target in related) else 0.12)


class GraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self._zoom = 1.0

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.0015 ** event.angleDelta().y()
        target = self._zoom * factor
        if 0.12 < target < 3.2:
            self._zoom = target
            self.scale(factor, factor)


class GraphPage(QWidget):
    course_opened = Signal(str)
    generate_requested = Signal(list)

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.statuses: Dict[str, Status] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 9, 14, 9)
        bl.setSpacing(9)

        self.f_scope = QComboBox()
        self.f_scope.addItem("Tout le syllabus", ("all", None))
        for tid, track in self.syl.tracks.items():
            self.f_scope.addItem("Parcours : %s" % track.title, ("track", tid))
        for did in self.syl.domain_order:
            self.f_scope.addItem("Domaine : %s" % self.syl.domain_name(did), ("domain", did))
        self.f_scope.currentIndexChanged.connect(self.rebuild)
        bl.addWidget(self.f_scope)

        self.hide_locked = QCheckBox("Masquer les cours verrouilles")
        self.hide_locked.stateChanged.connect(self.rebuild)
        bl.addWidget(self.hide_locked)

        btn_fit = QPushButton("Ajuster")
        btn_fit.setProperty("flat", True)
        btn_fit.clicked.connect(self.fit)
        bl.addWidget(btn_fit)

        self.btn_gen = QPushButton("Generer ce qui est accessible")
        self.btn_gen.setProperty("flat", True)
        self.btn_gen.clicked.connect(self._generate_available)
        bl.addWidget(self.btn_gen)

        bl.addStretch(1)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        bl.addWidget(self.legend)
        root.addWidget(bar)

        self.scene = GraphScene(self)
        self.scene.syl = self.syl
        self.scene.node_activated.connect(self.course_opened.emit)
        self.view = GraphView(self.scene, self)
        root.addWidget(self.view, 1)

        self.hint = QLabel("Molette : zoom  ·  glisser : deplacer  ·  survol : chaine de prerequis  "
                           "·  double-clic : ouvrir le cours")
        self.hint.setObjectName("Muted")
        self.hint.setContentsMargins(14, 6, 14, 8)
        root.addWidget(self.hint)

    # ------------------------------------------------------------- rendu
    def _visible_ids(self) -> List[str]:
        kind, key = self.f_scope.currentData()
        if kind == "track":
            ids = self.syl.track_path(key)
        elif kind == "domain":
            ids = [c.id for c in self.syl.by_domain(key)]
            extra = []
            for cid in ids:
                extra.extend(p for p in self.syl.get(cid).prereqs if p not in ids)
            ids = ids + sorted(set(extra), key=self.syl.topo_rank)
        else:
            ids = list(self.syl.order)
        if self.hide_locked.isChecked():
            ids = [c for c in ids if self.statuses[c].state != LOCKED]
        return sorted(set(ids), key=self.syl.topo_rank)

    def rebuild(self) -> None:
        self.statuses = st_mod.compute(self.syl)
        pal = theme.palette()
        self.legend.setText(
            "  ".join(
                "<span style='color:%s'>&#9679;</span> <span style='color:%s'>%s</span>"
                % (pal[STATE_STYLE[s][1]], pal["muted"], st_mod.LABELS[s])
                for s in (MASTERED, STARTED, READY, AVAILABLE, LOCKED)))

        ids = self._visible_ids()
        keep = set(ids)
        self.scene.clear()
        self.scene.nodes.clear()
        self.scene.edges.clear()

        # profondeur relative au sous-graphe affiche
        depth: Dict[str, int] = {}
        for cid in sorted(ids, key=self.syl.topo_rank):
            parents = [p for p in self.syl.get(cid).prereqs if p in keep]
            depth[cid] = 0 if not parents else 1 + max(depth[p] for p in parents)

        layers: Dict[int, List[str]] = {}
        for cid in ids:
            layers.setdefault(depth[cid], []).append(cid)

        order_index = {d: i for i, d in enumerate(self.syl.domain_order)}
        positions: Dict[str, QPointF] = {}
        for layer in sorted(layers):
            column = layers[layer]
            # on ordonne par domaine, puis par barycentre des parents deja places
            def sort_key(cid: str):
                parents = [p for p in self.syl.get(cid).prereqs if p in positions]
                bary = (sum(positions[p].y() for p in parents) / len(parents)
                        if parents else 1e9)
                return (order_index.get(self.syl.get(cid).domain, 99), bary, self.syl.title(cid))
            column.sort(key=sort_key)
            total_h = len(column) * (NODE_H + ROW_GAP)
            y0 = -total_h / 2
            for i, cid in enumerate(column):
                positions[cid] = QPointF(layer * COL_GAP, y0 + i * (NODE_H + ROW_GAP))

        for cid in ids:
            course = self.syl.get(cid)
            node = Node(cid, course.title, self.syl.domain_color(course.domain),
                        self.statuses[cid].state)
            node.setPos(positions[cid])
            node.setToolTip("%s\n%s\n\n%s"
                            % (course.title, self.statuses[cid].label, course.summary))
            self.scene.addItem(node)
            self.scene.nodes[cid] = node

        edge_color = QColor(pal["line2"])
        for cid in ids:
            for pid in self.syl.get(cid).prereqs:
                if pid not in keep:
                    continue
                a = positions[pid] + QPointF(NODE_W, NODE_H / 2)
                b = positions[cid] + QPointF(0, NODE_H / 2)
                path = QPainterPath(a)
                dx = max(40.0, (b.x() - a.x()) * 0.45)
                path.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b)
                item = QGraphicsPathItem(path)
                mastered = self.statuses[pid].state == MASTERED
                pen = QPen(QColor(pal["ok"]) if mastered else edge_color, 1.6 if mastered else 1.1)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                item.setPen(pen)
                item.setZValue(0)
                self.scene.addItem(item)
                self.scene.edges.append((item, pid, cid))

        rect = self.scene.itemsBoundingRect()
        self.scene.setSceneRect(rect.adjusted(-120, -120, 120, 120))
        self.fit()

    def fit(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.view.resetTransform()
        self.view._zoom = 1.0
        self.view.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
        # on ne laisse pas le zoom initial devenir illisible
        scale = self.view.transform().m11()
        if scale > 1.3:
            factor = 1.3 / scale
            self.view.scale(factor, factor)
            self.view._zoom = 1.3
        else:
            self.view._zoom = scale

    def focus(self, course_id: str) -> None:
        node = self.scene.nodes.get(course_id)
        if node is None:
            return
        self.scene.clearSelection()
        node.setSelected(True)
        self.view.centerOn(node)

    def _generate_available(self) -> None:
        ids = [cid for cid in self._visible_ids()
               if self.statuses[cid].unlocked and not self.statuses[cid].generated]
        if ids:
            self.generate_requested.emit(ids)

    def apply_theme(self) -> None:
        self.rebuild()
