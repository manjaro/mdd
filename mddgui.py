#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Frede Hundewadt <fh@manjaro.org>
# SPDX-License-Identifier: MIT

import json
import os
import sys
import mdd
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QLabel, QPlainTextEdit, QRadioButton, QSizePolicy, QVBoxLayout, QWidget
from PySide6 import QtCore, QtWidgets

config = {
    "telemetry": True,
    "enabled": False,
    "schedule": "1w",
}

class MDD(QtWidgets.QWidget):
    sysdata = None

    def __init__(self):
        super().__init__()
        self.config_modified = False
        self.setWindowTitle("MDD - The Manjaro Data Donor")
        self.resize(500, 650)
        size_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        size_policy.setHorizontalStretch(0)
        size_policy.setVerticalStretch(0)
        size_policy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(size_policy)
        self.setMinimumSize(QSize(500, 650))
        self.setMaximumSize(QSize(500, 650))
        # self.setSizeGripEnabled(False)
        self.buttonBox = QDialogButtonBox(self)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setGeometry(QRect(250, 600, 240, 32))
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.previewSysInfo = QPlainTextEdit(self)
        self.previewSysInfo.setObjectName(u"previewSysInfo")
        self.previewSysInfo.setGeometry(QRect(10, 10, 480, 410))
        font = QFont()
        font.setFamilies([u"Monospace"])
        font.setPointSize(9)
        self.previewSysInfo.setFont(font)
        # self.previewSysInfo.setStyleSheet(u"background-color: rgb(226, 226, 226);\n"
        #                                   "color: rgb(0, 0, 0);")
        self.previewSysInfo.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.labelTimerOptions = QLabel(self)
        self.labelTimerOptions.setObjectName(u"labelTimerOptions")
        self.labelTimerOptions.setGeometry(QRect(270, 440, 200, 25))
        self.labelServiceOptions = QLabel(self)
        self.labelServiceOptions.setObjectName(u"labelServiceOptions")
        self.labelServiceOptions.setGeometry(QRect(20, 440, 200, 25))
        self.widgetLayoutTimerConfig = QWidget(self)
        self.widgetLayoutTimerConfig.setObjectName(u"widgetLayoutTimerConfig")
        self.widgetLayoutTimerConfig.setGeometry(QRect(260, 460, 231, 121))
        self.layoutTimerConfig = QVBoxLayout(self.widgetLayoutTimerConfig)
        self.layoutTimerConfig.setObjectName(u"layoutTimerConfig")
        self.layoutTimerConfig.setContentsMargins(10, 10, 0, 0)
        self.optionWeekly = QRadioButton(self.widgetLayoutTimerConfig)
        self.optionWeekly.setObjectName(u"optionWeekly")
        self.optionWeekly.setChecked(True)

        self.layoutTimerConfig.addWidget(self.optionWeekly)

        self.optionBiWeekly = QRadioButton(self.widgetLayoutTimerConfig)
        self.optionBiWeekly.setObjectName(u"optionBiWeekly")

        self.layoutTimerConfig.addWidget(self.optionBiWeekly)

        self.optionMonthly = QRadioButton(self.widgetLayoutTimerConfig)
        self.optionMonthly.setObjectName(u"optionMonthly")

        self.layoutTimerConfig.addWidget(self.optionMonthly)

        self.checkEnableTimer = QCheckBox(self.widgetLayoutTimerConfig)
        self.checkEnableTimer.setObjectName(u"checkEnableTimer")

        self.layoutTimerConfig.addWidget(self.checkEnableTimer)

        self.widgetDataConfig = QWidget(self)
        self.widgetDataConfig.setObjectName(u"widgetDataConfig")
        self.widgetDataConfig.setGeometry(QRect(10, 460, 231, 71))
        self.layoutDataConfig = QVBoxLayout(self.widgetDataConfig)
        self.layoutDataConfig.setObjectName(u"layoutDataConfig")
        self.layoutDataConfig.setContentsMargins(10, 10, 0, 0)
        self.optionSystemInfo = QRadioButton(self.widgetDataConfig)
        self.optionSystemInfo.setObjectName(u"optionSystemInfo")
        self.optionSystemInfo.setChecked(True)

        self.layoutDataConfig.addWidget(self.optionSystemInfo)

        self.optionSystemPing = QRadioButton(self.widgetDataConfig)
        self.optionSystemPing.setObjectName(u"optionSystemPing")

        self.layoutDataConfig.addWidget(self.optionSystemPing)

        # set text (this is candidate for translation
        self.checkEnableTimer.setText(u"Enable Timer")
        self.optionWeekly.setText(u"Weekly")
        self.optionBiWeekly.setText(u"Biweek&ly")
        self.optionMonthly.setText(u"Mon&thly")
        self.labelTimerOptions.setText(
            u"<html><head/><body><p><span style=\" font-size:11pt; font-weight:700;\">Donate Timer</span></p></body></html>")
        self.optionSystemInfo.setText(u"S&ystem Info")
        self.labelServiceOptions.setText(
            u"<html><head/><body><p><span style=\" font-size:11pt; font-weight:700;\">Donate Info</span></p></body></html>")
        self.optionSystemPing.setText(u"&Basic Ping")

        self.buttonBox.accepted.connect(self.accepted)
        self.buttonBox.rejected.connect(self.rejected)
        self.checkEnableTimer.clicked.connect(self.enable_service)
        self.optionBiWeekly.clicked.connect(self.opt_biweekly_set)
        self.optionMonthly.clicked.connect(self.opt_monthly_set)
        self.optionSystemPing.clicked.connect(self.opt_system_ping_set)
        self.optionSystemInfo.clicked.connect(self.opt_system_info_set)
        self.optionWeekly.clicked.connect(self.opt_weekly_set)

        self.sysdata = mdd.get_device_data(config["telemetry"])
        self.previewSysInfo.setPlainText(mdd.json_beaut(self.sysdata, indent=2))

    def set_config(self, new_config):
        config.update(new_config)
        self.config_modified = True
        if config["schedule"] == "1w":
            self.optionWeekly.setChecked(True)
        if config["schedule"] == "2w":
            self.optionBiWeekly.setChecked(True)
        if config["schedule"] == "4w":
            self.optionMonthly.setChecked(True)
        if config["enabled"]:
            self.checkEnableTimer.setChecked(True)

        self.previewSysInfo.setPlainText("Stand by... working")
        self.previewSysInfo.repaint()
        self.optionSystemPing.setChecked(not config["telemetry"])
        self.optionSystemInfo.setChecked(config["telemetry"])

        self.sysdata = mdd.get_device_data(new_config)
        self.previewSysInfo.setPlainText(mdd.json_beaut(self.sysdata, indent=2))

    @staticmethod
    def rejected():
        exit()

    @QtCore.Slot()
    def opt_weekly_set(self):
        config["schedule"] = "1w"
        generate_service_files()
        self.config_modified = True

    @QtCore.Slot()
    def opt_biweekly_set(self):
        config["schedule"] = "2w"
        generate_service_files()
        self.config_modified = True

    @QtCore.Slot()
    def opt_monthly_set(self):
        config["schedule"] = "4w"
        generate_service_files()
        self.config_modified = True

    @QtCore.Slot()
    def enable_service(self):
        config["enabled"] = self.checkEnableTimer.isChecked()
        set_timer_state(config["enabled"])
        self.config_modified = True

    @QtCore.Slot()
    def accepted(self):
        if self.sysdata is not None:
            mdd.http_post_info(self.sysdata)
        if self.config_modified:
            write_config()
        self.rejected()

    @QtCore.Slot()
    def opt_system_ping_set(self):
        config["telemetry"] = False
        self.config_modified = True
        self.previewSysInfo.clear()
        self.previewSysInfo.setPlainText("Stand by... working")
        self.previewSysInfo.repaint()
        self.sysdata = mdd.get_device_data(config["telemetry"])
        self.previewSysInfo.clear()
        self.previewSysInfo.setPlainText(mdd.json_beaut(self.sysdata, indent=2))
        generate_service_files()

    @QtCore.Slot()
    def opt_system_info_set(self):
        config["telemetry"] = True
        self.config_modified = True
        self.previewSysInfo.clear()
        self.previewSysInfo.setPlainText("Stand by... working")
        self.previewSysInfo.repaint()
        self.sysdata = mdd.get_device_data(config["telemetry"])
        self.previewSysInfo.clear()
        self.previewSysInfo.setPlainText(mdd.json_beaut(self.sysdata, indent=2))
        generate_service_files()


def generate_service_files():
    service_path = f"{os.path.expanduser("~")}/.config/systemd/user"
    if not os.path.exists(service_path):
        os.makedirs(service_path)
    disable_telemetry = f"--disable-telemetry"
    if config["telemetry"]:
        disable_telemetry = ""
    timer_template = f"[Unit]\n" \
                     f"Description=Schedule Manjaro Data Donor\n\n" \
                     f"[Timer]\n" \
                     f"OnStartupSec=10m\n" \
                     f"OnUnitActiveSec={config['schedule']}\n\n" \
                     f"[Install]\n" \
                     f"WantedBy=timers.target\n"
    service_template = f"[Unit]\n" \
                       f"Description=Manjaro Data Donor\n" \
                       f"Wants=network-online.target\n" \
                       f"After=network-online.target default.target\n\n" \
                       f"[Service]\n" \
                       f"Type=oneshot\n" \
                       f"ExecStart=/usr/bin/mdd {disable_telemetry}\n\n" \
                       f"[Install]\n" \
                       f"WantedBy=default.target\n"
    # write user service unit
    with open(f"{service_path}/self.service", "w") as f:
        f.write(service_template)
    # writ user timer
    with open(f"{service_path}/self.timer", "w") as f:
        f.write(timer_template)


def set_timer_state(enable: bool):
    if enable:
        mdd.get_command_output("systemctl --user enable self.timer")
        return
    mdd.get_command_output("systemctl --user disable self.timer")


def write_config():
    config_file = f"{os.path.expanduser("~")}/.config/self.conf"
    if write_config:
        with open(config_file, "w") as f:
            json.dump(config, f)
        return config


def read_config():
    config_file = f"{os.path.expanduser("~")}/.config/self.conf"
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    else:
        return {"telemetry": True, "schedule": "1w", "enabled": True}

def run():
    mdd.prepare_inxi()
    config.update(read_config())
    app = QtWidgets.QApplication(sys.argv)
    widget = MDD()
    widget.set_config(config)
    widget.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
