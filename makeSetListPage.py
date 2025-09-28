import time
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from datetime import datetime
import re
from os import listdir
from colorama import init
from termcolor import colored

def makeSetListPage(setId, todaysDate, destDir):
    init()  # init Colorama to make Termcolor work on Windows too
    docName = destDir + '/' + setId + "00-" + "Set Lineup." + todaysDate + ".pdf"
    print("Setlist file name: " + docName)
    doc = SimpleDocTemplate(docName,pagesize=letter,
                        rightMargin=5,leftMargin=50,
                        topMargin=5,bottomMargin=5)
    partsList=[]
       
                  
    print("\n\nItems for setlist ok? If not, go adjust manually, then ")
    input("return and press Enter to make the setlist pdf...")
    
    makePartListForDoc(partsList, setId, todaysDate, destDir)
        
    doc.build(partsList)
    
def makePartListForDoc(partsList, setId, todaysDate, destDir):
    logo = "C:/Users/keith/OneDrive/Documents/GitHub/MixedNutsLib/MixedNutsImages/LogoImage" + setId + ".jpg"
    if setId == "PAT":
      im = Image(logo, 1.875*inch, .625*inch) # Image(image, width, height) - Small image to make letlist fit page
    else:
      im = Image(logo, 7.5*inch, 2.5*inch) # Image(image, width, height)
    #im.hAlign = "CENTER"
    partsList.append(im)
     
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Revised',
                              alignment=TA_JUSTIFY,
                              textColor=colors.HexColor("#FF0000")))
    styles.add(ParagraphStyle(name='SetTitle'))
    styles.add(ParagraphStyle(name='SongListNormalStyle',
                              fontSize=12))                       
    styles.add(ParagraphStyle(name='SongListRevisedStyle',
                              fontSize=12,
                              textColor=colors.HexColor("#FF0000"))) 
    styles.add(ParagraphStyle(name='SongListLongNormalStyle',
                              fontSize=9))                       
    styles.add(ParagraphStyle(name='SongListLongRevisedStyle',
                              fontSize=9,
                              textColor=colors.HexColor("#FF0000")))   
    ptext = '<font size=24>Set %s</font>' % setId
    partsList.append(Paragraph(ptext, styles["SetTitle"]))
    partsList.append(Spacer(1, 24))

    ptext = '<font size=12><u>Last revised:  %s</u></font>' % todaysDate
    partsList.append(Paragraph(ptext, styles["Revised"]))
    partsList.append(Spacer(1, 12))

    # Create list of songs by searching the destDir for matches on the set Id and sequence 01-99

    regExPattern = setId + "0[1-9]|" + setId + "[1-9][0-9]-[^$]"  # the digit 0 (in pos 1) and 1 thru 9 (in pos 2), or the digits 1-9 (in pos 1) and 0-9 (in pos 2).
    pattern = re.compile(regExPattern)
    
    print("\nList of PFD files for setlist:  *revised today")
    print("====================================================")
    setList=[]
    destList = listdir(destDir)
    for s in destList :
            if re.match(pattern, s) :
                setList.append(s)
                
    setList.sort()
    for s in setList :
        songTitle = s
        # Check if the file name contains "$talking"
        if "$talking" in s:
            continue  # Skip this file and move to the next one
  
        if todaysDate in s :
            print("* " + s)
            if len(setList) < 37 :
                partsList.append(Paragraph(songTitle, styles["SongListRevisedStyle"]))
                partsList.append(Spacer(1, 0.05*inch))
            else:
                partsList.append(Paragraph(songTitle, styles["SongListLongRevisedStyle"]))
                partsList.append(Spacer(1, 0*inch))
        else :
            print(s)
            if len(setList) < 37 :
                partsList.append(Paragraph(songTitle, styles["SongListNormalStyle"]))
                partsList.append(Spacer(1, 0.05*inch))
            else:
                partsList.append(Paragraph(songTitle, styles["SongListLongNormalStyle"]))
                partsList.append(Spacer(1, 0*inch))
                
def main():
    print("What is the Set Id? ", end="")
    setId = input()
    print("What is the revision date in YYYY.MM.DD format? ", end="")
    todaysDate = input()
    #todaysDate = datetime.today().strftime('%Y.%m.%d')
    #todaysDate = "2019.01.14"
    markedDir = 'C:/Users/keith/OneDrive/Documents/GitHub/MixedNutsLib/Marked'
    makeSetListPage(setId, todaysDate, markedDir)

if __name__ == '__main__':
    main()

