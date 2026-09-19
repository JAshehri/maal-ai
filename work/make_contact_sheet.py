from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument("--thumb-width", type=int, default=650)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()

    all_paths = sorted(args.source_dir.glob("*.png"))
    paths = all_paths[args.start - 1 : args.start - 1 + args.count]
    images = []
    for index, path in enumerate(paths, start=1):
        image = Image.open(path).convert("RGB")
        height = round(image.height * args.thumb_width / image.width)
        image = image.resize((args.thumb_width, height))
        canvas = Image.new("RGB", (args.thumb_width, height + 36), "white")
        canvas.paste(image, (0, 36))
        ImageDraw.Draw(canvas).text((12, 10), f"Page {index}: {path.name}", fill="black")
        images.append(canvas)

    rows = (len(images) + args.columns - 1) // args.columns
    cell_h = max(image.height for image in images)
    sheet = Image.new("RGB", (args.columns * args.thumb_width, rows * cell_h), "#dddddd")
    for index, image in enumerate(images):
        x = (index % args.columns) * args.thumb_width
        y = (index // args.columns) * cell_h
        sheet.paste(image, (x, y))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=90)


if __name__ == "__main__":
    main()
