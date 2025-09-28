##createBassSubSheet
from os import chdir
from os import getcwd
import os
import gspread_db
from datetime import datetime
from driveTools import getDbService



def main():
    # set all defaults
    specialRun = 'N'
    todaysDate = datetime.today().strftime('%Y.%m.%d')
    print("\nIs this a special run? (y/n) ", end="")
    specialRun = input()
    specialRun = specialRun.upper()

    db = getDbService()
    db.create_table(table_name='Users', header=['Username', 'Email'])

    print("\n============= The program has finished. ====================")
    input("Press Enter to close the terminal.")
    
if __name__ == '__main__':
    # you will need to go set up a System Enviroment varible named MIXEDNUTSLIBPATH
    #    and set it's value to the path to the MixedNutsLib folder
    #    i.e: 'C:/Users/keith/Documents/GitHub/MixedNutsLib'
    #     or whatever it is on the local computer.
    MixedNutsLib_Path = os.environ['MIXEDNUTSLIBPATH']
    chdir(MixedNutsLib_Path)
    #chdir('C:/Users/keith/Documents/GitHub/MixedNutsLib')
    print('Current working directory has been set to: ' + getcwd())
    main()
