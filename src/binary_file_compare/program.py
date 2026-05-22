#!/usr/bin/python3

import os
import sys
import signal
import argparse
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QMainWindow, 
    QProgressBar, QPushButton, QLineEdit, QMessageBox, 
    QToolBar, QSizePolicy, QAction,
    QFileDialog, QHBoxLayout
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QUrl
from PyQt5.QtGui import QIcon, QDesktopServices

import binary_file_compare.about as about
import binary_file_compare.modules.configure as configure 
from binary_file_compare.modules.resources import resource_path

from binary_file_compare.modules.wabout    import show_about_window
from binary_file_compare.desktop import create_desktop_file, create_desktop_directory, create_desktop_menu

# ---------- Path to config file ----------
CONFIG_PATH = os.path.join( os.path.expanduser("~"),
                            ".config", 
                            about.__package__, 
                            "config.json" )

DEFAULT_CONTENT={   
    "toolbar_configure": "Configure",
    "toolbar_configure_tooltip": "Open the configure Json file of program GUI",
    "toolbar_about": "About",
    "toolbar_about_tooltip": "About the program",
    "toolbar_coffee": "Coffee",
    "toolbar_coffee_tooltip": "Buy me a coffee (TrucomanX)",
    "window_width": 800,
    "window_height": 400,
    "msg_select_files": "First select both files",
    "msg_comparing": "Comparing...",
    "msg_error": "Error",
    "msg_information": "Information",
    "msg_warning": "Warning",
}

configure.verify_default_config(CONFIG_PATH,default_content=DEFAULT_CONTENT)

CONFIG=configure.load_config(CONFIG_PATH)

# ---------------------------------------


CHUNK_SIZE = 1024 * 1024  # 1MB


class CompareWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, file1, file2):
        super().__init__()
        self.file1 = file1
        self.file2 = file2

    def run(self):
        try:
            with open(self.file1, "rb") as f1, open(self.file2, "rb") as f2:
                f1.seek(0, 2)
                f2.seek(0, 2)

                size1 = f1.tell()
                size2 = f2.tell()

                if size1 != size2:
                    self.progress.emit(100)
                    self.finished.emit(False, "Files have different sizes")
                    return

                f1.seek(0)
                f2.seek(0)

                total = size1
                read_bytes = 0

                while True:
                    b1 = f1.read(CHUNK_SIZE)
                    b2 = f2.read(CHUNK_SIZE)

                    if not b1:
                        break

                    if b1 != b2:
                        self.finished.emit(False, "Files are different")
                        return

                    read_bytes += len(b1)
                    progress_percent = int((read_bytes / total) * 100)
                    self.progress.emit(progress_percent)

            self.finished.emit(True, "Files are identical")

        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self, file1=None, file2=None):
        super().__init__()

        self.setWindowTitle(about.__program_name__)
        self.resize(CONFIG["window_width"], CONFIG["window_height"])
        
        ## Icon
        # Get base directory for icons
        self.icon_path = resource_path("icons", "logo.svg")
        self.setWindowIcon(QIcon(self.icon_path)) 

        self._create_toolbar()
        self.init_ui()

        if file1 and file2:
            self.file1_input.setText(file1)
            self.file2_input.setText(file2)
            self.start_comparison()

    def init_ui(self):
        
        layout = QVBoxLayout()

        # FILE 1
        file1_layout = QHBoxLayout()
        self.file1_input = QLineEdit()
        btn1 = QPushButton("Select")
        btn1.setIcon(QIcon(resource_path("icons", "open_file.svg")))
        btn1.clicked.connect(self.select_file1)
        file1_layout.addWidget(self.file1_input)
        file1_layout.addWidget(btn1)
        layout.addLayout(file1_layout)

        # FILE 2
        file2_layout = QHBoxLayout()
        self.file2_input = QLineEdit()
        btn2 = QPushButton("Select")
        btn2.setIcon(QIcon(resource_path("icons", "open_file.svg")))
        btn2.clicked.connect(self.select_file2)
        file2_layout.addWidget(self.file2_input)
        file2_layout.addWidget(btn2)
        layout.addLayout(file2_layout)

        #
        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setIcon(QIcon(resource_path("icons", "play-button.svg")))
        self.compare_btn.clicked.connect(self.start_comparison)
        layout.addWidget(self.compare_btn)

        #
        self.expander = QLabel("")
        layout.addWidget(self.expander)
               
        #
        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        #
        self.close_btn = QPushButton("Close")
        self.close_btn.setIcon(QIcon(resource_path("icons", "application-exit.png")))
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.close_btn)


        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        


    def select_file1(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file 1")
        if path:
            self.file1_input.setText(path)

    def select_file2(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file 2")
        if path:
            self.file2_input.setText(path)

    def start_comparison(self):
        file1 = self.file1_input.text()
        file2 = self.file2_input.text()

        if not file1 or not file2:
            self.statusBar().showMessage(CONFIG["msg_select_files"], 5000)
            QMessageBox.critical(
                self,
                CONFIG["msg_error"],
                CONFIG["msg_select_files"]
            )
            return

        self.compare_btn.setEnabled(False)
        self.statusBar().showMessage(CONFIG["msg_comparing"], 5000)
        self.progress.setValue(0)

        self.worker = CompareWorker(file1, file2)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, success, message):
        if success:
            QMessageBox.information(
                self,
                CONFIG["msg_information"],
                message
            )
        else:
            QMessageBox.warning(
                self,
                CONFIG["msg_warning"],
                message
            )
        
        self.compare_btn.setEnabled(True)
        self.statusBar().showMessage(">> "+message, 20000)
        self.progress.setValue(0)

    def _create_toolbar(self):
        self.toolbar = self.addToolBar("Main")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        # Adicionar o espaçador
        self.toolbar_spacer = QWidget()
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toolbar.addWidget(self.toolbar_spacer)
        
        #
        self.configure_action = QAction(QIcon(resource_path("icons", "text-configure.svg")), 
                                        CONFIG["toolbar_configure"], 
                                        self)
        self.configure_action.setToolTip(CONFIG["toolbar_configure_tooltip"])
        self.configure_action.triggered.connect(self.open_configure_editor)
        self.toolbar.addAction(self.configure_action)
        
        #
        self.about_action = QAction(QIcon(resource_path("icons", "status_help.svg")), 
                                    CONFIG["toolbar_about"], 
                                    self)
        self.about_action.setToolTip(CONFIG["toolbar_about_tooltip"])
        self.about_action.triggered.connect(self.open_about)
        self.toolbar.addAction(self.about_action)
        
        # Coffee
        self.coffee_action = QAction(   QIcon(resource_path("icons", "emote-love.png")), 
                                        CONFIG["toolbar_coffee"], 
                                        self)
        self.coffee_action.setToolTip(CONFIG["toolbar_coffee_tooltip"])
        self.coffee_action.triggered.connect(self.on_coffee_action_click)
        self.toolbar.addAction(self.coffee_action)

        # Conectar ao sinal de mudança de orientação
        self.toolbar.orientationChanged.connect(self.on_update_spacer_policy)
        self.on_update_spacer_policy()

    def on_update_spacer_policy(self):
        """Atualiza a política do espaçador baseado na orientação da toolbar"""
        if self.toolbar.orientation() == Qt.Horizontal:
            # Horizontal: expande na largura
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            # Vertical: expande na altura
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _open_file_in_text_editor(self, filepath):
        if os.name == 'nt':  # Windows
            os.startfile(filepath)
        elif os.name == 'posix':  # Linux/macOS
            subprocess.run(['xdg-open', filepath])
    
    def open_url_usage_editor(self):
        QDesktopServices.openUrl(QUrl(CONFIG_GPT["usage"]))
        
    def open_configure_editor(self):
        self._open_file_in_text_editor(CONFIG_PATH)

    def open_about(self):
        data={
            "version": about.__version__,
            "package": about.__package__,
            "program_name": about.__program_name__,
            "author": about.__author__,
            "email": about.__email__,
            "description": about.__description__,
            "url_source": about.__url_source__,
            "url_doc": about.__url_doc__,
            "url_funding": about.__url_funding__,
            "url_bugs": about.__url_bugs__
        }
        show_about_window(data,self.icon_path)

    def on_coffee_action_click(self):
        QDesktopServices.openUrl(QUrl("https://ko-fi.com/trucomanx"))

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
       
    '''
    extras="" # "MimeType=text/vnd.graphviz;"
    
    create_desktop_directory()    
    create_desktop_menu()
    create_desktop_file(os.path.join("~",".local","share","applications"), 
                        program_name=about.__program_name__,
                        extras=extras)
    
    for n in range(len(sys.argv)):
        if sys.argv[n] == "--autostart":
            create_desktop_directory(overwrite = True)
            create_desktop_menu(overwrite = True)
            create_desktop_file(os.path.join("~",".config","autostart"), 
                                overwrite=True, 
                                program_name=about.__program_name__,
                                extras=extras)
            return
        if sys.argv[n] == "--applications":
            create_desktop_directory(overwrite = True)
            create_desktop_menu(overwrite = True)
            create_desktop_file(os.path.join("~",".local","share","applications"), 
                                overwrite=True, 
                                program_name=about.__program_name__,
                                extras=extras)
            return
    '''
    
    args = sys.argv[1:]

    # pega no máximo 2 argumentos
    file1 = args[0] if len(args) > 0 else ""
    file2 = args[1] if len(args) > 1 else ""

    app = QApplication(sys.argv)
    app.setApplicationName(about.__package__)
    
    window = MainWindow(file1, file2)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
