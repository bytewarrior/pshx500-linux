"""Main window of the PS-HX500 recording GUI.

Monitor (level/capture), listening (audio playback) and recording (file) are
independent switches on one shared CaptureSession. Stopping runs in a background
thread so the GUI does not freeze.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime

from PySide6 import QtCore, QtWidgets

from .. import formats as F
from ..device import DeviceError
from ..meter import FLOOR
from ..monitor import list_output_devices
from ..recorder import CaptureSession
from .meterwidget import MeterWidget

_SILENCE = [{"peak_db": FLOOR, "hold_db": FLOOR, "over": False} for _ in range(2)]


class MainWindow(QtWidgets.QMainWindow):
    _stopped = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PS-HX500 Recorder")
        self.session: CaptureSession | None = None
        self._rec_start = 0.0

        self.meter = MeterWidget()

        # Format: PCM (.wav) or DSD (.dsf) -- as in Sony's recorder
        self.format_box = QtWidgets.QComboBox()
        self.format_box.addItem("PCM (.wav)", "pcm")
        self.format_box.addItem("DSD (.dsf)", "dsd")
        self.format_box.currentIndexChanged.connect(self._on_format_change)

        self.rate_box = QtWidgets.QComboBox()
        self.bits_box = QtWidgets.QComboBox()
        for b in sorted(F.FORMATS):
            self.bits_box.addItem(f"{b} bit", b)
        self.bits_box.setCurrentText("24 bit")
        self._populate_rates()   # fills rate_box to match the format

        self.gain = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gain.setRange(-120, 120)      # 0.1 dB steps
        self.gain.setValue(0)
        self.gain_lbl = QtWidgets.QLabel("Gain: +0.0 dB")
        self.gain.valueChanged.connect(self._on_gain)

        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("Target WAV file…")
        browse = QtWidgets.QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)

        self.monitor_chk = QtWidgets.QCheckBox("Listen")
        self.monitor_chk.setChecked(True)
        self.monitor_chk.toggled.connect(self._on_listen)
        self.out_box = QtWidgets.QComboBox()
        self.out_box.addItem("Default device", None)
        for idx, name in list_output_devices():
            self.out_box.addItem(name, idx)
        self.out_box.currentIndexChanged.connect(self._on_device_change)
        if self.out_box.count() == 1:
            self.monitor_chk.setChecked(False)
            self.monitor_chk.setEnabled(False)
            self.out_box.setEnabled(False)
            self.monitor_chk.setToolTip("sounddevice/PortAudio not available")

        self.btn_monitor = QtWidgets.QPushButton("Monitor")
        self.btn_monitor.setCheckable(True)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        self.btn_record = QtWidgets.QPushButton("● Record")
        self.btn_record.setCheckable(True)
        self.btn_record.clicked.connect(self._toggle_record)

        self.status = QtWidgets.QLabel("Ready.")
        self.time_lbl = QtWidgets.QLabel("00:00.0")
        self.time_lbl.setStyleSheet("font-size: 20px;")

        form = QtWidgets.QFormLayout()
        form.addRow("Format", self.format_box)
        form.addRow("Sample rate", self.rate_box)
        form.addRow("Bit depth", self.bits_box)
        form.addRow(self.gain_lbl, self.gain)
        prow = QtWidgets.QHBoxLayout(); prow.addWidget(self.path_edit); prow.addWidget(browse)
        form.addRow("File", prow)
        mrow = QtWidgets.QHBoxLayout(); mrow.addWidget(self.monitor_chk); mrow.addWidget(self.out_box, 1)
        form.addRow("Output", mrow)

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.btn_monitor); btns.addWidget(self.btn_record)
        btns.addStretch(1); btns.addWidget(self.time_lbl)

        right = QtWidgets.QVBoxLayout()
        right.addLayout(form); right.addLayout(btns); right.addWidget(self.status); right.addStretch(1)
        central = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(central)
        lay.addWidget(self.meter); lay.addLayout(right, 1)
        self.setCentralWidget(central)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._stopped.connect(self._on_stopped)

    # ---- Format / rates ----------------------------------------------------
    def _is_dsd(self) -> bool:
        return self.format_box.currentData() == "dsd"

    def _populate_rates(self) -> None:
        self.rate_box.blockSignals(True)
        self.rate_box.clear()
        if self._is_dsd():
            self.rate_box.addItem("2.8 MHz (DSD64)", 64)
            self.rate_box.addItem("5.6 MHz (DSD128)", 128)
        else:
            for r in F.RATES:
                self.rate_box.addItem(f"{r/1000:g} kHz", r)
            self.rate_box.setCurrentIndex(F.RATES.index(96000))
        self.rate_box.blockSignals(False)

    def _on_format_change(self, _idx: int = 0) -> None:
        self._populate_rates()
        dsd = self._is_dsd()
        # Bit depth and gain apply to PCM only (DSD gain would need remodulation)
        self.bits_box.setEnabled(not dsd)
        self.gain.setEnabled(not dsd)
        self.gain_lbl.setEnabled(not dsd)
        # adjust the file extension in the path
        ext = ".dsf" if dsd else ".wav"
        self.path_edit.setPlaceholderText(f"Target file ({ext})…")
        p = self.path_edit.text().strip()
        if p:
            root = p[: -len(os.path.splitext(p)[1])] if os.path.splitext(p)[1] else p
            self.path_edit.setText(root + ext)

    # ---- Session management ------------------------------------------------
    def _ensure_session(self) -> bool:
        if self.session is not None:
            return True
        try:
            if self._is_dsd():
                s = CaptureSession(dsd=self.rate_box.currentData())
            else:
                s = CaptureSession(rate=self.rate_box.currentData(),
                                   bits=self.bits_box.currentData())
            s.start()
        except DeviceError as e:
            QtWidgets.QMessageBox.critical(self, "Device error", str(e))
            return False
        s.set_gain(self.gain.value() / 10.0)
        if self.monitor_chk.isChecked():
            s.set_monitor(True, self.out_box.currentData())
        self.session = s
        self._set_config_enabled(False)
        self._timer.start()
        if s.validity != 1:
            self.status.setText(f"⚠ Clock validity={s.validity}")
        elif s.monitor_error:
            self.status.setText(f"Listening off: {s.monitor_error}")
        else:
            self.status.setText("Running…")
        return True

    def _maybe_stop_session(self) -> None:
        if (self.session is not None
                and not self.btn_monitor.isChecked()
                and not self.btn_record.isChecked()):
            self._async_stop()

    def _async_stop(self) -> None:
        s, self.session = self.session, None
        self.btn_monitor.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.status.setText("Stopping…")

        def work():
            try:
                s.stop()
            finally:
                self._stopped.emit()
        threading.Thread(target=work, name="pshx500-stop", daemon=True).start()

    def _on_stopped(self) -> None:
        self._timer.stop()
        self.meter.set_levels(_SILENCE)
        self.time_lbl.setText("00:00.0")
        self.btn_monitor.setEnabled(True)
        self.btn_record.setEnabled(True)
        self.btn_monitor.setChecked(False)
        self.btn_record.setChecked(False)
        self._set_config_enabled(True)
        self.status.setText("Ready.")

    # ---- Switches ----------------------------------------------------------
    def _toggle_monitor(self, on: bool) -> None:
        if on:
            if not self._ensure_session():
                self.btn_monitor.setChecked(False)
        else:
            self._maybe_stop_session()

    def _toggle_record(self, on: bool) -> None:
        if on:
            path = self.path_edit.text().strip()
            if not path:
                self._browse()
                path = self.path_edit.text().strip()
            if not path:
                self.btn_record.setChecked(False)
                return
            if not self._ensure_session():
                self.btn_record.setChecked(False)
                return
            self.session.start_recording(path, gain_db=self.gain.value() / 10.0)
            self._rec_start = time.monotonic()
            self.status.setText(f"Recording → {path}")
        else:
            if self.session is not None:
                self.session.stop_recording()
                self.status.setText("Recording stopped.")
            self._maybe_stop_session()

    def _on_listen(self, checked: bool) -> None:
        if self.session is not None:
            self.session.set_monitor(checked, self.out_box.currentData())
            if checked and self.session.monitor_error:
                self.status.setText(f"Listening off: {self.session.monitor_error}")

    def _on_device_change(self, _idx: int) -> None:
        if self.session is not None and self.monitor_chk.isChecked():
            self.session.set_monitor(False)
            self.session.set_monitor(True, self.out_box.currentData())

    def _on_gain(self, v: int) -> None:
        db = v / 10.0
        self.gain_lbl.setText(f"Gain: {db:+.1f} dB")
        if self.session is not None:
            self.session.set_gain(db)

    def _browse(self) -> None:
        ext = ".dsf" if self._is_dsd() else ".wav"
        default = datetime.now().strftime(f"pshx500_%Y%m%d_%H%M%S{ext}")
        filt = "DSF files (*.dsf)" if self._is_dsd() else "WAV files (*.wav)"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save recording", default, filt,
            options=QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.path_edit.setText(path)

    def _set_config_enabled(self, en: bool) -> None:
        self.format_box.setEnabled(en)
        self.rate_box.setEnabled(en)
        self.bits_box.setEnabled(en and not self._is_dsd())

    def _tick(self) -> None:
        s = self.session
        if s is None:
            return
        self.meter.set_levels(s.meter.read())
        if s.recording:
            el = time.monotonic() - self._rec_start
            self.time_lbl.setText(f"{int(el // 60):02d}:{el % 60:04.1f}")

    def closeEvent(self, ev) -> None:
        if self.session is not None:
            self.session.stop()
            self.session = None
        super().closeEvent(ev)
