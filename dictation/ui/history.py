"""The history window: past dictations, newest first, with search, copy and adaptive vocabulary learning."""
import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..branding import APP_NAME
from ..paths import HISTORY_PATH
from .icons import line_icon, logo_icon
from .theme import c, fa
from .widgets import Card, label

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی",
          "بهمن", "اسفند"]
LIMIT = 300


def to_jalali(gy, gm, gd):
    """Gregorian → Jalali (Solar Hijri) date."""
    days_before = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + gd + days_before[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def jalali_text(stamp: str) -> str:
    try:
        t = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp
    y, m, d = to_jalali(t.year, t.month, t.day)
    return f"{fa(d)} {MONTHS[m - 1]} {fa(y)}، ساعت {fa(t.strftime('%H:%M'))}"


def load_history():
    if not HISTORY_PATH.exists():
        return []
    items = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-LIMIT:]:
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(items))


class AddVocabDialog(QDialog):
    """Quick modal dialog to add a term to custom vocabulary."""

    def __init__(self, default_term="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("افزودن به واژه‌نامه تخصصی (پرامپت)")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(400, 160)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(label("کلمه یا عبارت تخصصی را تأیید کنید:", "CardTitle"))

        self.input = QLineEdit(default_term)
        lay.addWidget(self.input)

        row = QHBoxLayout()
        ok_btn = QPushButton("ثبت در واژه‌نامه")
        ok_btn.setObjectName("Primary")
        ok_btn.clicked.connect(self.accept)
        row.addWidget(ok_btn)

        cancel_btn = QPushButton("انصراف")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        lay.addLayout(row)

    def term(self):
        return self.input.text().strip()


class HistoryWindow(QWidget):
    def __init__(self, app, copy_text):
        super().__init__()
        self.app = app
        self.copy_text = copy_text
        self.setObjectName("Window")
        self.setWindowTitle(f"تاریخچه‌ی متن‌ها · {APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 640)
        col = QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 20)
        col.setSpacing(12)
        col.addWidget(label("تاریخچه‌ی متن‌ها", "PageTitle"))
        col.addWidget(label("متن‌هایی که دیکته کرده‌اید؛ می‌توانید واژگان خاص را مستقیماً به حافظه مدل بیفزایید.",
                            "PageSubtitle", wrap=True))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو در متن‌ها…")
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        clear = QPushButton("پاک کردن همه")
        clear.setObjectName("Danger")
        clear.setIcon(line_icon("trash", c("danger")))
        clear.clicked.connect(self._clear)
        bar.addWidget(clear)
        col.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        col.addWidget(self.scroll, 1)
        self.items = []

    def showEvent(self, e):
        super().showEvent(e)
        self.items = load_history()
        self._fill()

    def _fill(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        q = self.search.text().strip()
        shown = [it for it in self.items if not q or q in it.get("text", "")]
        if not shown:
            empty = QLabel("هنوز متنی دیکته نشده است." if not self.items else "چیزی پیدا نشد.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            lay.addStretch(1)
            lay.addWidget(empty)
        for it in shown:
            card = Card()
            head = QHBoxLayout()
            head.addWidget(label(jalali_text(it.get("time", "")), "Faint"), 1)

            # Teach to Model button
            add_v = QPushButton("یادگیری کلمه")
            add_v.setObjectName("Link")
            add_v.setIcon(line_icon("plus", c("primary")))
            add_v.setToolTip("افزودن واژه‌ای از این متن به واژه‌نامه تخصصی مدل")
            add_v.clicked.connect(lambda _=False, t=it.get("text", ""): self._prompt_add_vocab(t))
            head.addWidget(add_v)

            copy = QPushButton("کپی")
            copy.setObjectName("Link")
            copy.setIcon(line_icon("copy", c("primary")))
            copy.clicked.connect(lambda _=False, t=it.get("text", ""): self.copy_text(t))
            head.addWidget(copy)
            card.add(head)

            text_lbl = QLabel(it.get("text", ""))
            text_lbl.setWordWrap(True)
            text_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text_lbl.setStyleSheet(f"font-size: 14px; line-height: 1.5; color: {c('text')};")
            card.add(text_lbl)
            lay.addWidget(card)
        lay.addStretch(1)
        self.scroll.setWidget(body)

    def _prompt_add_vocab(self, full_text):
        dlg = AddVocabDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            term = dlg.term()
            if term:
                current = list(self.app.cfg.vocabulary)
                if term not in current:
                    current.append(term)
                    self.app.update_config(vocabulary=current)
                    QMessageBox.information(self, "یادگیری انجام شد", f"واژه «{term}» به پرامپت هوشمند مدل اضافه شد.")
                else:
                    QMessageBox.information(self, "واژه موجود است", f"واژه «{term}» از قبل در واژه‌نامه شما ثبت شده است.")

    def _clear(self):
        box = QMessageBox(self)
        box.setLayoutDirection(Qt.RightToLeft)
        box.setWindowTitle("پاک کردن تاریخچه")
        box.setText("همه‌ی متن‌های ذخیره‌شده پاک شوند؟ این کار برگشت‌پذیر نیست.")
        yes = box.addButton("پاک کن", QMessageBox.DestructiveRole)
        box.addButton("انصراف", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            HISTORY_PATH.unlink(missing_ok=True)
            self.items = []
            self._fill()
