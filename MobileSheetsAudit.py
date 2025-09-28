##processRevisions
import os
import re

def build_files_set(rootdir):
    root_to_subtract = re.compile(r'^.*?' + rootdir + r'[\\/]{0,1}')

    files_set = set()
    for (dirpath, dirnames, filenames) in os.walk(rootdir):
        for filename in filenames + dirnames:
            full_path = os.path.join(dirpath, filename)
            relative_path = root_to_subtract.sub('', full_path, count=1)
            ## replace apostrophes with blank in relative_path because file names in Mobilesheets have no apostrophes
            ##print(relative_path)
            relative_path = relative_path.replace("'", " ")
            relative_path = relative_path.replace("_", " ")
            relative_path = relative_path.replace("ChordPro-", "")
            ##print(relative_path)
            if     ("Newsies-"      not in relative_path
                and ".pro"          not in relative_path
                and "JBOX"          not in relative_path):
                files_set.add(relative_path)

    return files_set

def compare_directories(dir1, dir2):
    files_set1 = build_files_set(dir1)
    files_set2 = build_files_set(dir2)
    
    
    return (files_set1 - files_set2, files_set2 - files_set1)


def main():

    print("\nBefore procedding you must do the following:\n 1. Clear out the directory: C:/Users/Keith/Documents/GitHub/MixedNutsLib/MobileSheetsPDFExtract")
    print(" 2. In Mobilesheets: Select all songs (use square icon in lower right corner).")
    print("    and use the \"Share-->Export Files\" option to export them as PDF files to:\n        C:/Users/Keith/Documents/GitHub/MixedNutsLib/MobileSheetsPDFExtract")
    print("    (Use a thumb drive if coming from a different computer. (moving through Google Docs is too slow.))")
    print(" 3. Be patient, it takes several minutes.")

    print("\nAre you ready to proceed with the audit? (y/n) ", end="")
    doAuditYN = input()
    doAuditYN = doAuditYN.upper()
    if doAuditYN != 'Y' :
        quit()

    ExtractPATH = 'C:/Users/Keith/oNEdRIVE/Documents/GitHub/MixedNutsLib/MobileSheetsPDFExtract/'
    MarkedPATH = 'C:/Users/Keith/oNEdRIVE/Documents/GitHub/MixedNutsLib/Marked/'
    ##print ("Extract file exists:" + str(path.exists(ExtractPATH + 'ValABCD18-C15-Fly Me To The Moon(KVF).2015.02.08.pdf')))
    ##print ("Marked  file exists:" + str(path.exists(MarkedPATH  + 'ValABCD18-C15-Fly Me To The Moon(KVF).2020.07.23.pdf')))

    dir1 = ExtractPATH
    dir1_label = "MobileSheets: "
    dir2 = MarkedPATH
    dir2_label = "Marked:       "
    in_dir1, in_dir2 = compare_directories(dir1, dir2)
    
    both_files_set = set()
    for relative_path in in_dir1:
        labeled_path = "MobileSheets: " + relative_path
        both_files_set.add(labeled_path)

    for relative_path in in_dir2:
        labeled_path = "Marked:       " + relative_path
        both_files_set.add(labeled_path)

    ##print ('\nFiles only in {}:'.format(dir1))
    ##for relative_path in in_dir1:
    ##    print ('* {0}'.format(relative_path))

        
    ##sorted_in_dir1 = sorted(in_dir1)
    ##print ('\nFiles only in MobileSheets:')
    ##for relative_path in sorted_in_dir1:
    ##    print ("MobileSheets: " + relative_path)


    ##print ('\nFiles only in {}:'.format(dir2))
    ##for relative_path in in_dir2:
    ##    print ('* {0}'.format(relative_path))

    ##sorted_in_dir2 = sorted(in_dir2)
    ##print ('\nFiles only in Marked')
    ##for relative_path in sorted_in_dir2:
    ##    print ("Marked:       " + relative_path)

    
    ##both_dir = in_dir1.union(in_dir2)
    both_sorted = sorted(both_files_set)
    print ('\nFiles with no match in the other dir:')
    for labeled_path in both_sorted:
        if ('$Music' not in labeled_path 
            and 'ValA' not in labeled_path
            and 'ValB' not in labeled_path
            and 'ValC' not in labeled_path
            and 'WEST0' not in labeled_path
            and 'WEST1' not in labeled_path
            and 'CTRY0' not in labeled_path
            and 'CTRY1' not in labeled_path         
            ):
            print (labeled_path)

    ##---------------------    



    print("\n============= The program has finished. ====================")
    input("Press Enter to close the terminal.")
    
if __name__ == '__main__':
    
    main()
