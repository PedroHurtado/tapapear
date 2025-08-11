import os
from common.server import AppBuilder


if __name__ == "__main__":
    (AppBuilder().with_title("customers").with_module_name("customers").run())
