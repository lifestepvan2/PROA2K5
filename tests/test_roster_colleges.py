import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_roster import (
    COLLEGE_BASE, COLLEGE_COUNT, COLLEGE_STRIDE, GAP, PLAYER_BASE, PLAYER_COUNT,
    PLAYER_STORAGE_COUNT, PLAYER_STRIDE, POOL_MIN, Payload, plan_colleges, repack_strings,
)


def fixture():
    data = bytearray(0xB1040)

    def pointer(field, target):
        struct.pack_into("<i", data, field, target - field + 1)

    struct.pack_into("<I", data, 0x60, COLLEGE_COUNT)
    pointer(0x64, COLLEGE_BASE)
    data[POOL_MIN:POOL_MIN + 12] = "Other\0".encode("utf-16-le")
    pointer(0x10, POOL_MIN)
    target = POOL_MIN + 0x100
    for r in range(COLLEGE_COUNT):
        row = COLLEGE_BASE + r * COLLEGE_STRIDE
        text = "Albany State" if r == 0 else f"College {r}"
        encoded = (text + "\0").encode("utf-16-le")
        data[target:target + len(encoded)] = encoded
        pointer(row, target)
        struct.pack_into("<II", data, row + 4, r * 2, 0x80000000)
        target += len(encoded)
    for r in range(PLAYER_STORAGE_COUNT):
        pointer(PLAYER_BASE + r * PLAYER_STRIDE, COLLEGE_BASE)
    return Payload(data)


def college(pl, record):
    return pl.str_at(pl.target(PLAYER_BASE + record * PLAYER_STRIDE))


def metadata(pl):
    return [bytes(pl.d[row + 4:row + 12])
            for row in range(COLLEGE_BASE, PLAYER_BASE, COLLEGE_STRIDE)]


class CollegeTests(unittest.TestCase):
    def test_shared_labels_blank_literal_college_and_metadata_preserved(self):
        original = fixture()
        before = bytes(original.d)
        values = {0: "Germany", 1: "Germany", 2: "Georgetown", 3: ""}
        assignments, reclaim, report = plan_colleges(original, values)
        built, changed, _, cleared = repack_strings(original, assignments, reclaim)
        self.assertEqual([college(built, r) for r in values], list(values.values()))
        self.assertEqual(built.target(PLAYER_BASE), built.target(PLAYER_BASE + PLAYER_STRIDE))
        self.assertEqual(metadata(built), metadata(original))
        self.assertEqual((report["labels"], report["new_rows"], report["reusable_rows"]), (3, 3, 457))
        self.assertEqual(cleared, 0)
        self.assertEqual(built.str_at(0x10), "Other")
        self.assertEqual(len(built.d), len(before))
        for r in range(4, PLAYER_STORAGE_COUNT):
            field = PLAYER_BASE + r * PLAYER_STRIDE
            self.assertEqual(bytes(built.d[field:field + 4]), before[field:field + 4])
            self.assertIsInstance(college(built, r), str)
        for field in range(COLLEGE_BASE, PLAYER_BASE, COLLEGE_STRIDE):
            if field not in changed:
                self.assertEqual(built.str_at(field), original.str_at(field))

    def test_matching_row_reused_without_rewriting(self):
        pl = fixture()
        pl.set_ptr(PLAYER_BASE + PLAYER_STRIDE, COLLEGE_BASE + 7 * COLLEGE_STRIDE)
        assignments, _, report = plan_colleges(pl, {0: "College 7"})
        self.assertEqual(assignments, [])
        self.assertEqual(pl.target(PLAYER_BASE), COLLEGE_BASE + 7 * COLLEGE_STRIDE)
        self.assertEqual(report["new_rows"], 0)

    def test_matching_free_row_reserved_before_allocating_new_labels(self):
        pl = fixture()
        assignments, reclaim, _ = plan_colleges(pl, {0: "AAA", 1: "College 1"})
        built, _, _, _ = repack_strings(pl, assignments, reclaim)
        self.assertEqual(college(built, 0), "AAA")
        self.assertEqual(college(built, 1), "College 1")
        self.assertNotEqual(built.target(PLAYER_BASE), built.target(PLAYER_BASE + PLAYER_STRIDE))

    def test_auxiliary_templates_still_have_valid_labels_when_their_row_is_reused(self):
        pl = fixture()
        assignments, reclaim, report = plan_colleges(pl, dict.fromkeys(range(PLAYER_COUNT), "Germany"))
        built, _, _, _ = repack_strings(pl, assignments, reclaim)
        self.assertEqual(report["reusable_rows"], COLLEGE_COUNT)
        for r in range(PLAYER_COUNT, PLAYER_STORAGE_COUNT):
            self.assertEqual(college(built, r), "Germany")
        for r in range(PLAYER_COUNT):
            self.assertEqual(college(built, r), "Germany")

    def test_mapping_is_deterministic(self):
        left, right = fixture(), fixture()
        values = {2: "Lithuania", 0: "Germany", 1: ""}
        a = plan_colleges(left, values)
        b = plan_colleges(right, dict(reversed(list(values.items()))))
        left = repack_strings(left, a[0], a[1])[0]
        right = repack_strings(right, b[0], b[1])[0]
        self.assertEqual(left.d, right.d)

    def test_row_exhaustion_fails_before_changing_pointers(self):
        pl = fixture()
        before = bytes(pl.d)
        with self.assertRaisesRegex(ValueError, "College table exhausted.*458.*457"):
            plan_colleges(pl, {r: f"New {r}" for r in range(458)})
        self.assertEqual(pl.d, before)

    def test_exact_row_capacity_succeeds(self):
        pl = fixture()
        values = {r: f"New {r}" for r in range(COLLEGE_COUNT)}
        assignments, reclaim, report = plan_colleges(pl, values)
        built, _, _, _ = repack_strings(pl, assignments, reclaim)
        self.assertEqual(report["remaining_rows"], 0)
        self.assertEqual(reclaim, [])
        self.assertEqual([college(built, r) for r in values], list(values.values()))

    def test_descriptor_bad_owner_and_invalid_text_are_rejected(self):
        cases = [
            (0x60, 458, "descriptor"),
            (PLAYER_BASE + PLAYER_COUNT * PLAYER_STRIDE, 0, "pointer"),
        ]
        for field, raw, message in cases:
            pl = fixture()
            struct.pack_into("<I", pl.d, field, raw)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                plan_colleges(pl, {0: "Germany"})
        with self.assertRaisesRegex(ValueError, "College"):
            plan_colleges(fixture(), {0: "Bad\0College"})

    def test_unused_names_reclaimed_only_when_needed_and_all_rows_remain_valid(self):
        pl = fixture()
        old_metadata = metadata(pl)
        text = "X" * 4000
        assignments, reclaim, _ = plan_colleges(pl, {0: text})
        built, _, _, cleared = repack_strings(pl, assignments, reclaim)
        self.assertEqual(cleared, len(reclaim))
        self.assertGreater(cleared, 0)
        self.assertEqual(college(built, 0), text)
        self.assertEqual(college(built, PLAYER_COUNT), text)
        self.assertEqual(metadata(built), old_metadata)
        self.assertEqual(built.str_at(0x10), "Other")
        for field in reclaim:
            self.assertEqual(built.str_at(field), "")
            self.assertIn(field, built.refs[built.target(field)])
        self.assertEqual(len(built.d), 0xB1040)

    def test_byte_exhaustion_is_explicit_and_does_not_mutate_input(self):
        pl = fixture()
        assignments, reclaim, _ = plan_colleges(pl, {0: "X" * 20000})
        before = bytes(pl.d)
        with self.assertRaisesRegex(MemoryError, "needs.*has.*short.*largest block"):
            repack_strings(pl, assignments, reclaim)
        self.assertEqual(pl.d, before)

    def test_fragmentation_fails_even_with_enough_total_free_bytes(self):
        pl = fixture()
        pl.free = [(GAP[0], GAP[0] + 20), (GAP[0] + 30, GAP[0] + 50)]
        before = bytes(pl.d)
        with self.assertRaisesRegex(MemoryError, "fragmentation.*26 B.*largest block 20 B"):
            repack_strings(pl, [(0x10, "ABCDEFGHIJKL")])
        self.assertEqual(pl.d, before)

    def test_exact_contiguous_capacity_succeeds(self):
        pl = fixture()
        pl.free = [(GAP[0], GAP[0] + 26)]
        built, _, _, _ = repack_strings(pl, [(0x10, "ABCDEFGHIJKL")])
        self.assertEqual(built.str_at(0x10), "ABCDEFGHIJKL")
        self.assertEqual(built.free_bytes(), 12)


if __name__ == "__main__":
    unittest.main()
