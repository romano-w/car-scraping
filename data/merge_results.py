import csv
import os
from glob import glob
from typing import Dict, List, Set

DATA_DIR = os.path.dirname(__file__)
OUTPUT_FILE = os.path.join(DATA_DIR, "combined_listings.csv")
FIELDS = ["source", "title", "price", "mileage", "dealer", "location", "url"]


def merge_csv_files(
    input_dir: str = DATA_DIR,
    pattern: str = "*_results.csv",
    output_file: str = OUTPUT_FILE,
) -> List[Dict[str, str]]:
    """Merge CSV files in ``input_dir`` matching ``pattern``.

    Rows are deduplicated by ``url`` and written to ``output_file``.
    The merged rows are also returned for further processing.
    """

    paths = [
        p
        for p in glob(os.path.join(input_dir, pattern))
        if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(output_file)
    ]
    paths.sort()

    merged: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()

    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("url")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append({field: row.get(field) for field in FIELDS})

    if not merged:
        print("No rows found to merge.")
        return []

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(merged)

    print(f"Merged {len(merged)} rows from {len(paths)} files into {output_file}")
    return merged


if __name__ == "__main__":
    merge_csv_files()
