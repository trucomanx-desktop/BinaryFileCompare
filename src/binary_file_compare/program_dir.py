#!/usr/bin/python3

import os
import sys
import signal
import subprocess
import shutil

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QLineEdit, QMessageBox,
    QToolBar, QSizePolicy, QAction,
    QFileDialog, QHBoxLayout, QSplitter, QTreeWidget,
    QTreeWidgetItem, QMenu
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QUrl
from PyQt5.QtGui import QIcon, QDesktopServices, QColor

import binary_file_compare.about as about
import binary_file_compare.modules.configure as configure
from binary_file_compare.modules.resources import resource_path

from binary_file_compare.modules.wabout import show_about_window
from binary_file_compare.desktop import create_desktop_file, create_desktop_directory, create_desktop_menu

# ---------- Path to config file ----------
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", about.__package__, "config_dir.json")

DEFAULT_CONTENT = {
    "toolbar_configure": "Configure",
    "toolbar_configure_tooltip": "Open the configure Json file of program GUI",
    "toolbar_about": "About",
    "toolbar_about_tooltip": "About the program",
    "toolbar_coffee": "Coffee",
    "toolbar_coffee_tooltip": "Buy me a coffee (TrucomanX)",
    "window_width": 1000,
    "window_height": 750,
    "msg_select_directories": "First select both directories",
    "msg_comparing": "Comparing directories...",
    "msg_error": "Error",
    "msg_information": "Information",
    "msg_warning": "Warning",
    "title_directory_1": "Directory 1",
    "title_directory_2": "Directory 2"
}

configure.verify_default_config(CONFIG_PATH, default_content=DEFAULT_CONTENT)
CONFIG = configure.load_config(CONFIG_PATH)

CHUNK_SIZE = 1024 * 1024  # 1MB
COLOR_DIFFERENT = QColor(255, 190, 190)
COLOR_MISSING = QColor(180, 215, 255)


class DirectoryDropLineEdit(QLineEdit):
    directoryDropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile() and os.path.isdir(urls[0].toLocalFile()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if os.path.isdir(path):
                self.setText(path)
                self.directoryDropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()


class DirectoryCompareWorker(QThread):
    file_progress = pyqtSignal(int, int, int)
    finished = pyqtSignal(dict, str)

    def __init__(self, directory1, directory2):
        super().__init__()
        self.directory1 = os.path.abspath(directory1)
        self.directory2 = os.path.abspath(directory2)

    @staticmethod
    def _files_in(directory):
        files = {}
        for root, dirs, names in os.walk(directory):
            dirs.sort()
            for name in sorted(names):
                full_path = os.path.join(root, name)
                relative_path = os.path.relpath(full_path, directory)
                files[relative_path] = full_path
        return files

    def _files_are_equal(self, path1, path2, index, total):
        size1 = os.path.getsize(path1)
        size2 = os.path.getsize(path2)
        if size1 != size2:
            self.file_progress.emit(index, total, 100)
            return False
        if size1 == 0:
            self.file_progress.emit(index, total, 100)
            return True
        read_bytes = 0
        with open(path1, "rb") as file1, open(path2, "rb") as file2:
            while True:
                block1 = file1.read(CHUNK_SIZE)
                block2 = file2.read(CHUNK_SIZE)
                read_bytes += len(block1)
                self.file_progress.emit(index, total, min(100, int(read_bytes * 100 / size1)))
                if block1 != block2:
                    self.file_progress.emit(index, total, 100)
                    return False
                if not block1:
                    return True

    def run(self):
        try:
            files1 = self._files_in(self.directory1)
            files2 = self._files_in(self.directory2)
            all_paths = sorted(set(files1) | set(files2), key=lambda value: value.casefold())
            total = len(all_paths)
            results = {}

            for index, relative_path in enumerate(all_paths, 1):
                path1 = files1.get(relative_path)
                path2 = files2.get(relative_path)
                if path1 is None:
                    results[relative_path] = "missing_left"
                elif path2 is None:
                    results[relative_path] = "missing_right"
                else:
                    self.file_progress.emit(index, total, 0)
                    results[relative_path] = "identical" if self._files_are_equal(path1, path2, index, total) else "different"
                    continue
                self.file_progress.emit(index, total, 100)

            self.finished.emit(results, "")
        except Exception as error:
            self.finished.emit({}, str(error))


class MainWindow(QMainWindow):
    def __init__(self, directory1=None, directory2=None):
        super().__init__()
        self.setWindowTitle(about.__program_dir__)
        self.resize(CONFIG["window_width"], CONFIG["window_height"])
        self.icon_path = resource_path("icons", "logo.svg")
        self.setWindowIcon(QIcon(self.icon_path))
        self.last_dir = os.path.expanduser("~")
        self.directory1 = ""
        self.directory2 = ""
        self.results = {}

        self._create_toolbar()
        self.init_ui()

        if directory1:
            self.directory1_input.setText(directory1)
        if directory2:
            self.directory2_input.setText(directory2)
        if directory1 and directory2:
            self.start_comparison()

    def init_ui(self):
        layout = QVBoxLayout()

        for label, attribute, selector in (
            (CONFIG["title_directory_1"], "directory1_input", self.select_directory1),
            (CONFIG["title_directory_2"], "directory2_input", self.select_directory2),
        ):
            row = QHBoxLayout()
            field = DirectoryDropLineEdit()
            setattr(self, attribute, field)
            button = QPushButton("Select")
            button.setIcon(QIcon(resource_path("icons", "open_file.svg")))
            button.clicked.connect(selector)
            row.addWidget(QLabel(label))
            row.addWidget(field)
            row.addWidget(button)
            layout.addLayout(row)

        self.compare_btn = QPushButton("Compare directories")
        self.compare_btn.setIcon(QIcon(resource_path("icons", "play-button.svg")))
        self.compare_btn.clicked.connect(self.start_comparison)
        layout.addWidget(self.compare_btn)

        layout.addWidget(QLabel("Files compared"))
        self.files_progress = QProgressBar()
        self.files_progress.setFormat("%v / %m files")
        layout.addWidget(self.files_progress)

        layout.addWidget(QLabel("Current file comparison"))
        self.bytes_progress = QProgressBar()
        self.bytes_progress.setFormat("%p%")
        layout.addWidget(self.bytes_progress)

        self.expander = QLabel("Select two directories and compare their files.")
        layout.addWidget(self.expander)

        self.splitter = QSplitter(Qt.Horizontal)
        self.tree1 = self._create_tree(CONFIG["title_directory_1"])
        self.tree2 = self._create_tree(CONFIG["title_directory_2"])
        self.splitter.addWidget(self.tree1)
        self.splitter.addWidget(self.tree2)
        layout.addWidget(self.splitter, 1)

        self.close_btn = QPushButton("Close")
        self.close_btn.setIcon(QIcon(resource_path("icons", "application-exit.png")))
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.close_btn)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

    def _create_tree(self, title):
        tree = QTreeWidget()
        tree.setHeaderLabel(title)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda position, source=tree: self.show_copy_menu(position, source)
        )
        return tree

    def select_directory1(self):
        self._select_directory(self.directory1_input)

    def select_directory2(self):
        self._select_directory(self.directory2_input)

    def _select_directory(self, field):
        path = QFileDialog.getExistingDirectory(self, "Select directory", self.last_dir)
        if path:
            field.setText(path)
            self.last_dir = path

    def start_comparison(self):
        directory1 = self.directory1_input.text().strip()
        directory2 = self.directory2_input.text().strip()
        if not directory1 or not directory2:
            message = CONFIG.get("msg_select_directories", "First select both directories")
            QMessageBox.critical(self, CONFIG["msg_error"], message)
            return
        if not os.path.isdir(directory1) or not os.path.isdir(directory2):
            QMessageBox.warning(self, CONFIG["msg_warning"], "Both paths must be existing directories.")
            return
        self.directory1, self.directory2 = os.path.abspath(directory1), os.path.abspath(directory2)
        if os.path.realpath(self.directory1) == os.path.realpath(self.directory2):
            QMessageBox.warning(self, CONFIG["msg_warning"], "Select two different directories.")
            return
        self.compare_btn.setEnabled(False)
        self.statusBar().showMessage(CONFIG["msg_comparing"])
        self.expander.setText("Comparing files...")
        self.files_progress.setRange(0, 0)
        self.bytes_progress.setValue(0)
        self.tree1.clear()
        self.tree2.clear()
        self.worker = DirectoryCompareWorker(self.directory1, self.directory2)
        self.worker.file_progress.connect(self.on_file_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_file_progress(self, current, total, percent):
        self.files_progress.setRange(0, max(total, 1))
        self.files_progress.setValue(current)
        self.bytes_progress.setValue(percent)

    def on_finished(self, results, error):
        self.compare_btn.setEnabled(True)
        if error:
            self.expander.setText("Comparison failed: " + error)
            self.statusBar().showMessage("Comparison failed", 10000)
            QMessageBox.warning(self, CONFIG["msg_warning"], error)
            return
        self.results = results
        self._populate_trees()
        different = sum(status != "identical" for status in results.values())
        message = "Compared %d files; %d need attention." % (len(results), different)
        self.expander.setText(message)
        self.statusBar().showMessage(message, 20000)
        self.files_progress.setRange(0, max(len(results), 1))
        self.files_progress.setValue(len(results))
        self.bytes_progress.setValue(100 if results else 0)
        if different == 0:
            QMessageBox.information(self, CONFIG["msg_information"],
                                    "Directory comparison completed successfully. All %d files are identical." % len(results))
        else:
            QMessageBox.warning(self, CONFIG["msg_warning"],
                                "Directory comparison completed with %d file difference(s): files that differ or exist on only one side." % different)

    def _populate_trees(self):
        roots = (QTreeWidgetItem([self.directory1]), QTreeWidgetItem([self.directory2]))
        self.tree1.addTopLevelItem(roots[0])
        self.tree2.addTopLevelItem(roots[1])
        nodes = ({"": roots[0]}, {"": roots[1]})
        for relative_path in sorted(self.results, key=lambda value: value.casefold()):
            status = self.results[relative_path]
            parts = relative_path.split(os.sep)
            parent_key = ""
            for part in parts[:-1]:
                key = os.path.join(parent_key, part) if parent_key else part
                for side in range(2):
                    if key not in nodes[side]:
                        node = QTreeWidgetItem([part])
                        nodes[side][parent_key].addChild(node)
                        nodes[side][key] = node
                parent_key = key
            for side in range(2):
                exists = status != ("missing_left" if side == 0 else "missing_right")
                if not exists:
                    continue
                item = QTreeWidgetItem([parts[-1]])
                item.setData(0, Qt.UserRole, relative_path)
                nodes[side][parent_key].addChild(item)
                if status == "different":
                    item.setBackground(0, COLOR_DIFFERENT)
                    item.setToolTip(0, "File contents differ")
                elif status in ("missing_left", "missing_right"):
                    item.setBackground(0, COLOR_MISSING)
                    item.setToolTip(0, "File exists only in the other directory")
        self.tree1.expandAll()
        self.tree2.expandAll()

    def show_copy_menu(self, position, source_tree):
        item = source_tree.itemAt(position)
        if item is None:
            return
        relative_path = item.data(0, Qt.UserRole)
        if not relative_path:
            return
        source_side = 0 if source_tree is self.tree1 else 1
        source_root = self.directory1 if source_side == 0 else self.directory2
        target_root = self.directory2 if source_side == 0 else self.directory1
        source_path = os.path.join(source_root, relative_path)
        target_path = os.path.join(target_root, relative_path)
        menu = QMenu(self)
        action_text = "Copy to Directory 2" if source_side == 0 else "Copy to Directory 1"
        action = menu.addAction(action_text)
        copy_path_action = menu.addAction("Copy full path")
        chosen = menu.exec_(source_tree.viewport().mapToGlobal(position))
        if chosen == action:
            self.copy_file(source_path, target_path)
        elif chosen == copy_path_action:
            QApplication.clipboard().setText(source_path)

    def copy_file(self, source_path, target_path):
        if not os.path.isfile(source_path):
            QMessageBox.warning(self, CONFIG["msg_warning"], "The source file no longer exists.")
            return
        if os.path.exists(target_path):
            answer = QMessageBox.question(
                self, "Confirm copy", "Replace the destination file?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)
            self.start_comparison()
        except Exception as error:
            QMessageBox.warning(self, CONFIG["msg_error"], str(error))

    def _create_toolbar(self):
        self.toolbar = self.addToolBar("Main")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.toolbar_spacer = QWidget()
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toolbar.addWidget(self.toolbar_spacer)
        self.configure_action = QAction(QIcon(resource_path("icons", "text-configure.svg")), CONFIG["toolbar_configure"], self)
        self.configure_action.setToolTip(CONFIG["toolbar_configure_tooltip"])
        self.configure_action.triggered.connect(self.open_configure_editor)
        self.toolbar.addAction(self.configure_action)
        self.about_action = QAction(QIcon(resource_path("icons", "status_help.svg")), CONFIG["toolbar_about"], self)
        self.about_action.setToolTip(CONFIG["toolbar_about_tooltip"])
        self.about_action.triggered.connect(self.open_about)
        self.toolbar.addAction(self.about_action)
        self.coffee_action = QAction(QIcon(resource_path("icons", "emote-love.png")), CONFIG["toolbar_coffee"], self)
        self.coffee_action.setToolTip(CONFIG["toolbar_coffee_tooltip"])
        self.coffee_action.triggered.connect(self.on_coffee_action_click)
        self.toolbar.addAction(self.coffee_action)
        self.toolbar.orientationChanged.connect(self.on_update_spacer_policy)
        self.on_update_spacer_policy()

    def on_update_spacer_policy(self):
        if self.toolbar.orientation() == Qt.Horizontal:
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _open_file_in_text_editor(self, filepath):
        if os.name == "nt":
            os.startfile(filepath)
        elif os.name == "posix":
            subprocess.run(["xdg-open", filepath])

    def open_configure_editor(self):
        self._open_file_in_text_editor(CONFIG_PATH)

    def open_about(self):
        data = {
            "version": about.__version__, "package": about.__package__,
            "program_name": about.__program_dir__, "author": about.__author__,
            "email": about.__email__, "description": about.__description__,
            "url_source": about.__url_source__, "url_doc": about.__url_doc__,
            "url_funding": about.__url_funding__, "url_bugs": about.__url_bugs__
        }
        show_about_window(data, self.icon_path)

    def on_coffee_action_click(self):
        QDesktopServices.openUrl(QUrl("https://ko-fi.com/trucomanx"))


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    extras = ""
    create_desktop_directory()
    create_desktop_menu()
    create_desktop_file(os.path.join("~", ".local", "share", "applications"),
                        program_name=about.__program_dir__, extras=extras)

    for argument in sys.argv[1:]:
        if argument == "--autostart":
            create_desktop_directory(overwrite=True)
            create_desktop_menu(overwrite=True)
            create_desktop_file(os.path.join("~", ".config", "autostart"), overwrite=True,
                                program_name=about.__program_dir__, extras=extras)
            return
        if argument == "--applications":
            create_desktop_directory(overwrite=True)
            create_desktop_menu(overwrite=True)
            create_desktop_file(os.path.join("~", ".local", "share", "applications"), overwrite=True,
                                program_name=about.__program_dir__, extras=extras)
            return

    arguments = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    directory1 = arguments[0] if len(arguments) > 0 else ""
    directory2 = arguments[1] if len(arguments) > 1 else ""
    app = QApplication(sys.argv)
    app.setApplicationName(about.__program_dir__)
    window = MainWindow(directory1, directory2)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
