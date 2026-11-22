"""Split edited strips back into their original workspace PNG tiles.

Run stitch_textures.py first. Matching sidecars must remain beside the edited
PNGs. All groups are validated before any original tile is overwritten.
"""
from stitch_textures import parser, split


def main() -> None:
    arguments = parser(__doc__)
    args = arguments.parse_args()
    try:
        reports = split(args.workspace, args.groups, args.name)
    except (ValueError, OSError, KeyError, TypeError) as error:
        arguments.exit(1, f"Split failed: {error}\n")
    for report in reports:
        print(f"{report['group']}: saved {report['tiles']} tiles")


if __name__ == "__main__":
    main()
