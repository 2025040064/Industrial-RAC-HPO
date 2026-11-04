"""Fetch the pinned, CC BY 4.0 official UCI Steel CSV into the local workspace."""

import argparse
from pathlib import Path

from rac_hpo.data import download_steel, prepare_steel_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("datasets/raw/steel_energy"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("datasets/manifests"))
    args = parser.parse_args()
    try:
        path = download_steel(args.destination)
        dataset = prepare_steel_dataset(path, args.manifest_dir)
    except ValueError as error:
        parser.exit(1, f"Dataset error: {error}\n")
    print(f"Dataset: {path}")
    print(f"SHA256: {dataset.source_sha256}")
    for name, summary in dataset.manifest["split_summary"].items():
        print(f"{name}: {summary['rows']} rows; {summary['calendar_dates']} calendar dates")


if __name__ == "__main__":
    main()
