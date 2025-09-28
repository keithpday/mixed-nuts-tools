import PyPDF2, os
from os import listdir
from datetime import datetime
import re

def makeBook(setId, todaysDate, srcDir, destDir, zzSetId):
    if zzSetId == "None":
        bookName = destDir + "/" + setId + " Book." + todaysDate + ".pdf"
    else:
        bookName = destDir + "/" + zzSetId + " Book." + todaysDate + ".pdf"
    print("\nBook file name: " + bookName)

    pdfFiles = []
    # Create list of songs by searching the srcDir for matches on the set Id and sequence 00-99

    regExPattern = setId + "[0-9][0-9]-*"  # the digits 0-9 (in pos 1) and 0-9 (in pos 2).
    pattern = re.compile(regExPattern)
    
    for filename in listdir(srcDir):
        if re.match(pattern, filename) and filename.endswith('.pdf') :
            pdfFiles.append(filename)

    pdfFiles.sort(key = str.lower)

    print("\npdfFiles list for book:  *revised today")
    print("====================================================")
    for item in pdfFiles :
        if todaysDate in item:
            print("* " + item)
        else:
            print(item)
     
    print("\n\nItems for book ok? If not, go adjust manually, then")
    input("return and press Enter to make the book...")

    # rebuild list in case user changed items in folder.
    pdfFiles = []
    # Create list of songs by searching the srcDir for matches on the set Id and sequence 00-99
    regExPattern = setId + "[0-9][0-9]-*"  # the digits 0-9 (in pos 1) and 0-9 (in pos 2).
    pattern = re.compile(regExPattern)
    for filename in listdir(srcDir):
        if re.match(pattern, filename) and filename.endswith('.pdf') :
            pdfFiles.append(filename)
    pdfFiles.sort(key = str.lower)
    
    pdfWriter = PyPDF2.PdfFileWriter()

    # Loop through all the PDF files
    for filename in pdfFiles:
        pdfFileObj = open(srcDir + "/" + filename, 'rb')
        pdfReader = PyPDF2.PdfFileReader(pdfFileObj)
        # Loop through all the pages and add them
        for pageNum in range(0, pdfReader.numPages):
            pageObj = pdfReader.getPage(pageNum)
            pdfWriter.addPage(pageObj)

    # Save the resulting PDF to a file.
    pdfOutput = open(bookName, 'wb')
    pdfWriter.write(pdfOutput)
    pdfOutput.close()

    return bookName # includes full path

    
def main():
    print("What is the Set Id? ", end="")
    setId = input()
    zzSetId = 'None'
    print("What is the ZZ Set Id? If None type 'None'", end="")
    zzSetId = input()
    print("What is the revision date in YYYY.MM.DD format? ", end="")
    todaysDate = input()
    print("The Set Id is: ", setId)
    markedDir = 'C:/Users/keith/OneDrive/Documents/GitHub/MixedNutsLib/Marked'
    booksDir = 'C:/Users/keith/OneDrive/Documents/GitHub/MixedNutsLib/Books'
    makeBook(setId, todaysDate, markedDir, booksDir, zzSetId)

if __name__ == '__main__':
    main()

