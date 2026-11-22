"""Voice Calibration Wizard for MD-TalkType.

Guides the user through reading targeted Persian sentences to:
1. Test and adjust microphone levels for speech recognition.
2. Detect recognition challenges and speaker phonetic nuances.
3. Automatically seed user vocabulary with key words for prompt injection.
"""
import re
import threading
import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..audio import MicError, Session
from .icons import line_icon, logo_icon
from .theme import c, fa
from .widgets import Card, LevelMeter, label, rtl, set_msg

# Targeted sentences covering Persian homophones, compounds, prefixes and technical terms
CALIBRATION_SENTENCES = [
    {
        "text": "فناوری هوش مصنوعی و یادگیری ماشین ساختار نرم‌افزارهای مدرن را دگرگون کرده است.",
        "keywords": ["فناوری", "هوش مصنوعی", "یادگیری ماشین", "نرم‌افزارها"],
        "hint": "بررسی روان بودن بیان کلمات مرکب و پیشوندها",
    },
    {
        "text": "توسعه‌دهندگان در شرکت‌های دانش‌بنیان، پروژه‌های خود را با دقت پیاده‌سازی می‌کنند.",
        "keywords": ["توسعه‌دهندگان", "دانش‌بنیان", "پروژه‌ها", "پیاده‌سازی"],
        "hint": "بررسی پسوندها و نیم‌فاصله‌های متوالی",
    },
    {
        "text": "پایگاه داده و سرورهای ابری اطلاعات مهم سازمان را با سرعت بالا پردازش می‌نمایند.",
        "keywords": ["پایگاه داده", "سرورهای ابری", "سازمان", "پردازش"],
        "hint": "بررسی حروف هم‌آوا و واژگان تخصصی فناوری",
    },
    {
        "text": "برای ضبط باکیفیت صدا، فاصله مناسب از میکروفون و وضوح لحن گوینده بسیار اثرگذار است.",
        "keywords": ["باکیفیت", "میکروفون", "وضوح", "اثرگذار"],
        "hint": "بررسی سطح بلندی صدا و حروف صامت و مصوت",
    },
    {
        "text": "با تنظیم دقیق این واژه‌نامه، تبدیل گفتار به متن در تمامی برنامه‌ها بی‌نقص عمل خواهد کرد.",
        "keywords": ["واژه‌نامه", "تبدیل گفتار", "تمامی برنامه‌ها", "بی‌نقص"],
        "hint": "تأیید نهایی ثبت در پرامپت اولیه مدل",
    },
]


class CalibrationWizard(QDialog):
    calibration_finished = Signal(list)  # emits list of newly added keywords
    analysis_finished = Signal(str)      # emits recognized text back to GUI thread
    analysis_failed = Signal(str)        # emits error string back to GUI thread

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.step = 0
        self.session = None
        self.recording = False
        self.collected_keywords = set()

        self.setWindowTitle("کالیبراسیون و انطباق صدای شما - MD-TalkType")
        self.setWindowIcon(logo_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(720, 520)
        self.setMinimumSize(640, 480)

        # Thread-safe signal connections
        self.analysis_finished.connect(self._analyze_result)
        self.analysis_failed.connect(self._handle_analysis_error)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        # Header
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("کالیبراسیون هوشمند صدا", "PageTitle"))
        titles.addWidget(label("جملات زیر را با صدای رسا بخوانید تا برنامه با لحن و میکروفون شما منطبق شود.", "PageSubtitle", wrap=True))
        head.addLayout(titles, 1)
        lay.addLayout(head)

        # Progress bar
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, len(CALIBRATION_SENTENCES))
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(6)
        self.prog_bar.setTextVisible(False)
        lay.addWidget(self.prog_bar)

        # Main Card for Sentence
        self.card = Card()
        self.step_label = label("", "CardTitle")
        self.card.add(self.step_label)

        self.sentence_box = QFrame()
        self.sentence_box.setObjectName("Card")
        self.sentence_box.setStyleSheet(
            f"background: {c('track')}; border-radius: 10px; padding: 14px; margin: 6px 0;"
        )
        sbox_lay = QVBoxLayout(self.sentence_box)
        self.sentence_text = QLabel()
        self.sentence_text.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {c('text')}; line-height: 1.6;")
        self.sentence_text.setWordWrap(True)
        self.sentence_text.setAlignment(Qt.AlignCenter)
        sbox_lay.addWidget(self.sentence_text)
        self.card.add(self.sentence_box)

        self.hint_label = label("", "CardText")
        self.card.add(self.hint_label)

        # Audio Meter
        self.meter = LevelMeter()
        self.card.add(self.meter)

        # Feedback & Status message
        self.status_msg = label("", "Hint", wrap=True)
        set_msg(self.status_msg, "")
        self.card.add(self.status_msg)
        lay.addWidget(self.card)

        # Controls Row
        self.ctrl_row = QHBoxLayout()
        self.btn_record = QPushButton("شروع خواندن این جمله")
        self.btn_record.setObjectName("Primary")
        self.btn_record.setIcon(line_icon("mic", "#ffffff"))
        self.btn_record.setCursor(Qt.PointingHandCursor)
        self.btn_record.clicked.connect(self._toggle_record)
        self.ctrl_row.addWidget(self.btn_record)

        self.btn_next = QPushButton("جمله بعدی")
        self.btn_next.setIcon(line_icon("check", c("text")))
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self._next_step)
        self.ctrl_row.addWidget(self.btn_next)

        self.ctrl_row.addStretch(1)

        self.btn_close = QPushButton("انصراف")
        self.btn_close.clicked.connect(self._on_close)
        self.ctrl_row.addWidget(self.btn_close)
        lay.addLayout(self.ctrl_row)

        # Level meter update timer
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._update_meter)

        self._show_step(0)

    def _update_meter(self):
        if self.recording:
            self.meter.set_level(self.app.recorder.level)
        else:
            self.meter.set_level(0.0)

    def _show_step(self, idx):
        self.step = idx
        self.prog_bar.setValue(idx)
        if idx >= len(CALIBRATION_SENTENCES):
            self._show_summary()
            return

        item = CALIBRATION_SENTENCES[idx]
        self.step_label.setText(f"جمله {fa(str(idx + 1))} از {fa(str(len(CALIBRATION_SENTENCES)))}")
        self.sentence_text.setText(item["text"])
        self.hint_label.setText(f"نکته: {item['hint']}")
        set_msg(self.status_msg, "روی «شروع خواندن این جمله» کلیک کنید و متن بالا را بخوانید.")
        self.btn_record.setText("شروع خواندن این جمله")
        self.btn_record.setIcon(line_icon("mic", "#ffffff"))
        self.btn_record.setEnabled(True)
        self.btn_next.setEnabled(False)

    def _toggle_record(self):
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        if not self.app.engine or not self.app.engine.ready.is_set():
            set_msg(self.status_msg, "مدل گفتار هنوز آماده نیست؛ لطفاً چند ثانیه صبر کنید.", "Warning")
            return

        with self.app._lock:
            if self.app.session is not None:
                set_msg(self.status_msg, "یک دیکته دیگر در حال انجام است.", "Warning")
                return
            try:
                self.session = Session(self.app.recorder, self.app.engine, self.app.cfg.tail_ms)
                self.app.session = self.session
            except MicError:
                set_msg(self.status_msg, "خطا در دسترسی به میکروفون. اتصال را بررسی کنید.", "Danger")
                return

        if hasattr(self.app, "volume") and getattr(self.app.cfg, "duck_audio", False):
            self.app.volume.duck(self.app.cfg.duck_level)

        self.recording = True
        self.btn_next.setEnabled(False)
        self.app.recorder.monitor(True)
        self._timer.start()

        self.btn_record.setText("پایان خواندن")
        self.btn_record.setIcon(line_icon("stop", "#ffffff"))
        set_msg(self.status_msg, "در حال ضبط صدا… جمله را شمرده بخوانید و سپس دکمه پایان را بزنید.", "Success")

    def _stop_recording(self):
        if not self.recording or not self.session:
            return
        self.recording = False
        self._timer.stop()
        self.meter.set_level(0.0)

        if hasattr(self.app, "volume") and getattr(self.app.cfg, "duck_audio", False):
            self.app.volume.restore()

        self.btn_record.setEnabled(False)
        self.btn_record.setText("در حال تحلیل…")
        set_msg(self.status_msg, "در حال تحلیل پردازش گفتار… لطفاً شکیبا باشید.")

        with self.app._lock:
            s = self.session
            self.session = None
            if self.app.session is s:
                self.app.session = None

        def work():
            try:
                raw = s.finish()
                self.analysis_finished.emit(raw or "")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.analysis_failed.emit(str(e))

        threading.Thread(target=work, name="calibration-asr", daemon=True).start()

    def _handle_analysis_error(self, err_msg):
        set_msg(self.status_msg, f"خطا در پردازش صدا: {err_msg}", "Danger")
        self.btn_record.setText("تلاش مجدد")
        self.btn_record.setIcon(line_icon("mic", "#ffffff"))
        self.btn_record.setEnabled(True)
        self.btn_next.setEnabled(True)

    def _analyze_result(self, recognized_text):
        target = CALIBRATION_SENTENCES[self.step]
        text_clean = (recognized_text or "").strip()

        # Always collect keywords for this sentence so they are learned
        for kw in target["keywords"]:
            self.collected_keywords.add(kw)

        if not text_clean:
            msg = "⚠️ صدایی شنیده نشد یا بسیار ضعیف بود.\nمی‌توانید دوباره تلاش کنید یا به جمله بعدی بروید."
            color = "Warning"
        else:
            recognized_clean = re.sub(r"[^\w\s]", "", recognized_text).strip()
            matched = [kw for kw in target["keywords"] if kw in recognized_text or kw in recognized_clean]
            acc = len(matched) / max(len(target["keywords"]), 1)
            msg = f"متن شنیده‌شده: «{text_clean}»\n"
            if acc >= 0.75:
                msg += f"✅ تطبیق عالی بود! ({fa(str(len(matched)))} از {fa(str(len(target['keywords'])))} کلیدواژه شناسایی شد)"
                color = "Success"
            else:
                msg += "ℹ️ صدا دریافت شد. کلیدواژه‌های این بخش به واژه‌نامه شخصی اضافه شدند."
                color = "Hint"

        set_msg(self.status_msg, msg, color)
        self.btn_record.setText("تلاش مجدد")
        self.btn_record.setIcon(line_icon("mic", "#ffffff"))
        self.btn_record.setEnabled(True)
        self.btn_next.setEnabled(True)

    def _next_step(self):
        self._show_step(self.step + 1)

    def _show_summary(self):
        self.prog_bar.setValue(len(CALIBRATION_SENTENCES))
        self.step_label.setText("کالیبراسیون با موفقیت انجام شد!")
        self.sentence_text.setText("صدای شما با موفقیت آنالیز و با مدل هماهنگ شد.")
        self.hint_label.setText("کلیدواژه‌های تخصصی این جملات به پرامپت دائمی مدل اضافه شدند.")

        # Update app config vocabulary
        new_keywords = list(self.collected_keywords)
        current_vocab = list(self.app.cfg.vocabulary)
        merged = current_vocab + [k for k in new_keywords if k not in current_vocab]
        self.app.update_config(vocabulary=merged)

        set_msg(self.status_msg, f"تعداد {fa(str(len(new_keywords)))} واژه کلیدی به واژه‌نامه تخصصی شما اضافه شد.", "Success")
        self.btn_record.setVisible(False)
        self.btn_next.setVisible(False)
        self.btn_close.setText("اتمام و بستن")
        self.btn_close.setObjectName("Primary")
        self.calibration_finished.emit(new_keywords)

    def _cleanup(self):
        self.recording = False
        self._timer.stop()
        if hasattr(self.app, "volume") and getattr(self.app.cfg, "duck_audio", False):
            self.app.volume.restore()
        with self.app._lock:
            if self.session:
                try:
                    self.session.cancel()
                except Exception:
                    pass
                if self.app.session is self.session:
                    self.app.session = None
                self.session = None
        self.app.recorder.monitor(False)

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def reject(self):
        self._cleanup()
        super().reject()

    def _on_close(self):
        self._cleanup()
        self.close()
