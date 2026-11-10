"""Progress reporting built on tqdm (notebooks) and rich (terminals).

* In Jupyter / SageMaker / VS Code / Colab we use ``tqdm.auto`` which renders a
  native widget progress bar.
* In a terminal we use ``rich`` for a colourful bar with spinner, transfer
  speed and elapsed time.
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from ._utils import in_notebook

ACCENT = "#6366f1"


class Progress:
    """Minimal progress interface used throughout osss."""

    def start(self, total: Optional[float], description: str = "", unit: str = "") -> None: ...

    def update(self, completed: float, message: str = "") -> None: ...

    def note(self, message: str) -> None: ...

    def close(self, message: str = "", ok: bool = True) -> None: ...


class NullProgress(Progress):
    pass


class TqdmProgress(Progress):
    """``tqdm.auto`` bar: a widget in notebooks, text elsewhere."""

    def __init__(self) -> None:
        from tqdm.auto import tqdm

        self._tqdm = tqdm
        self._bar = None
        self._desc = ""

    def start(self, total, description="", unit=""):
        self._desc = description
        is_bytes = unit == "B"
        self._bar = self._tqdm(
            total=total,
            desc=description,
            unit=unit or ("" if total is None else "it"),
            unit_scale=is_bytes,
            unit_divisor=1024 if is_bytes else 1000,
            colour=ACCENT,
            dynamic_ncols=True,
            leave=True,
            bar_format=None if total else "{desc} {elapsed} {postfix}",
        )

    def update(self, completed, message=""):
        if self._bar is None:
            return
        delta = float(completed) - float(self._bar.n)
        if delta > 0:
            self._bar.update(delta)
        if message:
            self._bar.set_postfix_str(message[:70], refresh=False)

    def note(self, message):
        if self._bar is not None:
            self._bar.set_postfix_str(message[:70])

    def close(self, message="", ok=True):
        if self._bar is None:
            return
        if self._bar.total:
            self._bar.update(max(0, self._bar.total - self._bar.n))
        self._bar.set_description(("✓ " if ok else "✕ ") + self._desc)
        self._bar.set_postfix_str(message[:80])
        if not ok:
            self._bar.colour = "#dc2626"
        self._bar.close()
        self._bar = None


class RichProgress(Progress):
    """Rich progress bar for terminals."""

    def __init__(self) -> None:
        from rich.progress import Progress as RP

        self._RP = RP
        self._p = None
        self._task = None
        self._desc = ""

    def start(self, total, description="", unit=""):
        from rich.progress import (
            BarColumn,
            DownloadColumn,
            MofNCompleteColumn,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
            TransferSpeedColumn,
        )

        cols = [SpinnerColumn(style="magenta", finished_text=""), TextColumn("[bold]{task.description}")]
        if total:
            cols.append(BarColumn(complete_style="magenta", finished_style="green"))
            cols += [DownloadColumn(), TransferSpeedColumn()] if unit == "B" else [MofNCompleteColumn()]
        cols += [TimeElapsedColumn(), TextColumn("[dim]{task.fields[msg]}")]
        self._desc = description
        self._p = self._RP(*cols, transient=False)
        self._p.start()
        self._task = self._p.add_task(description, total=total, msg="")

    def update(self, completed, message=""):
        if self._p is not None:
            kw = {"msg": message[:60]} if message else {}
            self._p.update(self._task, completed=completed, **kw)

    def note(self, message):
        if self._p is not None:
            self._p.update(self._task, msg=message[:60])

    def close(self, message="", ok=True):
        if self._p is None:
            return
        task = self._p.tasks[0]
        # Mark the task finished so the spinner column disappears.
        self._p.update(self._task, total=task.total or 1, completed=task.total or 1)
        self._p.update(
            self._task,
            description=("[green]✓ " if ok else "[red]✕ ") + self._desc,
            msg=message[:80],
        )
        self._p.stop()
        self._p = None


def make_progress(enabled: Union[bool, Progress, Callable[[], Progress]] = True) -> Progress:
    """``True`` → auto (tqdm in notebooks, rich in terminals), ``False`` → silent,
    a :class:`Progress` instance or a zero-arg factory → used as-is (the UI does this)."""
    if isinstance(enabled, Progress):
        return enabled
    if callable(enabled):
        return enabled()
    if not enabled:
        return NullProgress()
    try:
        if in_notebook():
            return TqdmProgress()
        return RichProgress()
    except Exception:  # pragma: no cover - missing/broken frontend
        try:
            return TqdmProgress()
        except Exception:
            return NullProgress()
