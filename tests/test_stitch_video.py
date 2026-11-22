import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stitch_video import FRAME_COUNT, FRAME_SIZE, split, stitch


GIF_DURATIONS_MS = [20] * FRAME_COUNT


def save_gif(path, colors, durations=GIF_DURATIONS_MS, size=FRAME_SIZE):
    frames = [
        Image.new("RGB", size, color).quantize(
            colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
        for color in colors
    ]
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )


class JumbotronVideoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.group = self.workspace / "jumbotron_movies" / "slot_000" / "hash_12345678"
        self.group.mkdir(parents=True)
        for index in reversed(range(FRAME_COUNT)):
            image = Image.new("RGBA", FRAME_SIZE, (index % 256, 20, 40, 64 + index % 180))
            image.save(self.group / f"hash_jumbotron_movie{index:03d}__64x64__{index:08x}.png")
        self.video = (
            self.workspace / "_videos" / "jumbotron_movies" / "slot_000" / "hash_12345678"
            / "jumbotron_movie.gif"
        )
        self.sidecar = self.video.with_suffix(".json")

    def test_stitch_creates_ordered_gif_and_mapping(self):
        report = stitch(self.workspace)
        self.assertEqual(report[0]["frames"], FRAME_COUNT)
        self.assertFalse(report[0]["skipped"])
        self.assertTrue(self.video.is_file())
        metadata = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual(metadata["format"], "GIF")
        self.assertEqual(metadata["fps"], 50)
        self.assertEqual(metadata["duration_ms"], 3600)
        self.assertEqual([frame["index"] for frame in metadata["frames"]], list(range(FRAME_COUNT)))

        with Image.open(self.video) as image:
            self.assertEqual(image.format, "GIF")
            self.assertEqual(image.size, FRAME_SIZE)
            self.assertEqual(image.n_frames, FRAME_COUNT)
            durations = []
            for index in range(FRAME_COUNT):
                image.seek(index)
                durations.append(image.info["duration"])
        self.assertEqual(durations, GIF_DURATIONS_MS)

    def test_split_saves_gif_frames_to_original_ids_and_preserves_alpha(self):
        stitch(self.workspace)
        colors = [(210, 90, 30 + index) for index in range(FRAME_COUNT)]
        save_gif(self.video, colors)

        self.assertEqual(split(self.workspace)[0]["frames"], FRAME_COUNT)
        for index in (0, 179):
            path = self.group / f"hash_jumbotron_movie{index:03d}__64x64__{index:08x}.png"
            with Image.open(path) as image:
                self.assertEqual(image.getpixel((0, 0)), (*colors[index], 64 + index % 180))

        self.assertEqual(split(self.workspace)[0]["frames"], FRAME_COUNT)

    def test_stitch_keeps_duplicate_source_frames(self):
        for path in self.group.glob("*.png"):
            Image.new("RGBA", FRAME_SIZE, (10, 20, 30, 255)).save(path)

        stitch(self.workspace)
        with Image.open(self.video) as image:
            self.assertEqual(image.n_frames, FRAME_COUNT)

    def test_stitch_keeps_existing_gif_unless_overwrite_is_requested(self):
        stitch(self.workspace)
        save_gif(self.video, [(index, 0, 0) for index in range(FRAME_COUNT)])
        edited_gif = self.video.read_bytes()

        report = stitch(self.workspace)
        self.assertTrue(report[0]["skipped"])
        self.assertEqual(self.video.read_bytes(), edited_gif)

        stitch(self.workspace, overwrite=True)
        self.assertNotEqual(self.video.read_bytes(), edited_gif)

    def test_bad_later_group_does_not_publish_any_gif(self):
        later = self.workspace / "jumbotron_movies" / "slot_001" / "hash_87654321"
        later.mkdir(parents=True)
        for index in range(FRAME_COUNT - 1):
            Image.new("RGBA", FRAME_SIZE).save(
                later / f"hash_jumbotron_movie{index:03d}__64x64__{index:08x}.png"
            )

        with self.assertRaisesRegex(ValueError, "exactly 180"):
            stitch(self.workspace)
        self.assertFalse(self.video.exists())

    def test_short_gif_is_padded_with_its_last_frame(self):
        stitch(self.workspace)
        colors = [(210, 90, 30 + index) for index in range(FRAME_COUNT - 1)]
        save_gif(self.video, colors)

        self.assertEqual(split(self.workspace)[0]["frames"], FRAME_COUNT)
        last_path = self.group / f"hash_jumbotron_movie179__64x64__{179:08x}.png"
        with Image.open(last_path) as image:
            self.assertEqual(image.getpixel((0, 0)), (*colors[-1], 64 + 179 % 180))

    def test_long_gif_is_truncated_after_frame_179(self):
        stitch(self.workspace)
        colors = [(210, 90, 30 + index) for index in range(FRAME_COUNT + 1)]
        save_gif(self.video, colors, durations=20)

        self.assertEqual(split(self.workspace)[0]["frames"], FRAME_COUNT)
        last_path = self.group / f"hash_jumbotron_movie179__64x64__{179:08x}.png"
        with Image.open(last_path) as image:
            self.assertEqual(image.getpixel((0, 0)), (*colors[179], 64 + 179 % 180))

    def test_wrong_dimensions_do_not_overwrite_source_frames(self):
        stitch(self.workspace)
        original_files = {path: path.read_bytes() for path in self.group.glob("*.png")}
        save_gif(
            self.video,
            [(index, 10, 20) for index in range(FRAME_COUNT)],
            size=(FRAME_SIZE[0] - 1, FRAME_SIZE[1]),
        )

        with self.assertRaisesRegex(ValueError, "expected 64x64 GIF"):
            split(self.workspace)
        self.assertEqual(original_files, {path: path.read_bytes() for path in self.group.glob("*.png")})

    def test_legacy_mp4_sidecar_migrates_for_existing_gif(self):
        stitch(self.workspace)
        metadata = json.loads(self.sidecar.read_text(encoding="utf-8"))
        metadata["schema"] = 1
        metadata["codec"] = "H.264"
        metadata["fps"] = 60
        metadata["video"] = self.video.with_suffix(".mp4").relative_to(self.workspace).as_posix()
        metadata.pop("format")
        metadata.pop("duration_ms")
        self.sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        save_gif(self.video, [(210, 90, 30 + index) for index in range(FRAME_COUNT)])

        split(self.workspace)
        migrated = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema"], 2)
        self.assertEqual(migrated["format"], "GIF")
        self.assertEqual(migrated["fps"], 50)
        self.assertEqual(migrated["video"], self.video.relative_to(self.workspace).as_posix())

    def test_schema_2_60_fps_sidecar_is_accepted_and_updated(self):
        stitch(self.workspace)
        metadata = json.loads(self.sidecar.read_text(encoding="utf-8"))
        metadata["fps"] = 60
        metadata["duration_ms"] = 3000
        self.sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        durations = [0] + [20] * (FRAME_COUNT - 1)
        save_gif(self.video, [(210, 90, 30 + index) for index in range(FRAME_COUNT)], durations)

        split(self.workspace)
        updated = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual(updated["fps"], 50)
        self.assertEqual(updated["duration_ms"], 3580)

    def test_sidecar_cannot_escape_its_source_group(self):
        stitch(self.workspace)
        metadata = json.loads(self.sidecar.read_text(encoding="utf-8"))
        metadata["frames"][0]["path"] = "../outside.png"
        self.sidecar.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "outside"):
            split(self.workspace)


if __name__ == "__main__":
    unittest.main()
