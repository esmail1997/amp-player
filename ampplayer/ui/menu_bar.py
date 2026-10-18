"""Native Qt menu semantics, without player shortcuts stealing arrow keys."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QMenuBar, QMenu


class AccessibleMenuBar(QMenuBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setNativeMenuBar(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._return_focus = None

    def activate(self):
        self._return_focus = QApplication.focusWidget()
        self.setFocus(Qt.FocusReason.MenuBarFocusReason)
        actions = self.actions()
        if actions:
            self.setActiveAction(actions[0])

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            # Qt's menu key handlers must receive keys before window actions.
            event.accept()
            return True
        return super().event(event)

    def eventFilter(self, obj, event):
        if isinstance(obj, QMenu) and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        actions = [a for a in self.actions() if a.isEnabled() and a.isVisible()]
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and actions:
            current = self.activeAction()
            index = actions.index(current) if current in actions else 0
            step = 1 if key == Qt.Key.Key_Right else -1
            if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                step = -step
            self.setActiveAction(actions[(index + step) % len(actions)])
            event.accept()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            action = self.activeAction()
            if action and action.menu():
                menu = action.menu()
                menu.popup(self.mapToGlobal(self.actionGeometry(action).bottomLeft()))
                first = next((a for a in menu.actions()
                              if a.isEnabled() and a.isVisible() and not a.isSeparator()), None)
                menu.setActiveAction(first)
            event.accept()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_F10):
            self.setActiveAction(None)
            if self._return_focus:
                self._return_focus.setFocus(Qt.FocusReason.MenuBarFocusReason)
            else:
                self.parentWidget().setFocus()
            event.accept()
        else:
            super().keyPressEvent(event)
