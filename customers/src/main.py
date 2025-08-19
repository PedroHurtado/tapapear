from common.server import AppBuilder
from common.infraestructure import initialize_database

def main():       
    initialize_database("tapapear.json")
    AppBuilder().run()
if __name__ == "__main__":
    main()
