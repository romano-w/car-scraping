import csv
from pathlib import Path

import data.merge_results as mr


def _write_csv(path: Path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=mr.FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_merge_csv_dedupes_by_url(tmp_path):
    rows1 = [
        {
            "source": "cars.com",
            "title": "Car A",
            "price": "1000",
            "mileage": "5000",
            "dealer": "A",
            "location": "X",
            "url": "http://1",
        },
        {
            "source": "cars.com",
            "title": "Car B",
            "price": "2000",
            "mileage": "10000",
            "dealer": "B",
            "location": "Y",
            "url": "http://2",
        },
    ]
    rows2 = [
        {
            "source": "cargurus",
            "title": "Car C",
            "price": "3000",
            "mileage": "15000",
            "dealer": "C",
            "location": "Z",
            "url": "http://2",
        },
        {
            "source": "craigslist",
            "title": "Car D",
            "price": "4000",
            "mileage": "20000",
            "dealer": "D",
            "location": "W",
            "url": "http://3",
        },
    ]

    _write_csv(tmp_path / "a_results.csv", rows1)
    _write_csv(tmp_path / "b_results.csv", rows2)

    output_file = tmp_path / "combined.csv"
    merged = mr.merge_csv_files(
        input_dir=str(tmp_path), pattern="*_results.csv", output_file=str(output_file)
    )

    assert len(merged) == 3
    assert output_file.exists()
    with open(output_file, newline="", encoding="utf-8") as f:
        out_rows = list(csv.DictReader(f))
    assert len(out_rows) == 3
    urls = [r["url"] for r in out_rows]
    assert urls == ["http://1", "http://2", "http://3"]
