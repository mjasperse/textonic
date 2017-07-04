from PySide import QtGui, QtCore
import os, sys, time
import textonic
        
class WorkerObj(QtCore.QObject):
    finished = QtCore.Signal(str)
    progress = QtCore.Signal(str)
    preview = QtCore.Signal(str)
    
    def __init__(self):
        super(WorkerObj,self).__init__()
        self.tex = textonic.TexTonic()
        self.hasChanged = True
        self.format = 'PNG'
        self.files = {}
        
    def run(self, format=None):
        try:
            if format is not None:
                self.format = format
            if self.hasChanged:
                self.files.clear()
                self.tex.runLatex(self.data,self.progress.emit)
            dest = self.tex.convert('textonic.pdf',self.format,self.progress.emit)
            if self.format == 'PNG': self.preview.emit(os.path.join(self.tex.dir,dest))
        except Exception as E:
            self.finished.emit(str(E))
            return False
        else:
            self.finished.emit('')
            return True
        
    def toClipboard(self,fmt):
        filename = 'output.'+fmt
        if self.hasChanged:
            if not self.run(fmt): return False
        if fmt == 'PDF' and not self.tex.outline:
            filename = 'textonic.pdf'
        try:
            self.tex.clipboard(filename,fmt)
        except Exception as E:
            self.finished.emit(str(E))
            return False
        return True
        
    def cleanup(self):
        self.tex.cleanup()

class ErrHighlight(QtGui.QSyntaxHighlighter):
    def __init__(self,parent):
        super(ErrHighlight,self).__init__(parent)
        self.fmt = QtGui.QTextCharFormat()
        self.fmt.setBackground(QtCore.Qt.red)
        self.fmt.setForeground(QtCore.Qt.white)
    def highlightBlock(self,text):
        if text.startswith('!'):
            self.setFormat(0, len(text), self.fmt)
        
class LatexHighlight(QtGui.QSyntaxHighlighter):
    def __init__(self,parent):
        super(LatexHighlight,self).__init__(parent)
        self.rules = []
        # highlight rules for comments
        fmt = QtGui.QTextCharFormat()
        self.commentRule = QtCore.QRegExp(r'(?![%\\])%(?!%)')
        fmt.setForeground(QtCore.Qt.darkBlue)
        self.commentStyle = fmt
        # highlight rules for detected preamble
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(QtCore.Qt.darkRed)
        self.preambleStyle = fmt
        
    def highlightBlock(self,text):
        idx = -1
        # check for preamble instructions
        if self.previousBlockState() == -1 and text.startswith('%!'):
            self.setFormat(0, len(text), self.preambleStyle)
            idx = 1
        else:
            self.setCurrentBlockState(0)
        commentStart = -1
        while 1:
            idx = text.find('%', idx+1)
            if idx < 0: break
            if idx == 0 or text[idx-1] != '\\':
                self.setFormat(idx, len(text)-idx, self.commentStyle)
                if commentStart == -1: commentStart = idx
                break
            idx = text.find('%',idx+1)
        if commentStart == -1: commentStart = len(text)
        
class TexTonicUI(QtGui.QMainWindow):
    def __init__(self):
        super(TexTonicUI,self).__init__()
        self.setWindowTitle('TexTonic')
        self.isModified = False
        self.filename = None
        
        self.thread = QtCore.QThread()
        self.worker = WorkerObj()
        self.worker.moveToThread(self.thread)
        self.worker.finished.connect(self.workerDone)
        self.worker.progress.connect(self.addLog)
        self.worker.finished.connect(self.thread.quit)
        self.worker.preview.connect(self.newImage)
        self.thread.started.connect(self.worker.run)
        
        if not self.loadSettings(): # need worker to exist to hold settings
            QtGui.QMessageBox.critical(None, 'Error', 'Cannot find dependent applications, cannot continue')
            # we cannot quit immediately, instead we schedule a quit
            QtCore.QTimer.singleShot(0,self.close)
            return
        
        self.initUI()
        self.initMenu()
        self.initStatus()
        
        ErrHighlight(self.log)
        LatexHighlight(self.editor)
        
        self.autoTimer = QtCore.QTimer(self)
        self.autoTimer.setInterval(1000)
        self.autoTimer.timeout.connect(self.workerStart)
        self.editor.textChanged.connect(self.onChange)
        
        self.show()
        
    def checkAppExists(self,name,file,query):
        try:
            import subprocess
            subprocess.check_output([file,query],shell=False)
            return file
        except Exception as E:
            print E
            ret = QtGui.QMessageBox.question(self,'Application error',
                    'Failed to execute %s:\n%s.\n\nManually locate executable?'%(name,E),
                    QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
            if ret == QtGui.QMessageBox.Yes:
                file, filter = QtGui.QFileDialog.getOpenFileName(self,'Locate %s'%name,dir=os.path.dirname(file),filter='Applications (*.exe)')
                if len(file):
                    return self.checkAppExists(name,file,query)
        
    def initUI(self):
        self.setStyleSheet( """
            QListWidget { background: #dddddd; }
            QScrollArea { background: url('bg.png'); }
            """ )
        
        self.editor = QtGui.QTextEdit(self)
        self.log = QtGui.QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setBackgroundRole(QtGui.QPalette.Midlight)
        self.log.setWordWrapMode(QtGui.QTextOption.NoWrap)
        
        self.preview = QtGui.QLabel(self)
        self.preview.setPixmap(QtGui.QPixmap())
        scroller = QtGui.QScrollArea(self)
        scroller.setAlignment(QtCore.Qt.AlignCenter)
        scroller.setWidget(self.preview)
        scroller.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        self.scroller = scroller
        
        self.loader = QtGui.QMovie('loader.gif')
        self.loader.frameChanged.connect(self.updateIco)
        
        lrsplit = QtGui.QSplitter(self)
        lrsplit.addWidget(self.editor)
        lrsplit.addWidget(scroller)
        lrsplit.setChildrenCollapsible(False)
        lrsplit.setSizes([400,400])
        tbsplit = QtGui.QSplitter(QtCore.Qt.Vertical,self)
        tbsplit.addWidget(lrsplit)
        tbsplit.addWidget(self.log)
        tbsplit.setSizes([200,80])
        
        w = QtGui.QWidget(self)
        self.setCentralWidget(w)
        b = QtGui.QHBoxLayout(w)
        b.addWidget(tbsplit)
        
    def initMenu(self):
        menu = self.menuBar()
        m = menu.addMenu('&File')
        self.fileMenu = m
        m.addAction('&New',self.actionNew,QtGui.QKeySequence.New)
        m.addAction('&Open',self.actionOpen,QtGui.QKeySequence.Open)
        m.addSeparator()
        a = m.addAction('&Save',self.actionSave,QtGui.QKeySequence.Save)
        a.setEnabled(False)
        m.addAction('Save &As', self.actionSaveAs,QtGui.QKeySequence.SaveAs)
        m.addSeparator()
        m.addAction('&Quit',self.close,QtGui.QKeySequence.Quit)
        
        m = menu.addMenu('&Options')
        m.addAction('Render now',self.workerRun)
        act = m.addAction('Autodetect changes')
        act.setCheckable(True)
        act.setChecked(self.auto)
        act.toggled.connect(self.toggleAuto)
        m.addSeparator()
        m.addAction('Set resolution',self.setResolution)
        itm = m.addAction('Outline fonts (PDF)')
        itm.setCheckable(True)
        itm.setChecked(self.worker.tex.outline)
        itm.toggled.connect(self.toggleOutline)
        m.addSeparator()
        m.addAction('Open temp directory',self.openTempDir)
            
        m = menu.addMenu('&Help')
        m.addAction('&Website',self.website)
        m.addAction('&About',self.about,QtGui.QKeySequence.HelpContents)
        
        for s, f in [['Copy as EPS',self.copyEPS],['Copy as PDF',self.copyPDF],['Copy as bitmap',self.copyPNG],['Export file',self.saveOutput]]:
            itm = QtGui.QAction(s,self)
            itm.triggered.connect(f)
            self.scroller.addAction(itm)
        
    def initStatus(self):
        status = self.statusBar()
        self.statusicon = QtGui.QLabel(self)
        status.addWidget(self.statusicon)
        self.statusmsg = QtGui.QLabel('Ready',self)
        status.addWidget(self.statusmsg)
        
    def toggleAuto(self,val):
        self.auto = val
        if val: self.workerRun()
            
    def toggleOutline(self,val):
        self.worker.outline = val
        
    def setResolution(self):
        val, success = QtGui.QInputDialog.getInt(self, 'Resolution', 'Set raster resolution', value=self.worker.tex.res, minValue=0)
        if success:
            self.worker.tex.res = val
            self.workerStart()
        
    def openTempDir(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.worker.tex.dir))
        
    def copyEPS(self):
        self.worker.toClipboard('EPS')
    
    def copyPDF(self):
        self.worker.toClipboard('PDF')
    
    def copyPNG(self):
        self.worker.toClipboard('PNG')
    
    def saveOutput(self):
        name, filter = QtGui.QFileDialog.getSaveFileName(self,'Save output as', filter='PDF file (*.pdf);;EPS file (*.eps);;PNG image (*.png)')
        if not len(name): return
        format = filter.split(' ',1)[0]
        self.workerRun(format)
        # copy the output file
        open(name,'wb').write(open(os.path.join(self.worker.tex.dir,'output.'+format),'rb').read())
        
    def newImage(self,filename):
        if filename is None:
            self.preview.clear()
            self.preview.resize(0,0)
            return
        pix = QtGui.QPixmap(filename)
        self.preview.resize(pix.size())
        self.preview.setPixmap(pix)
        self.preview.setMask(pix.mask())
        
    def workerRun(self,format='PNG'):
        if not self.workerStart(format): return False
        QtGui.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        while self.thread.isRunning():
            QtGui.QApplication.processEvents()
        QtGui.QApplication.restoreOverrideCursor()
        return True
        
    def workerStart(self,format='PNG',redo=True):
        self.autoTimer.stop()
        if self.thread.isRunning(): return False
        data = self.editor.toPlainText()
        if not len(data): return False
        if not r'\begin{document}' in data and not r'\documentclass' in data:
            preamble = r"""
                \documentclass{article}
                \usepackage{amsmath,amssymb}
                \pagestyle{empty}
            """
            mainmatter = ''
            for l in data.split('\n'):
                if l.startswith('%!'):
                    preamble += l[2:] + '\n'
                else:
                    mainmatter += l + '\n'
            data = preamble + '\\begin{document}\n' + mainmatter + '\\end{document}\n'
        self.worker.data = data
        self.worker.format = format
        if redo: self.worker.hasChanged = True
        self.loader.start()
        self.log.clear()
        self.log.has_err = False
        self.statusmsg.setText('Processing...')
        self.thread.start()
        return True
        
    def workerDone(self,errmsg):
        self.loader.stop()
        if len(errmsg):
            self.statusmsg.setText('Error: '+errmsg)
            self.statusicon.setPixmap('err.png')
        else:
            self.statusmsg.setText('Complete')
            self.statusicon.setPixmap('success.png')
        
    def onChange(self,modified=True):
        if self.filename is None and not len(self.editor.toPlainText()):
            return
        if modified and not self.isModified:
            self.isModified = True
            # enable Save menu
            self.fileMenu.actions()[3].setEnabled(self.filename is not None)
        # start the renderer timer
        if modified and self.auto: self.autoTimer.start()
        self.worker.hasChanged = True
        self.setWindowTitle('TexTonic' + (' (*)' if modified else ''))
        
    def updateIco(self):
        self.statusicon.setPixmap(self.loader.currentPixmap())
        
    def addLog(self,s):
        c = self.log.textCursor()
        c.movePosition(QtGui.QTextCursor.End)
        if s.startswith('!'): self.log.has_err = True
        c.insertText(s+'\n')
        if not self.log.has_err: self.log.setTextCursor(c)
        QtGui.QApplication.processEvents()
        
    def website(self):
        QtGui.QDesktopServices.openUrl('http://bitbucket.org/martijnj/textonic')
        
    def about(self):
        QtGui.QMessageBox.information(self,"About",
            """<b>TexTonic</b><br>
            A simple LaTeX rendering tool<br>
            &copy; 2017 by Martijn Jasperse""")
        
    def closeEvent(self,e):
        if not self.saveChanges():
            e.ignore()
            return False
        self.thread.quit()
        self.worker.cleanup()
        self.saveSettings()
        e.accept()
        
    def saveChanges(self):
        if self.isModified:
            ret = QtGui.QMessageBox.question(self,'Save changes?','Save changes to document?', buttons=QtGui.QMessageBox.Yes|QtGui.QMessageBox.No|QtGui.QMessageBox.Cancel)
            if ret == QtGui.QMessageBox.Cancel:
                return False
            if ret == QtGui.QMessageBox.Yes:
                if not self.saveAs(self.filename):
                    return False
        return True
        
    def actionNew(self):
        if not self.saveChanges(): return False
        self.filename = None
        self.editor.setPlainText('')
        self.onChange(False)
        self.log.clear()
        self.log.has_err = False
        self.newImage(None)
        return True
        
    def actionSave(self):
        return self.actionSaveAs(self.filename)
        
    def actionSaveAs(self,name=None):
        if name is None:
            name, filter = QtGui.QFileDialog.getSaveFileName(self, 'Save file', filter='LaTeX document (*.tex)')
            if not len(name): return False
        open(name,'w').write(self.editor.toPlainText())
        self.filename = name
        self.isModified = False
        self.onChange(False)
        return True
        
    def actionOpen(self):
        if not self.saveChanges(): return False
        name, filter = QtGui.QFileDialog.getOpenFileName(self, 'Open file', filter='LaTeX document (*.tex)')
        if not len(name): return False
        self.filename = name
        self.editor.blockSignals(True)
        self.editor.setPlainText(open(name,'r').read())
        self.editor.blockSignals(False)
        self.onChange(False)
        self.workerStart()
        return True
        
    def loadSettings(self):
        self.settings = QtCore.QSettings("textonic.ini",QtCore.QSettings.IniFormat)
        self.worker.tex.res = int(self.settings.value('res',300))
        self.worker.tex.outline = self.settings.value('outline','true') == 'true'
        self.auto = self.settings.value('auto','true') == 'true'
        self.resize(self.settings.value('winsz', self.size()))
        
        latex = self.checkAppExists('PDFLatex',self.settings.value('latex',self.worker.tex.latex),'--version')
        if latex is None: return False
        else: self.worker.tex.latex = latex
        gs = self.checkAppExists('Ghostscript',self.settings.value('gs',self.worker.tex.gs),'-v')
        if gs is None: return False
        else: self.worker.tex.gs = gs
        return True
        
    def saveSettings(self):
        if getattr(self,'settings',None) is None: return
        self.settings.setValue('res',self.worker.tex.res)
        self.settings.setValue('outline',self.worker.tex.outline)
        self.settings.setValue('auto',self.auto)
        self.settings.setValue('latex',self.worker.tex.latex)
        self.settings.setValue('gs',self.worker.tex.gs)
        self.settings.setValue('winsz',self.size())
        
        
if __name__ == '__main__':
    app = QtGui.QApplication([])
    wnd = TexTonicUI()
    wnd.show()
    app.exec_()
    