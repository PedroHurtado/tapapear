from common.server import AppBuilder
from common.infraestructure import initialize_database

app =None

def main():
    global app
    initialize_database("tapapear.json")    
    builder = AppBuilder().build()
    app = builder.app
    builder.run()

if __name__ == '__main__':  
    main()    


