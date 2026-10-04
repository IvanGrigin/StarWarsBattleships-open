#!/usr/bin/env python3
"""Validate the required AI commit format for new project commits."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys


SUBJECT = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+)\.(?P<sequence>\d{5})/"
    r"(?P<worker>Claude|GLM|Codex): (?P<summary>\S.*)$"
)
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
REQUIRED = ("Время", "Что", "Почему")


def git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


def latest_sequence(version: str, ref: str = "HEAD") -> int:
    try:
        subjects = git("log", ref, "--format=%s").splitlines()
    except subprocess.CalledProcessError:
        return 0                                  # пустой репозиторий: истории ещё нет — первый коммит 00001
    for subject in subjects:
        match = SUBJECT.fullmatch(subject)
        if match and match["version"] == version:
            return int(match["sequence"])
    return 0


def validate(message: str, previous: int | None = None) -> tuple[str, int]:
    lines = message.splitlines()
    if not lines or not (match := SUBJECT.fullmatch(lines[0])):
        raise ValueError(
            "тема должна иметь вид v0.4.1.00001/Codex: краткое описание "
            "(также допустимы Claude и GLM)"
        )
    fields: dict[str, str] = {}
    for line in lines[1:]:
        for key in REQUIRED:
            prefix = key + ":"
            if line.startswith(prefix):
                if key in fields:
                    raise ValueError(f"поле {key} указано дважды")
                fields[key] = line[len(prefix):].strip()
    for key in REQUIRED:
        if not fields.get(key):
            raise ValueError(f"в теле коммита требуется непустое поле {key}:")
    if not TIME.fullmatch(fields["Время"]):
        raise ValueError("Время: требуется ISO 8601 с секундами и смещением, например 2026-09-23T12:30:00+02:00")
    if datetime.fromisoformat(fields["Время"]).utcoffset() is None:
        raise ValueError("Время: требуется явный часовой пояс")
    sequence = int(match["sequence"])
    if previous is not None and sequence != previous + 1:
        raise ValueError(
            f"номер версии v{match['version']} должен быть {previous + 1:05d}, получен {sequence:05d}"
        )
    return match["version"], sequence


def check_range(spec: str) -> None:
    if ".." not in spec:
        raise ValueError("--range ожидает диапазон BASE..HEAD")
    base, _ = spec.split("..", 1)
    commits = git("rev-list", "--reverse", spec).splitlines()
    seen: dict[str, int] = {}
    for sha in commits:
        message = git("show", "-s", "--format=%B", sha)
        subject = message.splitlines()[0] if message else ""
        match = SUBJECT.fullmatch(subject)
        previous = None
        if match:
            version = match["version"]
            if version not in seen:
                seen[version] = latest_sequence(version, base)
            previous = seen[version]
        try:
            version, sequence = validate(message, previous)
        except ValueError as exc:
            raise ValueError(f"{sha[:12]}: {exc}") from exc
        seen[version] = sequence


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message-file", type=Path)
    group.add_argument("--range", dest="commit_range")
    parser.add_argument("--check-sequence", action="store_true")
    args = parser.parse_args()
    try:
        if args.commit_range:
            check_range(args.commit_range)
        else:
            message = args.message_file.read_text(encoding="utf-8")
            match = SUBJECT.fullmatch(message.splitlines()[0] if message.splitlines() else "")
            previous = latest_sequence(match["version"]) if args.check_sequence and match else None
            validate(message, previous)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Ошибка формата коммита: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
