import os
import re
import sys
import math
import time
import json
import random
import fnmatch

import signal
import functools
import traceback
import threading
import subprocess

import multiprocessing
import concurrent.futures

import optimize_textures as Ot

from string import Template

import PyQt5
import PyQt5.QtGui as QtGui
import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets

from PyQt5.QtCore import Qt #pylint: disable=E0611
from PyQt5.QtCore import qDebug #pylint: disable=E0611
from PyQt5.QtCore import qWarning #pylint: disable=E0611
from PyQt5.QtCore import qCritical #pylint: disable=E0611
from PyQt5.QtCore import QCoreApplication #pylint: disable=E0611

class StandaloneWindow(QtWidgets.QDialog):

    def __tr(self, str):
        return QCoreApplication.translate("OptimizeTexturesWindow", str)

    def __init__(self, parent = None):
        super(StandaloneWindow, self).__init__(parent)

        self.__folders = []
        self.__futures = []
        self.__cpucount = max(1, multiprocessing.cpu_count() - 1)
        self.__scriptdir = os.path.dirname(os.path.realpath(__file__))
        self.__config_file = os.path.join(self.__scriptdir, '{}.json'.format(os.path.splitext(os.path.basename(__file__))[0]))
        with open(self.__config_file, encoding='utf-8') as file:
            self.__config = json.loads(file.read())

        self.resize(500, 500)
        self.setAcceptDrops(True)
        self.setWindowIcon(QtGui.QIcon(':/deorder/optimizeTextures'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Vertical Layout
        verticalLayout = QtWidgets.QVBoxLayout()

        # Vertical Layout -> Merged Mod List
        self.folderList = QtWidgets.QTreeWidget()

        self.folderList.setStyleSheet("::section { background-color:rgb(220, 220, 220); }")

        self.folderList.setColumnCount(1)
        self.folderList.setRootIsDecorated(False)

        self.folderList.setDragEnabled(True)
        self.folderList.setAcceptDrops(True)
        self.folderList.setDropIndicatorShown(True)
        self.folderList.setAlternatingRowColors(True)
        self.folderList.setDragDropOverwriteMode(False)
        self.folderList.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)

        self.folderList.header().setVisible(True)
        self.folderList.headerItem().setText(0, self.__tr("Folder"))

        self.folderList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folderList.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.folderList.customContextMenuRequested.connect(self.openFolderMenu)

        verticalLayout.addWidget(self.folderList)

        # Vertical Layout -> Button Layout
        buttonLayout = QtWidgets.QHBoxLayout()

        # Vertical Layout -> Button Layout -> Refresh Button
        refreshButton = QtWidgets.QPushButton(self.__tr("&Refresh"), self)
        refreshButton.setIcon(QtGui.QIcon(':/MO/gui/refresh'))
        refreshButton.clicked.connect(self.refreshFolderList)
        buttonLayout.addWidget(refreshButton)

        # Vertical Layout -> Button Layout -> Close Button
        closeButton = QtWidgets.QPushButton(self.__tr("&Close"), self)
        closeButton.clicked.connect(self.close)
        buttonLayout.addWidget(closeButton)

        verticalLayout.addLayout(buttonLayout)

        # Vertical Layout
        self.setLayout(verticalLayout)

        self.refreshFolderList()

    def addFolderListItemByPath(self, path):
        folder = {'path': path}
        item = QtWidgets.QTreeWidgetItem(self.folderList, [path])
        item.setData(0, Qt.UserRole, {"folder": folder})
        self.folderList.addTopLevelItem(item)

        source = path
        config = self.__config
        params = {'scriptdir': self.__scriptdir}

        files = Ot.scantree_generator(path)
        entries = Ot.entries_enumerate_generator('info', config['recipes'], files)

        max_workers = int(Template(str(config['tools']['info']['threads'])).safe_substitute(cpucount = self.__cpucount))
        with concurrent.futures.ThreadPoolExecutor(max_workers = max_workers) as executor:
            for entry in entries:
                def done_callback(parent, future):
                    info = future.result()
                    print(info)
                    child = QtWidgets.QTreeWidgetItem(parent, [info['subpath']])
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setData(0, Qt.UserRole, {"info": info})
                    child.setCheckState(0, Qt.Checked)            
                future = executor.submit(Ot.info_task, config, source, entry, {**params})
                future.add_done_callback(functools.partial(done_callback, item))

        #self.folderList.resizeColumnToContents(0)

    def removeFolderListItem(self, item):
        #data = item.data(0, Qt.UserRole)
        #folder = data['folder']
        root = self.folderList.invisibleRootItem()
        (item.parent() or root).removeChild(item)

    def openFolderMenu(self, position):
        selectedItems = self.folderList.selectedItems()
        if selectedItems:
            menu = QtWidgets.QMenu()

            removeAction = QtWidgets.QAction(self.__tr('&Remove'), self)
            removeAction.setEnabled(True)
            menu.addAction(removeAction)

            action = menu.exec_(self.folderList.mapToGlobal(position))

            if action == removeAction:
                for item in selectedItems:
                    self.removeFolderListItem(item)
                    
    def refreshFolderList(self):
        self.folderList.clear()
        for folder in self.__folders:
            item = QtWidgets.QTreeWidgetItem(self.folderList, [folder['name']])
            item.setData(0, Qt.UserRole, {"folder": folder})
            self.folderList.addTopLevelItem(item)
        self.folderList.resizeColumnToContents(0)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls:
            if all([os.path.isdir(x.toLocalFile()) for x in event.mimeData().urls()]):
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.addFolderListItemByPath(path)

if __name__ == '__main__':
    application = QtWidgets.QApplication(sys.argv)
    window = StandaloneWindow()
    window.setWindowTitle("Optimize Textures")
    window.show()
    application.exec_()