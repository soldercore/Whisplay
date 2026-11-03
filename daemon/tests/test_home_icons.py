"""Home-only visual contracts with real Pillow sprites and renderer output."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import ImageOps
from cyber_ui import preview, theme
from cyber_ui.menu_renderer import CyberDesktopRenderer
from cyber_ui.home_icons import APP_ICONS, application_icon, _wifi_sprite, _bluetooth_sprite, _app_sprite
from cyber_ui.draw_util import draw_text


class HomeIconsTests(unittest.TestCase):
    def test_every_known_app_has_a_distinct_icon_and_unknown_ids_share_bounded_generic_cache(self):
        sprites=[application_icon(app_id) for app_id in APP_ICONS]
        self.assertEqual(len(sprites),11)
        self.assertEqual(len({s.tobytes() for s in sprites}),11)
        for sprite in sprites:
            self.assertEqual(sprite.size,(16,16));self.assertIsNotNone(sprite.getbbox())
        generic=application_icon('plugin.unknown')
        for i in range(1000):
            self.assertIs(application_icon('plugin.'+str(i)),generic)
        self.assertLessEqual(_app_sprite.cache_info().currsize,24)
        self.assertIs(application_icon('whisplay-system'),application_icon('whisplay-system'))

    def test_wifi_is_symmetric_with_centered_point_and_radio_states_stay_distinct(self):
        full=_wifi_sprite('active',3)
        self.assertEqual(full.size,(13,11))
        self.assertEqual(full.tobytes(),ImageOps.mirror(full).tobytes())
        self.assertEqual(full.getpixel((6,10))[:3],theme.GREEN)
        states=[_wifi_sprite('active',3),_wifi_sprite('active',1),_wifi_sprite('disabled',0),
                _wifi_sprite('disconnected',0),_wifi_sprite('unknown',0)]
        self.assertEqual(len({s.tobytes() for s in states}),len(states))
        bt=[_bluetooth_sprite(mode) for mode in ('active','disabled','unknown')]
        self.assertEqual(len({s.tobytes() for s in bt}),3)
        self.assertTrue(all(s.height==full.height for s in bt))

    def test_known_and_dynamic_icons_do_not_change_names_order_selection_or_safe_area(self):
        apps=[preview.make_app(key,key.replace('whisplay-','').title()) for key in APP_ICONS]
        apps.append(preview.make_app('third-party-new','Third Party With A Very Long Display Name'))
        original=[(a.app_id,a.display_name) for a in apps]
        board=preview.FakeBoard();r=CyberDesktopRenderer(board,str(Path(__file__).resolve().parents[1]))
        for selected in range(len(apps)):
            r.render(apps,selected,battery_level=100,wireless_status={'wifi':{},'bluetooth':{}})
            self.assertIn(selected,r._visible_rows(len(apps),selected))
            self.assertEqual(preview.safe_area_violations(board.fb,theme),[])
        self.assertEqual(original,[(a.app_id,a.display_name) for a in apps])

    def test_battery_uses_clock_weight_for_single_double_triple_digits_without_pictogram(self):
        r=CyberDesktopRenderer(preview.FakeBoard(),str(Path(__file__).resolve().parents[1]))
        for value in (9,55,100):
            with patch('cyber_ui.statusbar.draw_text',wraps=draw_text) as text:
                r.statusbar.render_home(value,{'wifi':{},'bluetooth':{}},clock='23:05')
            battery=next(c for c in text.call_args_list if c.args[5]==str(value)+'%')
            clock=next(c for c in text.call_args_list if c.args[5]=='23:05')
            self.assertIs(battery.args[2],clock.args[2])
            self.assertLessEqual(battery.args[3]+battery.args[2].width(battery.args[5]),theme.STATUS_SAFE_RIGHT)


if __name__=='__main__':
    unittest.main()
