from .menu import MenuApp


class DisplayApp(MenuApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-display', 'Display', 'DI', 165

    def __init__(self, *args, get_display, set_brightness, lock_screen):
        super().__init__(*args)
        self.get_display = get_display
        self.set_brightness = set_brightness
        self.lock_screen = lock_screen

    def adjust(self, amount):
        value = self.get_display().get('brightness')
        target = max(20, min(100, (100 if value is None else value) + amount))
        self.set_brightness(target)
        self.note(f'Brightness {target}%')

    def items(self):
        values = self.get_display()
        brightness = values.get('brightness')
        text = 'Unavailable' if brightness is None else f'{brightness}%'
        rgb = values.get('rgb')
        led = 'Unavailable' if rgb is None else '#%02X%02X%02X' % tuple(rgb)
        return super().items() + [
            ('Brightness +20%', 'Current ' + text, lambda: self.adjust(20)),
            ('Brightness -20%', 'Current ' + text, lambda: self.adjust(-20)),
            ('Screen off', 'Press button to wake', self.lock_screen),
            ('Lock screen', 'Press button to unlock', self.lock_screen),
            ('LED command', led, lambda: self.note('GLaDOS retains foreground LED control')),
        ]
