"""Logic regressions extracted from the actual widget methods.

The Qt responses below are fakes: these tests do not establish rendered-button,
mouse, Slicer-runtime or Windows acceptance. Native dialog checks are separate.
"""
import ast
from collections import deque
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from MeniscusAnnotatorLib.core import ValidationError


def widget_method(name, **globals_override):
    """Compile the real method without importing the unavailable Slicer GUI."""
    source = REPO / 'MeniscusAnnotator.py'
    module = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
    widget = next(node for node in module.body
                  if isinstance(node, ast.ClassDef) and node.name == 'MeniscusAnnotatorWidget')
    method = next(node for node in widget.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'Path': Path, 'ValidationError': ValidationError, **globals_override}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[name]


@pytest.fixture
def dialogs():
    replies = deque()
    readers = deque()
    requested_readers = []
    shown = []

    class MessageBox:
        Yes = 0x4000
        No = 0x10000

        def __init__(self, parent):
            self.parent = parent
            self.default = None
            self.standard = None
            self.title = self.text = self.informative = ''
            shown.append(self)

        def setWindowTitle(self, value): self.title = value
        def setText(self, value): self.text = value
        def setInformativeText(self, value): self.informative = value
        def setStandardButtons(self, value): self.standard = value
        def setDefaultButton(self, value): self.default = value

        def exec_(self):
            assert self.standard == self.Yes | self.No
            assert self.default == self.No, 'Every consent dialog must default to No.'
            return replies.popleft() if replies else self.default

    qt = SimpleNamespace(QMessageBox=MessageBox)
    slicer = SimpleNamespace(util=SimpleNamespace(mainWindow=lambda: None))
    method = widget_method('_confirmDatasetStart', qt=qt, slicer=slicer)
    def choose(previous):
        requested_readers.append(previous)
        return readers.popleft() if readers else None
    widget = SimpleNamespace(_chooseReaderIdentity=choose)
    return SimpleNamespace(replies=replies, readers=readers, requested_readers=requested_readers,
                           widget=widget, shown=shown, box=MessageBox,
                           confirm=lambda job, previous='': method(widget, job, previous))


def test_missing_job_defaults_to_no_before_reader_prompt(dialogs):
    assert dialogs.confirm(None) is False
    assert len(dialogs.shown) == 1
    assert dialogs.shown[0].objectName == 'MeniscusBlankStartDialog'
    assert 'empty labels' in dialogs.shown[0].text
    assert 'expected existing automated masks' in dialogs.shown[0].informative


@pytest.mark.parametrize('answer', [0, 0x10000])
def test_cancel_or_no_on_blank_warning_stops_before_actor_prompt(dialogs, answer):
    dialogs.replies.append(answer)
    assert dialogs.confirm(None) is False
    assert [box.objectName for box in dialogs.shown] == ['MeniscusBlankStartDialog']


def test_intentional_blank_requires_second_explicit_reader_confirmation(dialogs):
    dialogs.replies.append(dialogs.box.Yes)
    assert dialogs.confirm(None) is False
    assert len(dialogs.shown) == 1
    assert dialogs.requested_readers == ['']
    assert dialogs.widget._confirmedReader is None


def test_intentional_legacy_blank_can_continue_after_both_confirmations(dialogs):
    dialogs.replies.append(dialogs.box.Yes)
    dialogs.readers.append('Synthetic Reader')
    assert dialogs.confirm(None) is True
    assert len(dialogs.shown) == 1
    assert dialogs.widget._confirmedReader == 'Synthetic Reader'


def test_named_reader_is_shown_and_requires_yes(dialogs):
    job = {'annotator': 'Synthetic Reader B'}
    dialogs.replies.append(dialogs.box.Yes)
    assert dialogs.confirm(job) is True
    assert len(dialogs.shown) == 1
    assert dialogs.shown[0].objectName == 'MeniscusReaderConfirmDialog'
    assert dialogs.shown[0].text.endswith('Synthetic Reader B')
    assert dialogs.widget._confirmedReader == 'Synthetic Reader B'


def test_named_reader_confirmation_defaults_to_no(dialogs):
    assert dialogs.confirm({'annotator': 'Synthetic Reader B'}) is False
    assert len(dialogs.shown) == 1


def test_legacy_assignment_is_explicitly_confirmed(dialogs):
    assert dialogs.confirm({'cases': {}}) is False
    assert not dialogs.shown
    assert dialogs.requested_readers == ['']
    dialogs.readers.append('Synthetic Reader C')
    assert dialogs.confirm({'cases': {}}, 'Synthetic Reader B') is True
    assert dialogs.requested_readers[-1] == 'Synthetic Reader B'
    assert dialogs.widget._confirmedReader == 'Synthetic Reader C'


@pytest.mark.parametrize('actor_type,actor', [
    ('automated', 'Software QA (automated)'),
    ('human_unverified', 'Preview user (identity unverified)'),
])
def test_explicit_software_practice_needs_no_reader_or_blank_dialog(dialogs, actor_type, actor):
    job = {'practice_context': {'purpose': 'software_practice',
                                'actor_type': actor_type, 'actor': actor}}
    assert dialogs.confirm(job) is True
    assert dialogs.shown == []


def test_cancelled_dataset_confirmation_creates_no_store_or_settings(tmp_path):
    messages, events = [], []
    dataset = SimpleNamespace(identity='SYNTHETIC-IDENTITY',
                              cases=[SimpleNamespace(metadata={'dataset_version': 'SYNTHETIC-V1'})])
    qt = SimpleNamespace(
        Qt=SimpleNamespace(WaitCursor=1),
        QEventLoop=SimpleNamespace(ExcludeUserInputEvents=2),
        QApplication=SimpleNamespace(setOverrideCursor=lambda cursor: None,
                                      restoreOverrideCursor=lambda: None),
        QStandardPaths=SimpleNamespace(DocumentsLocation=3,
                                       writableLocation=lambda _: str(tmp_path)),
    )
    slicer = SimpleNamespace(app=SimpleNamespace(processEvents=lambda *args: None))

    def forbidden_store(*args, **kwargs):
        pytest.fail('Cancel must return before WorkStore creates any work.')

    method = widget_method('openDataset', qt=qt, slicer=slicer,
                           Dataset=lambda *args, **kwargs: dataset,
                           load_dataset_job_config=lambda *args, **kwargs: (None, None),
                           WorkStore=forbidden_store)
    widget = SimpleNamespace(_practiceConfig=None,
                             message=SimpleNamespace(setText=messages.append),
                             settings=SimpleNamespace(value=lambda key, default: default,
                                                      setValue=lambda *args: events.append(args)),
                             _confirmDatasetStart=lambda job, previous: False)
    assert method(widget, tmp_path / 'Synthetic dataset',
                  work_root=str(tmp_path / 'Separate work')) is None
    assert events == []
    assert messages[-1] == 'Opening cancelled. No new annotation work was created.'
    assert not (tmp_path / 'Separate work').exists()


def navigation_widget(current=None, blocked=(), no_job=False):
    cases = [SimpleNamespace(key=key) for key in ('A', 'B', 'C', 'D')]
    opened, messages = [], []
    job = None if no_job else {'cases': {
        case.key: {'availability': 'unresolved' if case.key in blocked else 'ready'}
        for case in cases}}
    widget = SimpleNamespace(dataset=SimpleNamespace(cases=cases),
                             store=SimpleNamespace(job=job),
                             session=SimpleNamespace(case=SimpleNamespace(key=current)) if current else None,
                             openCase=opened.append, _safe=lambda action: action(),
                             message=SimpleNamespace(setText=messages.append))
    return widget, opened, messages


def test_next_case_skips_blocked_successor_without_resetting_to_first():
    widget, opened, _ = navigation_widget(current='B', blocked=('C',))
    widget_method('_nextCase')(widget)
    assert opened == ['D']


def test_next_case_skips_multiple_blocked_cases_in_order():
    widget, opened, _ = navigation_widget(current='A', blocked=('B', 'C'))
    widget_method('_nextCase')(widget)
    assert opened == ['D']


def test_next_case_wraps_to_first_available_after_last():
    widget, opened, _ = navigation_widget(current='D', blocked=('A',))
    widget_method('_nextCase')(widget)
    assert opened == ['B']


def test_next_case_with_no_active_case_opens_first_available():
    widget, opened, _ = navigation_widget(blocked=('A', 'B'))
    widget_method('_nextCase')(widget)
    assert opened == ['C']


def test_next_case_without_job_retains_legacy_order():
    widget, opened, _ = navigation_widget(current='B', no_job=True)
    widget_method('_nextCase')(widget)
    assert opened == ['C']


def test_all_blocked_cases_show_message_without_opening_any():
    widget, opened, messages = navigation_widget(current='B', blocked=('A', 'B', 'C', 'D'))
    widget_method('_nextCase')(widget)
    assert opened == []
    assert messages == ['No available case. All starting masks are blocked.']


def test_blocked_manual_open_preserves_current_case_instead_of_resetting():
    widget, opened, _ = navigation_widget(current='B', blocked=('C',))
    original_session = widget.session
    closed = []
    widget.closeCase = lambda: closed.append(True)
    with pytest.raises(ValidationError, match='blocked; no blank'):
        widget_method('openCase')(widget, 'C')
    assert closed == [] and widget.session is original_session and opened == []
