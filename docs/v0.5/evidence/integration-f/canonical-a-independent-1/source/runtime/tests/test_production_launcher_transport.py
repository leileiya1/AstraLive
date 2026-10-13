"""Launcher branch checks only; RTMP preflight/lock and run are stubbed.

Real local_listener HTTP/UDS and actual Backend entrypoints are separate subprocess
integration gates. This file does not claim Linux production preflight passed.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
if os.name == "posix":
    from app import production_launcher

@unittest.skipUnless(os.name == "posix", "existing production launcher requires Unix fcntl")
class LauncherTransportTests(unittest.TestCase):
    def test_default_keeps_original_exec_and_port(self):
        opened=[]
        real_open=os.open
        def capture_open(*args,**kwargs):
            fd=real_open(*args,**kwargs)
            opened.append(fd)
            return fd
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True), \
                patch.object(production_launcher,'Path',return_value=Path(directory)/'lock'), \
                patch.object(production_launcher,'preflight_main',return_value=0), \
                patch.object(production_launcher.os,'open',side_effect=capture_open), \
                patch.object(production_launcher.os,'execv',side_effect=RuntimeError('exec captured')) as execute:
            with self.assertRaisesRegex(RuntimeError,'exec captured'):
                production_launcher.main()
            args=execute.call_args.args[1]
            self.assertEqual(args[1:],['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18000','--timeout-graceful-shutdown','25'])
            self.assertEqual(os.environ['MAX_SESSIONS'],'1')
            # Stubbed exec does not replace the process; close the inherited lock.
            os.close(opened[0])

    def test_uds_retains_lock_and_closes_after_listener(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'ASTRALIVE_LOCAL_TRANSPORT':'uds'},clear=True), \
                patch.object(production_launcher,'Path',return_value=Path(directory)/'lock'), \
                patch.object(production_launcher,'preflight_main',return_value=0), \
                patch('app.local_listener.run') as run:
            self.assertIsNone(production_launcher.main())
            run.assert_called_once_with(default_tcp_url='http://127.0.0.1:18000')

    def test_listener_failure_releases_publisher_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'ASTRALIVE_LOCAL_TRANSPORT':'uds'},clear=True), \
                patch.object(production_launcher,'Path',return_value=Path(directory)/'lock'), \
                patch.object(production_launcher,'preflight_main',return_value=0), \
                patch('app.local_listener.run',side_effect=ValueError('invalid transport')):
            with self.assertRaises(ValueError):production_launcher.main()
            import fcntl
            with open(Path(directory)/'lock','rb') as lock:
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
