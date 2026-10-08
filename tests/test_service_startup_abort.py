"""Stopping during startup must not create a fresh, unnotified 24-hour wait."""
import ast
import types
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'service.subtitles.kodipovilai/service.py'


class StartupAbortTests(unittest.TestCase):
    def run_main(self,abort_during_startup):
        tree=ast.parse(SOURCE.read_text('utf8'))
        node=next(row for row in tree.body if isinstance(row,ast.FunctionDef) and row.name=='main')
        monitors=[];workers=[];waits=[];publisher=Mock()
        class Monitor:
            def __init__(self):self.aborted=False;monitors.append(self)
            def abortRequested(self):return self.aborted
            def waitForAbort(self,timeout):
                waits.append((self,timeout))
                if abort_during_startup and not self.aborted:
                    raise AssertionError('New monitor missed the startup abort and waits for hours')
                return True
        namespace={name:lambda *a,**k:None for name in {
            row.func.id for row in ast.walk(node) if isinstance(row,ast.Call) and isinstance(row.func,ast.Name)
            and row.func.id.startswith('_')}}
        namespace.update(xbmc=types.SimpleNamespace(Monitor=Monitor),ADDON_ID='fixture',
                         _subs_filename_publisher=None)
        namespace['_check_first_run_marker']=lambda:False
        namespace['_is_kodi_pov_il_build']=lambda:False
        def startup_repair():
            if abort_during_startup:
                for monitor in monitors:monitor.aborted=True
        namespace['_maybe_default_pov_autoplay']=startup_repair
        for name in ('_start_he_warm_drainer','_start_subsync_drainer','_start_subsync_delay_watch',
                     '_start_service_mirror_keeper','_start_pool_queue_drainer'):
            namespace[name]=lambda monitor,name=name:workers.append((name,monitor))
        library=types.ModuleType('resources.lib')
        library.kodi_utils=types.SimpleNamespace(get_bool=lambda key,default=False:key=='use_builtin_engine')
        library.subs_filename_publisher=types.SimpleNamespace(SubsFilenamePublisher=publisher)
        library.pov_reload=types.SimpleNamespace(reload_if_patched=lambda:None)
        module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
        exec(compile(module,str(SOURCE),'exec'),namespace)
        with patch.dict('sys.modules',{'resources':types.ModuleType('resources'),'resources.lib':library}):
            namespace['main']()
        return monitors,workers,waits,publisher

    def test_abort_during_repairs_skips_late_listeners_and_long_wait(self):
        monitors,workers,waits,publisher=self.run_main(True)
        self.assertEqual(len(monitors),4)
        self.assertEqual(len(workers),3)
        self.assertEqual(waits,[])
        publisher.assert_not_called()

    def test_ordinary_startup_keeps_workers_and_original_monitor_for_main_wait(self):
        monitors,workers,waits,publisher=self.run_main(False)
        self.assertEqual(len(monitors),4)
        self.assertEqual(len(workers),5)
        self.assertEqual(waits,[(monitors[0],86400)])
        self.assertIs(workers[-1][1],monitors[0])
        self.assertIs(workers[-2][1],monitors[0])
        publisher.assert_called_once()


if __name__=='__main__':unittest.main()
