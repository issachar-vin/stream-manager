from .app import StreamManagerApp
from .config.config_manager import ConfigManager
from .ui.main_window import MainWindow


def main() -> None:
    config = ConfigManager()
    app = StreamManagerApp(config)
    MainWindow(app).run()


if __name__ == "__main__":
    main()
