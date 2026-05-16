import re


# Function to extract status and clean names
def extract_status_and_clean_name(name):
    status_list = []
    for prefix in [
        "Mr",
        "Mrs",
        "Ms",
        "Miss",
        "Dr",
        "Prof",
        "Sir",
        "Lord",
        "Lady",
        "Dame",
        "Baroness",
        "Baron",
        "Viscount",
        "Viscountess",
        "Earl",
        "Countess",
        "Duke",
        "Duchess",
        "Prince",
        "Princess",
        "King",
        "Queen",
        "President",
        "Chairman",
        "The Rt Hon",
    ]:
        if re.search(rf"\b{re.escape(prefix)}\b", name):
            status_list.append(prefix)
            name = re.sub(rf"\b{re.escape(prefix)}\b", "", name).strip()

    for suffix in [
        "MP",
        "MSP",
        "MEP",
        "Mp",
        "Msp",
        "Mep",
        "mp",
        "msp",
        "mep",
        "QC",
        "Qc",
        "qc",
        "CBE",
        "Cbe",
        "cbe",
        "OBE",
        "Obe",
        "obe",
        "MBE",
        "Mbe",
        "mbe",
        "KBE",
        "Kbe",
        "kbe",
        "DBE",
        "Dbe",
        "dbe",
    ]:
        if re.search(rf"\b{suffix}\b", name):
            status_list.append(suffix)
            name = re.sub(rf"\b{suffix}\b", "", name).strip()

    status = " & ".join(status_list) if status_list else None
    return name, status


# procedure to create unified name column for mp party membership data
def create_unified_name_column(given_name, family_name):
    First_Last_Name = given_name + " " + family_name
    Last_First_Name = family_name + " " + given_name
    return First_Last_Name, Last_First_Name
