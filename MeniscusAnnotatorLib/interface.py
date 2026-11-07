"""Small, code-drawn interface assets; no external icon/runtime dependency."""
import tempfile
from pathlib import Path
import qt

_cache = None

def checkmark_path():
    global _cache
    if _cache is None:
        _cache = tempfile.TemporaryDirectory(prefix='meniscus-ui-')
        Path(_cache.name, 'checked.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18"><path d="M4 9l3.2 3.2L14 5.5" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding='utf-8')
    return Path(_cache.name, 'checked.svg').as_posix()

def icon(name, color='#425363', size=20):
    pix = qt.QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.)
    pix.fill(qt.Qt.transparent)
    p = qt.QPainter(pix)
    p.setRenderHint(qt.QPainter.Antialiasing, True)
    p.scale(size / 24., size / 24.)
    pen = qt.QPen(qt.QColor(color), 1.7)
    pen.setCapStyle(qt.Qt.RoundCap)
    pen.setJoinStyle(qt.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(qt.QBrush())
    def line(a,b,c,d): p.drawLine(qt.QPointF(a,b),qt.QPointF(c,d))
    def path(points, closed=False):
        q = qt.QPainterPath(); q.moveTo(*points[0])
        for point in points[1:]: q.lineTo(*point)
        if closed: q.closeSubpath()
        p.drawPath(q)
    if name in ('previous','next'):
        path([(14,5),(7,12),(14,19)] if name=='previous' else [(9,5),(16,12),(9,19)])
    elif name == 'folder':
        path([(3,6),(9,6),(11,8),(21,8),(21,19),(3,19)],True)
    elif name in ('cases','tools'):
        p.drawRoundedRect(qt.QRectF(3,4,18,16),2,2)
        line(9 if name=='cases' else 15,4,9 if name=='cases' else 15,20)
    elif name == 'save':
        path([(4,3),(17,3),(21,7),(21,21),(3,21),(3,3)],True)
        p.drawRect(qt.QRectF(8,3,8,6)); p.drawRect(qt.QRectF(7,14,10,7))
    elif name == 'check': path([(4,12),(9,17),(20,6)])
    elif name == 'flag':
        line(5,21,5,3); path([(5,4),(19,4),(16,8),(19,12),(5,12)])
    elif name == 'draw':
        path([(5,18),(6,6),(18,4),(20,17)],True)
        for x,y in [(5,18),(6,6),(18,4),(20,17)]: p.drawRect(qt.QRectF(x-1.5,y-1.5,3,3))
    elif name == 'paint':
        path([(5,16),(15,4),(20,8),(10,20),(5,20)],True); line(13,6,18,10)
    elif name == 'erase':
        path([(3,14),(13,4),(21,12),(12,21),(10,21)],True); line(8,9,16,17); line(12,21,21,21)
    elif name in ('undo','redo'):
        if name == 'redo': p.translate(24,0); p.scale(-1,1)
        path([(9,5),(4,10),(9,15)]); path([(4,10),(15,10),(19,13),(19,19)])
    elif name == 'help':
        p.drawEllipse(qt.QRectF(3,3,18,18)); path([(9,8),(10,6),(14,6),(16,9),(12,12),(12,14)]); line(12,17,12,17.2)
    elif name == 'export':
        path([(4,12),(4,20),(20,20),(20,12)]); line(12,15,12,3); path([(7,8),(12,3),(17,8)])
    elif name == 'resume':
        p.drawEllipse(qt.QRectF(3,3,18,18)); path([(10,7),(16,12),(10,17)],True)
    elif name == 'reset':
        path([(5,8),(5,3),(10,3)]); p.drawArc(qt.QRectF(4,4,16,16),35*16,290*16)
    elif name == 'dot':
        p.setBrush(qt.QBrush(qt.QColor(color))); no_pen = qt.QPen(); no_pen.setStyle(qt.Qt.NoPen); p.setPen(no_pen); p.drawEllipse(qt.QRectF(5,5,14,14))
    p.end()
    return qt.QIcon(pix)

class EmptyCanvas(qt.QWidget):
    """A quiet first-use prompt inside the real native image viewport."""
    def __init__(self, parent, workflow):
        super().__init__(parent)
        self.workflow = workflow
        self.setFixedSize(350,160)
        self.setStyleSheet('QWidget { background:transparent; color:#a9b9c5; font-size:11pt; } QLabel#emptyTitle { color:#d9e3ea; font-size:14pt; font-weight:600; } QPushButton { background:#246d98; color:white; border:0; border-radius:4px; min-height:32px; padding:5px 18px; } QPushButton:hover { background:#327fab; } QPushButton:focus { border:2px solid #d6eaf7; }')
        layout = qt.QVBoxLayout(self)
        layout.setAlignment(qt.Qt.AlignCenter)
        layout.setSpacing(12)
        self.title = qt.QLabel('Open a dataset')
        self.title.objectName = 'emptyTitle'
        self.title.setAlignment(qt.Qt.AlignCenter)
        layout.addWidget(self.title)
        self.detail = qt.QLabel('Choose the complete dataset folder to view scans.')
        self.detail.setAlignment(qt.Qt.AlignCenter)
        self.detail.wordWrap = True
        layout.addWidget(self.detail)
        self.button = qt.QPushButton('Open dataset')
        self.button.setIcon(icon('folder','#ffffff'))
        self.button.connect('clicked()',self.open)
        layout.addWidget(self.button,0,qt.Qt.AlignCenter)
        parent.installEventFilter(self)
        self.place()

    def place(self):
        parent = self.parentWidget()
        self.move(max(0,(parent.width-self.width)//2),max(0,(parent.height-self.height)//2))

    def eventFilter(self, watched, event):
        if event.type()==qt.QEvent.Resize: self.place()
        return False

    def ready(self, has_dataset):
        self.title.setText('Choose a case' if has_dataset else 'Open a dataset')
        self.detail.setText('Select a case in the list to start annotating.' if has_dataset else 'Choose the complete dataset folder to view scans.')
        self.button.setText('Open selected case' if has_dataset else 'Open dataset')
        self.place()
        self.show()

    def open(self):
        if self.workflow.dataset:
            self.workflow._openRow(self.workflow.caseTable.currentRow(),0)
        else:
            self.workflow._chooseDataset()
