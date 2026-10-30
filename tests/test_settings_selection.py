import unittest

from rolling_thunder.settings_selection import SettingsOption


class TestSettingsSelection(unittest.TestCase):
    def test_settings_option_order(self):
        """Test that SettingsOption enum has the correct values in the correct order."""
        expected_values = [
            "map_zoom",
            "radar",
            "callsign_info",
            "map_style",
            "reboot",
            "shutdown"
        ]

        actual_values = [option.value for option in SettingsOption]

        self.assertEqual(actual_values, expected_values)
