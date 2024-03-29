import pandas as pd


def extract_manufacturer_number(row):
    try:
        if row["manufacturer_company"] != "Darby Dental Supply":
            last_word = row["name"].rsplit(",", 1)[1].strip()
            if "Pkg." in last_word:
                return
            if " ml" in last_word:
                return
            if "/Box" in last_word:
                return
            if "/Tub" in last_word:
                return
            if "Tabs" in last_word:
                return
            if "Tablets" in last_word:
                return
            if " oz" in last_word:
                return
            return last_word
    except IndexError:
        pass


def is_different(row):
    if row["manufacturer_company"] != "Darby Dental Supply":
        if row["manufacturer_number"] == row["new_manufacturer_number"]:
            return ""
        if "/Pkg." in row["manufacturer_number"]:
            return ""
        if " ml" in row["manufacturer_number"]:
            return
        if "/Box" in row["manufacturer_number"]:
            return
        if "/Tub" in row["manufacturer_number"]:
            return
        if "Tabs" in row["manufacturer_number"]:
            return
        if "Tablets" in row["manufacturer_number"]:
            return
        if " oz" in row["manufacturer_number"]:
            return
        return "1"


if __name__ == "__main__":
    file_path = "/home/levan/Projects/ordo/ordo-backend/products/darby.csv"
    df = pd.read_csv(file_path, na_filter=False, low_memory=False, dtype=str)
    df["manufacturer_number"] = df.apply(lambda row: extract_manufacturer_number(row), axis=1)
    df.to_csv(file_path)
