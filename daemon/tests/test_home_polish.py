"""Native renderer contracts; no GPIO, services, microphone or network access."""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyber_ui import preview, theme
from cyber_ui.menu_renderer import CyberDesktopRenderer, DESKTOP_ROWS
from cyber_ui.draw_util import draw_text
from cyber_ui.home_icons import draw_home_wireless
import test_cyber_menu

STATE = {'wifi':{'enabled':True,'connected':True,'signal':76}, 'bluetooth':{'enabled':False}}


class HomePolishTests(unittest.TestCase):
    def renderer(self):
        board = preview.FakeBoard()
        return CyberDesktopRenderer(board, str(Path(__file__).resolve().parents[1])), board

    def test_list_is_primary_with_actual_selection_no_duplicate_hero_or_false_home_hint(self):
        renderer, board = self.renderer()
        apps = [preview.make_app('app-'+str(i), name) for i,name in enumerate(['Play MP4','Run Test','GLaDOS','Network','Audio'])]
        before = [(a.app_id,a.display_name) for a in apps]
        with patch('cyber_ui.menu_renderer.draw_text', wraps=draw_text) as text:
            renderer.render(apps, 2, battery_level=76, wireless_status=STATE)
        strings = [call.args[5] for call in text.call_args_list]
        for name in ['Play MP4','Run Test','GLaDOS','Network','Audio']:
            self.assertEqual(strings.count(name), 1)
        self.assertNotIn('4X',strings)
        self.assertNotIn('HOME',strings)  # Home label belongs to the status bar only.
        self.assertIn('TAP',strings); self.assertIn('NEXT',strings)
        self.assertIn('HOLD',strings); self.assertIn('OPEN',strings)
        self.assertFalse(any('pi@' in s or 'STOPPED' in s or 'INSTALLED' in s for s in strings))
        names = [c for c in text.call_args_list if c.args[5] in [a.display_name for a in apps]]
        self.assertLess(names[0].args[4],60, 'Applications start near the header, not below a hero')
        selected = next(c for c in names if c.args[5]=='GLaDOS')
        self.assertEqual(selected.args[6], theme.BRIGHT)
        self.assertEqual(before,[(a.app_id,a.display_name) for a in apps])
        self.assertEqual(preview.safe_area_violations(board.fb, theme),[])

    def test_viewport_keeps_order_stays_still_and_wraps_with_real_selection(self):
        renderer,_ = self.renderer()
        self.assertEqual(DESKTOP_ROWS,7)
        for count in (3,5,7,11,30):
            renderer._home_start = 0
            previous = list(range(min(count,7)))
            for selected in range(count):
                rows = renderer._visible_rows(count,selected)
                self.assertIn(selected,rows)
                self.assertEqual(rows,list(range(rows[0],rows[-1]+1)))
                if selected in previous:
                    self.assertEqual(rows,previous)
                previous=rows
            self.assertEqual(renderer._visible_rows(count,0),list(range(min(count,7))))
        self.assertEqual(renderer._visible_rows(11,10),list(range(4,11)))

    def test_all_counts_selection_states_long_names_and_empty_fit_native_safe_area(self):
        renderer,board = self.renderer()
        for count in (0,1,3,5,7,11):
            apps=[preview.make_app('app-'+str(i), 'Long application name that must be fitted' if i==2 else 'Application '+str(i)) for i in range(count)]
            for selected in range(max(1,count)):
                renderer.render(apps, selected, battery_level=100, wireless_status=STATE)
                self.assertEqual(board.fb.shape,(280,240,3))
                self.assertEqual(preview.safe_area_violations(board.fb,theme),[],(count,selected))

    def test_home_percentage_only_clock_and_fixed_radio_alignment(self):
        renderer,_ = self.renderer()
        from cyber_ui.statusbar import draw_text as header_text
        for battery,expected in [(0,'0%'),(9,'9%'),(76,'76%'),(100,'100%'),(None,'--%'),(-1,'--%'),(True,'--%')]:
            with patch('cyber_ui.statusbar.draw_text',wraps=header_text) as text, \
                 patch('cyber_ui.statusbar.draw_home_wireless',wraps=draw_home_wireless) as radios, \
                 patch.object(renderer.statusbar,'_battery',side_effect=AssertionError('Home must not draw a battery outline')):
                renderer.statusbar.render_home(battery,STATE,clock='19:38')
            strings=[c.args[5] for c in text.call_args_list]
            self.assertIn(expected,strings);self.assertIn('19:38',strings)
            self.assertEqual(radios.call_args.args[1],int(theme.STATUS_SAFE_RIGHT-renderer.fonts.meta_bold.width('100%')-6))

    def test_wireless_states_are_distinct_and_header_geometry_is_constant(self):
        renderer,_ = self.renderer()
        states=[STATE,{'wifi':{'enabled':False},'bluetooth':{'enabled':False}},
                {'wifi':{'enabled':True,'connected':False},'bluetooth':{'enabled':True}},
                {'wifi':{},'bluetooth':{}},
                {'wifi':{'enabled':True,'connected':True,'signal':20},'bluetooth':{'enabled':True}}]
        frames=[renderer.statusbar.render_home(76,state,clock='19:38') for state in states]
        self.assertEqual(len({f.tobytes() for f in frames}),len(states))
        for f in frames:
            self.assertEqual(f.crop((0,0,150,27)).tobytes(),frames[0].crop((0,0,150,27)).tobytes())
            self.assertEqual(f.crop((190,0,240,27)).tobytes(),frames[0].crop((190,0,240,27)).tobytes())

    def test_clock_ticks_only_home_without_forcing_more_device_reads(self):
        daemon = test_cyber_menu.DaemonIntegrationTests().make_daemon()
        daemon._last_status_poll_at = 119.5
        daemon._home_clock_minute = 1
        daemon.radio_status.updated = threading.Event()
        daemon.status_poller.refresh = Mock(return_value=False)
        daemon._render_desktop = Mock(side_effect=lambda:setattr(daemon,'_home_clock_minute',2))
        with patch('whisplay_daemon.time.time',return_value=120.1):
            daemon._refresh_status_icons()
            daemon._refresh_status_icons()
        daemon._render_desktop.assert_called_once()
        daemon.status_poller.refresh.assert_not_called()
        daemon.foreground_app_id = 'whisplay-ai-chatbot'
        with patch('whisplay_daemon.time.time',return_value=180.1):
            daemon._refresh_status_icons()
        daemon._render_desktop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
