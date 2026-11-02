from .menu import MenuApp


class NetworkApp(MenuApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-network', 'Network', 'NW', 195

    def __init__(self, *args, open_app):
        super().__init__(*args)
        self.open_app = open_app

    def items(self):
        return super().items() + [
            ('Wi-Fi', 'Status, saved networks, radio', lambda: self.open_app('whisplay-wifi')),
            ('Bluetooth', 'Status, pairing, radio', lambda: self.open_app('whisplay-bluetooth')),
        ]
