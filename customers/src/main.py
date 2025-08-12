import os
from common.server import AppBuilder
from common.infraestructure import initialize_database
if __name__ == "__main__":
    initialize_database("tapapear.json")
    (AppBuilder().title("Customers Api").features("customers.features").run())
