"""Split edited 64x64 jumbotron GIFs back into their PNG frames."""

from stitch_video import parser, split


def main() -> None:
    arguments = parser(__doc__)
    args = arguments.parse_args()
    try:
        reports = split(args.workspace, args.groups, args.name)
    except (ValueError, OSError, KeyError, TypeError) as error:
        arguments.exit(1, f"GIF split failed: {error}\n")
    for report in reports:
        print(f"{report['group']}: saved {report['frames']} frames")


if __name__ == "__main__":
    main()
