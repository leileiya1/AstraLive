import errno
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from app.local_listener import ListenerSettings, PrivateSocket, private_parent

class ListenerConfigTests(unittest.TestCase):
    def test_windows_loopback_selection(self):
        with patch.dict(os.environ, {'ASTRALIVE_LOCAL_TRANSPORT':'tcp','ASTRALIVE_LOCAL_FALLBACK':'disabled','AI_RUNTIME_URL':'http://127.0.0.1:8000'},clear=True):
            self.assertEqual(ListenerSettings.from_env(platform='win32').mode,'tcp')
            os.environ['ASTRALIVE_LOCAL_TRANSPORT']='uds'
            with self.assertRaises(ValueError):ListenerSettings.from_env(platform='win32')
            os.environ['ASTRALIVE_LOCAL_FALLBACK']='tcp'
            self.assertEqual(ListenerSettings.from_env(platform='win32').mode,'tcp')
    def test_no_public_listener_or_auto(self):
        for target in ('http://0.0.0.0:8000','http://example.org:8000','http://127.0.0.1:8000/x','http://user:pass@127.0.0.1:8000'):
            with patch.dict(os.environ, {'AI_RUNTIME_URL':target}, clear=True):
                with self.assertRaises(ValueError):ListenerSettings.from_env()
        with patch.dict(os.environ, {'ASTRALIVE_LOCAL_TRANSPORT':'auto'},clear=True):
            with self.assertRaises(ValueError):ListenerSettings.from_env()
    def test_path_length(self):
        with patch.dict(os.environ, {'ASTRALIVE_LOCAL_TRANSPORT':'uds','ASTRALIVE_RUNTIME_UDS_PATH':'/'+ 'x'*104},clear=True):
            with self.assertRaises(ValueError):ListenerSettings.from_env(platform='linux')

@unittest.skipUnless(sys.platform in {'linux','darwin'},'Unix lifecycle only')
class SocketLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='al-ipc-',dir=os.path.realpath(tempfile.gettempdir()))
        self.root=Path(self.tmp.name);self.root.chmod(0o700);self.path=str(self.root/'r.sock')
    def tearDown(self):self.tmp.cleanup()
    def test_mode_lock_and_cleanup(self):
        with PrivateSocket(self.path):
            self.assertEqual(stat.S_IMODE(os.lstat(self.path).st_mode),0o600)
            with self.assertRaisesRegex(RuntimeError,'lock already held'):
                with PrivateSocket(self.path):pass
        self.assertFalse(Path(self.path).exists())
        self.assertTrue(Path(self.path+'.lock').exists())
    def test_stale_recorded_socket(self):
        # Emulate kernel closing socket+lock on SIGKILL; real kill also covered by Go process test.
        owner=PrivateSocket(self.path);owner.__enter__();owner.sock.close();os.close(owner.fd);owner.fd=None
        with PrivateSocket(self.path):pass
        self.assertFalse(Path(self.path).exists())
    def test_unknown_owned_socket_preserved(self):
        s=socket.socket(socket.AF_UNIX);s.bind(self.path);os.chmod(self.path,0o600);s.close()
        with self.assertRaisesRegex(PermissionError,'lifecycle record'):
            with PrivateSocket(self.path):pass
        self.assertTrue(Path(self.path).exists())
    def test_live_socket_record_preserved(self):
        s=socket.socket(socket.AF_UNIX);s.bind(self.path);os.chmod(self.path,0o600);s.listen(1)
        info=os.lstat(self.path);Path(self.path+'.lock').write_text(json.dumps({'device':info.st_dev,'inode':info.st_ino}));os.chmod(self.path+'.lock',0o600)
        try:
            with self.assertRaisesRegex(RuntimeError,'is live'):
                with PrivateSocket(self.path):pass
        finally:s.close()
        self.assertTrue(Path(self.path).exists())
    def test_regular_file_symlink_and_parent_permissions(self):
        Path(self.path).write_text('preserve')
        with self.assertRaises(PermissionError):
            with PrivateSocket(self.path):pass
        self.assertEqual(Path(self.path).read_text(),'preserve');Path(self.path).unlink()
        target=self.root/'target';target.write_text('preserve');Path(self.path).symlink_to(target)
        with self.assertRaises(PermissionError):
            with PrivateSocket(self.path):pass
        self.assertEqual(target.read_text(),'preserve');Path(self.path).unlink()
        self.root.chmod(0o777)
        with self.assertRaises(PermissionError):
            with PrivateSocket(self.path):pass
        self.root.chmod(0o700)
    def test_lock_symlink_and_socket_replacement_preserved(self):
        target=self.root/'target';target.write_text('preserve');Path(self.path+'.lock').symlink_to(target)
        with self.assertRaises(OSError):
            with PrivateSocket(self.path):pass
        self.assertEqual(target.read_text(),'preserve');Path(self.path+'.lock').unlink()
        with PrivateSocket(self.path):
            Path(self.path).unlink();Path(self.path).write_text('replacement')
        self.assertEqual(Path(self.path).read_text(),'replacement')
    def test_unowned_socket_preserved(self):
        if os.geteuid()!=0:self.skipTest('requires isolated root to create unowned inode; run on Linux root test')
        s=socket.socket(socket.AF_UNIX);s.bind(self.path);s.close();os.chmod(self.path,0o600);os.chown(self.path,65534,65534)
        with self.assertRaises(PermissionError):
            with PrivateSocket(self.path):pass
        self.assertTrue(Path(self.path).exists())
