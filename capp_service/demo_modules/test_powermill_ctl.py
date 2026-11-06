import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from demo_modules import powermill_ctl as pc


class FakeBridge:
    def __init__(self, toolpaths=('A', 'B', 'C'), setups=('S1', 'S2'), alive=True, fail=None):
        self.sent, self.tp, self.su, self._alive, self.fail = [], list(toolpaths), list(setups), alive, fail

    def alive(self, timeout=4):
        return self._alive

    def execute(self, cmd, timeout=60):
        self.sent.append(cmd)
        if self.fail and cmd.startswith(self.fail[0]):
            raise self.fail[1]
        return {'success': True, 'returnCode': 0}

    def param(self, expr, timeout=20):
        for folder, items in (('Toolpath', self.tp), ('Setup', self.su)):
            if expr == f"size(folder('{folder}'))":
                return f'(int) {len(items)}'
            m = re.match(rf"folder\('{folder}'\)\[(\d+)\]\.Name", expr)
            if m:
                return f'(string) {items[int(m.group(1))]}'
        raise AssertionError(expr)


def win(running=True, project='x', dirty=False, dialogs=()):
    return lambda: {'running': running, 'title': 't', 'dialogs': list(dialogs), 'project': project, 'dirty': dirty}


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'work'
        self.src = Path(self.tmp.name) / 'src'
        self.src.mkdir()
        (self.src / 'p.pmlprj').write_text('x')
        (self.src / 'lockfile').write_text('x')
        self._orig = pc.pick_source
        pc.pick_source = lambda run=None: (self.src, 'run one', 'run one')

    def tearDown(self):
        pc.pick_source = self._orig
        self.tmp.cleanup()

    def test_title(self):
        self.assertEqual(pc.parse_title('Autodesk PowerMill Ultimate 2020    [ Editable Project * before_pZ ]    '),
                         {'project': 'before_pZ', 'dirty': True})
        self.assertEqual(pc.parse_title('Autodesk PowerMill [ Editable Project name ]'),
                         {'project': 'name', 'dirty': False})
        self.assertEqual(pc.parse_title('Autodesk PowerMill'), {'project': None, 'dirty': False})

    def test_working_copy_is_fresh_and_safe(self):
        d = pc.make_working_copy(self.src, 'run one', root=self.root, now=datetime(2026, 1, 1, 1, 2, 3))
        self.assertTrue((d / 'p.pmlprj').exists())
        self.assertFalse((d / 'lockfile').exists())
        self.assertEqual(d.parent, self.root)
        d2 = pc.make_working_copy(self.src, 'run one', root=self.root, now=datetime(2026, 1, 1, 1, 2, 3))
        self.assertNotEqual(d, d2)
        self.assertTrue((self.src / 'lockfile').exists())   # source untouched

    def test_prune_keeps_recent(self):
        for i in range(6):
            pc.make_working_copy(self.src, 'r', root=self.root, now=datetime(2026, 1, 1, 1, 2, i))
        self.assertLessEqual(len(list(self.root.iterdir())), pc.KEEP_COPIES)

    def test_protected_paths(self):
        self.assertTrue(pc.is_protected(pc.SAVED_PROTECTED[0] / 'x'))
        self.assertTrue(pc.is_protected(pc.SAVED_PROTECTED[1]))
        self.assertFalse(pc.is_protected(pc.WORK_ROOT / 'a'))
        self.assertTrue(str(pc.WORK_ROOT).endswith('powermill_working'))

    def test_open_ok_sequence(self):
        b = FakeBridge()
        r = pc.open_program(bridge=b, window=win(project=None), root=self.root)
        self.assertTrue(r['ok'])
        self.assertEqual((r['toolpaths'], r['setups']), (3, ['S1', 'S2']))
        self.assertTrue(b.sent[0].startswith("PROJECT OPEN '"))
        self.assertNotIn('PROJECT SAVE', b.sent)
        self.assertFalse(any('DELETE' in c for c in b.sent))
        self.assertIn('ACTIVATE SETUP "S1"', b.sent)
        self.assertEqual(b.sent[-1], 'ROTATE TRANSFORM ISO1')

    def test_open_refuses_dirty_foreign_project(self):
        b = FakeBridge()
        with self.assertRaises(pc.PmError) as e:
            pc.open_program(bridge=b, window=win(project='mine', dirty=True), root=self.root)
        self.assertEqual(e.exception.code, 'unsaved_changes')
        self.assertEqual(b.sent, [])

    def test_open_dialog_waiting(self):
        b = FakeBridge()
        with self.assertRaises(pc.PmError) as e:
            pc.open_program(bridge=b, window=win(dialogs=['Bridge Exception']), root=self.root)
        self.assertEqual(e.exception.code, 'dialog_waiting')
        self.assertEqual(b.sent, [])

    def test_open_bridge_down(self):
        with self.assertRaises(pc.PmError) as e:
            pc.open_program(bridge=FakeBridge(alive=False), window=win(), root=self.root)
        self.assertEqual(e.exception.code, 'bridge_not_answering')

    def test_open_timeout_not_retried(self):
        b = FakeBridge(fail=('PROJECT OPEN', pc.BridgeTimeout('x')))
        with self.assertRaises(pc.PmError) as e:
            pc.open_program(bridge=b, window=win(project=None), root=self.root)
        self.assertEqual(e.exception.code, 'dialog_waiting')
        self.assertEqual(len([c for c in b.sent if c.startswith('PROJECT OPEN')]), 1)

    def test_dirty_working_copy_saved_first(self):
        d = pc.make_working_copy(self.src, 'run one', root=self.root)
        orig = pc.WORK_ROOT
        pc.WORK_ROOT = self.root
        try:
            b = FakeBridge()
            pc.open_program(bridge=b, window=win(project=d.name, dirty=True), root=self.root)
        finally:
            pc.WORK_ROOT = orig
        self.assertEqual(b.sent[0], 'PROJECT SAVE')
        self.assertTrue(b.sent[1].startswith('PROJECT OPEN'))

    def test_show_toolpath_validates(self):
        b = FakeBridge()
        r = pc.show_toolpath('B', bridge=b, window=win())
        self.assertEqual((r['index'], r['total']), (1, 3))
        self.assertEqual(b.sent, ['ACTIVATE TOOLPATH "B"'])
        for bad in ('Z', 'B" ; DELETE TOOLPATH ALL', '', None):
            with self.assertRaises(pc.PmError):
                pc.show_toolpath(bad, bridge=b, window=win())
        self.assertEqual(len(b.sent), 1)

    def test_recalculate_only_working_copy(self):
        with self.assertRaises(pc.PmError) as e:
            pc.recalculate('A', bridge=FakeBridge(), window=win(project='founders'))
        self.assertEqual(e.exception.code, 'not_working_copy')

    def test_recalculate_ok_and_timeout(self):
        d = pc.make_working_copy(self.src, 'r', root=self.root)
        orig = pc.WORK_ROOT
        pc.WORK_ROOT = self.root
        try:
            b = FakeBridge()
            r = pc.recalculate('A', bridge=b, window=win(project=d.name))
            self.assertEqual(r['status'], 'done')
            self.assertEqual(b.sent, ['ACTIVATE TOOLPATH "A"', 'EDIT TOOLPATH "A" CALCULATE'])
            b2 = FakeBridge(fail=('EDIT TOOLPATH', pc.BridgeTimeout('x')))
            self.assertEqual(pc.recalculate('A', bridge=b2, window=win(project=d.name))['status'], 'still_running')
        finally:
            pc.WORK_ROOT = orig

    def test_status_states(self):
        self.assertEqual(pc.status(FakeBridge(), win(running=False))['state'], 'not_running')
        self.assertEqual(pc.status(FakeBridge(), win(dialogs=['Bridge Exception']))['state'], 'dialog_waiting')
        self.assertEqual(pc.status(FakeBridge(alive=False), win())['state'], 'bridge_not_answering')
        s = pc.status(FakeBridge(), win())
        self.assertEqual((s['state'], s['toolpaths']), ('ready', 3))

    def test_error_payload(self):
        self.assertEqual(pc.PmError('x', 'm').payload(), {'ok': False, 'status': 'x', 'error': 'm'})


if __name__ == '__main__':
    unittest.main()
