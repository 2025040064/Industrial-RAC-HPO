"""Desktop presentation; all data and experiments are owned by application services."""


def launch_gui(root):
    from .main_window import launch_gui as launch

    return launch(root)
