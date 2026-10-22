"""Shell command analysis shared by the guards that read the literal Bash command.

A guard must decide on the commands that will run, not on the text of the line. This
module splits a command line into simple commands and looks through the usual ways of
running another command:

  - separators (`;`, `&`, `|`, newlines, parentheses, backticks) outside quotes;
  - comments, arithmetic `$((...))` and heredoc bodies, which are data and not commands;
  - `$(...)` and backticks inside double quotes;
  - `bash -c '...'`, `sh -c`, `eval`, and shells or `source` fed by a heredoc, a
    here-string or a pipe (every quoted string in the line is then inspected);
  - wrappers such as `sudo -u x`, `env -i`, `time`, `nice -n 5`, `timeout 5`, `xargs`
    and `find -exec`, and leading assignments and redirections.

Unreadable input (an unterminated quote, nesting too deep) raises ValueError, and the
guard's `run_guard` turns that into a block: the guard fails closed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from _common import tokenize

MAX_NESTING = 3

HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECT_OPERATOR = re.compile(r"^\d*(>>?|<|>\||&>>?)$")
REDIRECT_ATTACHED = re.compile(r"^\d*(>>?|<|>\||&>>?)\S")
SEPARATORS = ";&|()`"
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
STDIN_SHELLS = SHELLS | {"source", "."}
WRAPPERS = {
    "sudo",
    "doas",
    "time",
    "nohup",
    "command",
    "builtin",
    "exec",
    "env",
    "xargs",
    "nice",
    "ionice",
    "timeout",
    "stdbuf",
    "setsid",
    "unbuffer",
    "watch",
    "strace",
}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


@dataclass
class Command:
    text: str  # the segment as written
    tokens: list[str]  # from the program onwards (wrappers and assignments removed)
    raw: list[str]  # every token of the segment, assignments and redirections included
    stdin: str = ""  # heredoc bodies and here-strings given to the segment


@dataclass
class _Piece:
    text: str
    bodies: list[str] = field(default_factory=list)
    inner: list[str] = field(default_factory=list)  # $(...) and `...` inside double quotes


def _keep_backslashes(text: str) -> str:
    """Double the backslashes outside quotes so POSIX tokenizing keeps Windows paths intact."""
    out: list[str] = []
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote == '"' and char == "\\" and text[index + 1 : index + 2] in {'"', "\\"}:
            out.append(text[index : index + 2])
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "\\":
            out.append("\\")
        out.append(char)
        index += 1
    return "".join(out)


def _tokens(text: str, windows: bool) -> list[str]:
    return tokenize(_keep_backslashes(text) if windows else text)


def program_name(token: str) -> str:
    return os.path.basename(token.replace("\\", "/")).lower().removesuffix(".exe")


def unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    return token


def _skip_heredocs(
    command: str, start: int, pending: list[tuple[str, bool, int]]
) -> tuple[int, list[tuple[int, str]]]:
    """Index after the pending bodies, and the bodies with their piece (`start` if unterminated)."""
    index = start
    bodies: list[tuple[int, str]] = []
    for delimiter, strip_tabs, target in pending:
        lines: list[str] = []
        while True:
            if index >= len(command):
                return start, []
            end = command.find("\n", index)
            line = command[index:] if end == -1 else command[index:end]
            index = len(command) if end == -1 else end + 1
            line = line.rstrip("\r")
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
            lines.append(line)
        bodies.append((target, "\n".join(lines)))
    return index, bodies


def _balanced_end(command: str, start: int, opener: str, closer: str) -> int:
    """Index just after the closer matching the opener that ends at `start`; -1 if none."""
    depth = 1
    index = start
    while index < len(command):
        if command[index] == "\\":
            index += 2
            continue
        if command.startswith(opener, index):
            depth += 1
        elif command[index] == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return -1


def _is_redirect_part(char: str, current: list[str], command: str, index: int) -> bool:
    """`>|`, `>&`, `2>&1` and `&>` are redirections, not separators."""
    before = current[-1] if current else ""
    if char == "|":
        return before == ">"
    if char == "&":
        return before == ">" or command[index + 1 : index + 2] == ">"
    return False


def _scan(command: str) -> list[_Piece]:
    pieces: list[_Piece] = []
    current: list[str] = []
    inner: list[str] = []
    pending: list[tuple[str, bool, int]] = []
    quote = ""
    index = 0

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            pieces.append(_Piece(text, [], list(inner)))
        current.clear()
        inner.clear()

    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 2
        elif (
            quote == '"'
            and command.startswith("$(", index)
            and not command.startswith("$((", index)
        ):
            end = _balanced_end(command, index + 2, "(", ")")
            if end == -1:
                raise ValueError("unterminated command substitution")
            inner.append(command[index + 2 : end - 1])
            current.append(command[index:end])
            index = end
        elif quote == '"' and char == "`":
            end = command.find("`", index + 1)
            if end == -1:
                raise ValueError("unterminated command substitution")
            inner.append(command[index + 1 : end])
            current.append(command[index : end + 1])
            index = end + 1
        elif quote:
            current.append(char)
            quote = "" if char == quote else quote
            index += 1
        elif char in "'\"":
            quote = char
            current.append(char)
            index += 1
        elif char == "#" and (not current or current[-1].isspace()):
            end = command.find("\n", index)
            index = len(command) if end == -1 else end
        elif command.startswith("$((", index):
            end = command.find("))", index + 3)
            end = end + 2 if end != -1 else index + 3
            current.append(command[index:end])
            index = end
        elif command.startswith("<<", index) and not command.startswith("<<<", index):
            match = HEREDOC.match(command, index)
            if match:
                pending.append((match.group(3), bool(match.group(1)), len(pieces)))
                current.append(match.group(0))
                index = match.end()
            else:
                current.append("<<")
                index += 2
        elif char == "\n":
            flush()
            index, found = _skip_heredocs(command, index + 1, pending)
            for target, body in found:
                pieces[target].bodies.append(body)
            pending = []
        elif _is_redirect_part(char, current, command, index):
            current.append(char)
            index += 1
        elif char in SEPARATORS:
            flush()
            index += 1
        else:
            current.append(char)
            index += 1
    if quote:
        raise ValueError("unterminated quote")
    flush()
    return pieces


def split_segments(command: str) -> list[str]:
    """The simple commands of a command line, as written."""
    return [piece.text for piece in _scan(command)]


def _skip_prefix(tokens: list[str], index: int) -> int:
    while index < len(tokens):
        token = tokens[index]
        if ENV_ASSIGNMENT.match(token) or token in KEYWORDS:
            index += 1
        elif REDIRECT_OPERATOR.match(token):
            index += 2
        elif REDIRECT_ATTACHED.match(token):
            index += 1
        else:
            break
    return index


def _starts(tokens: list[str]) -> list[int]:
    """Positions where a command may begin: the program, and what a wrapper runs."""
    first = _skip_prefix(tokens, 0)
    if first >= len(tokens):
        return []
    starts = [first]
    program = program_name(tokens[first])
    if program in WRAPPERS:
        starts += [_skip_prefix(tokens, i) for i in range(first + 1, len(tokens))]
    elif program == "find":
        starts += [i + 1 for i, token in enumerate(tokens) if token in FIND_EXEC]
    return [i for i in dict.fromkeys(starts) if i < len(tokens)]


def _shell_script(args: list[str]) -> str | None:
    for index, arg in enumerate(args[:-1]):
        if re.fullmatch(r"-[a-zA-Z]*c", arg):
            return unquote(args[index + 1])
    return None


def _here_strings(tokens: list[str]) -> list[str]:
    found = []
    for index, token in enumerate(tokens):
        if token == "<<<" and index + 1 < len(tokens):
            found.append(unquote(tokens[index + 1]))
        elif token.startswith("<<<") and len(token) > 3:
            found.append(unquote(token[3:]))
    return found


def iter_commands(command: str, windows: bool = False, depth: int = 0) -> Iterator[Command]:
    """Every command the line may run, including those inside nested shells.

    windows=True keeps the backslashes of unquoted Windows paths (`C:\\Users\\name`).
    """
    if depth > MAX_NESTING:
        raise ValueError("shell commands nested too deeply to inspect")
    pieces = _scan(command)
    deep = False
    for piece in pieces:
        raw = _tokens(piece.text, windows)
        stdin = "\n".join([*piece.bodies, *_here_strings(raw)])
        for start in _starts(raw):
            tokens = raw[start:]
            yield Command(piece.text, tokens, raw, stdin)
            program = program_name(unquote(tokens[0]))
            if program in SHELLS:
                script = _shell_script(tokens[1:])
                if script is not None:
                    yield from iter_commands(script, windows, depth + 1)
                    continue
            if program == "eval":
                yield from iter_commands(
                    " ".join(unquote(t) for t in tokens[1:]), windows, depth + 1
                )
            if program in STDIN_SHELLS or program == "eval":
                deep = True
        for inner in piece.inner:
            yield from iter_commands(inner, windows, depth + 1)
    if deep:
        # Something reads commands from a heredoc, a pipe or a substitution: look at every
        # heredoc body and every quoted string of the line as a command line of its own.
        for piece in pieces:
            texts = list(piece.bodies)
            texts += [
                unquote(t) for t in _tokens(piece.text, windows) if re.search(r"\s", unquote(t))
            ]
            texts += _here_strings(_tokens(piece.text, windows))
            for text in texts:
                yield from iter_commands(text, windows, depth + 1)
