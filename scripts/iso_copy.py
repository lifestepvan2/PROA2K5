"""Publish an equal-size patched ISO copy after full source/output verification."""
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class CopySpan:
    """One output span: source bytes, literal data, or zeros if neither is set."""
    offset: int
    size: int
    source_offset: int | None = None
    data: bytes | None = None


def validate_copy_plan(plan: list[CopySpan], size: int) -> None:
    position = 0
    for span in plan:
        if (span.offset != position or span.size <= 0
                or (span.data is not None and
                    (span.source_offset is not None or len(span.data) != span.size))
                or (span.source_offset is not None and
                    not 0 <= span.source_offset <= size - span.size)):
            raise ValueError("ISO copy plan must cover the image with disjoint, bounded spans")
        position += span.size
    if position != size:
        raise ValueError("ISO copy plan must cover the complete image")


def render_copy_plan(stream: BinaryIO, plan: list[CopySpan], index: int,
                     position: int, size: int) -> tuple[bytes, int]:
    result = bytearray()
    saved = stream.tell()
    try:
        while len(result) < size:
            span = plan[index]
            local = position + len(result) - span.offset
            length = min(span.size - local, size - len(result))
            if span.source_offset is not None:
                stream.seek(span.source_offset + local)
                block = stream.read(length)
                if len(block) != length:
                    raise ValueError("Truncated relocated ISO source span")
            elif span.data is not None:
                block = span.data[local:local + length]
            else:
                block = bytes(length)
            result.extend(block)
            if local + length == span.size:
                index += 1
    finally:
        stream.seek(saved)
    return bytes(result), index


def hash_stream(stream: BinaryIO) -> str:
    result = hashlib.sha256()
    stream.seek(0)
    while block := stream.read(4 * 1024 * 1024):
        result.update(block)
    return result.hexdigest()


def validate_patches(patches: list[tuple[int, bytes, bytes]], size: int) -> None:
    previous_end = 0
    for offset, before, after in sorted(patches):
        if (offset < previous_end or not before or len(before) != len(after)
                or offset + len(before) > size):
            raise ValueError("ISO patches must be disjoint, equal-size spans within the image")
        previous_end = offset + len(before)


def publish_iso_copy(
    stream: BinaryIO, output: Path, patches: list[tuple[int, bytes, bytes]],
    source_hash: str, size: int, manifest: dict, manifest_path: Path,
    *, copy_plan: list[CopySpan] | None = None,
) -> dict:
    if output.exists() or manifest_path.exists():
        raise ValueError("Output ISO or manifest already exists; choose a new output path")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory does not exist")
    validate_patches(patches, size)
    if copy_plan is not None:
        validate_copy_plan(copy_plan, size)
    temporary = None
    manifest_created = published = False
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", dir=output.parent,
                                         prefix=output.name + ".", suffix=".tmp",
                                         delete=False) as dest:
            temporary = Path(dest.name)
            expected = hashlib.sha256()
            observed_source = hashlib.sha256()
            stream.seek(0)
            position = 0
            plan_index = 0
            while block := stream.read(4 * 1024 * 1024):
                observed_source.update(block)
                if copy_plan is not None:
                    block, plan_index = render_copy_plan(stream, copy_plan, plan_index, position, len(block))
                for offset, before, after in patches:
                    start = max(position, offset)
                    end = min(position + len(block), offset + len(before))
                    if start < end:
                        local, patch_start = start - position, start - offset
                        if block[local:local + end - start] != before[patch_start:patch_start + end - start]:
                            raise ValueError("Source patch bytes changed during copy")
                        block = (block[:local] + after[patch_start:patch_start + end - start]
                                 + block[local + end - start:])
                expected.update(block)
                if dest.write(block) != len(block):
                    raise OSError("Incomplete output ISO write")
                position += len(block)
            if position != size or observed_source.hexdigest() != source_hash:
                raise ValueError("Source ISO changed during copy")
            if copy_plan is not None and hash_stream(stream) != source_hash:
                raise ValueError("Source ISO changed during relocation")
            dest.flush()
            os.fsync(dest.fileno())
            output_hash = hash_stream(dest)
            if output_hash != expected.hexdigest():
                raise ValueError("Full output ISO verification failed")
            manifest["source_sha256"] = source_hash
            manifest["output_sha256"] = output_hash
        with manifest_path.open("x", encoding="utf-8") as file:
            manifest_created = True
            file.write(json.dumps(manifest, indent=2) + "\n")
            file.flush()
            os.fsync(file.fileno())
        # A hard link atomically publishes the verified file without replacing a racing output.
        os.link(temporary, output)
        published = True
    finally:
        if temporary is not None:
            temporary.unlink()
        if manifest_created and not published:
            manifest_path.unlink()
    return manifest
