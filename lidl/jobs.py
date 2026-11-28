"""Háttérfeladatok (letöltés, render, export) futtatása és naplózása.

A webes felület és a parancssor ugyanazokat a ``python -m lidl ...``
hívásokat használja, csak itt egy szál figyeli a kimenetet, a napló pedig a
``DATA_DIR/logs`` mappába is bekerül. Egyszerre egy feladat futhat.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config

MAX_LINES = 3000
MAX_HISTORY = 50

ACTIONS: dict[str, dict] = {
    "fetch": {
        "label": "Új nyugták letöltése",
        "args": ["fetch", "--no-auto-login"],
    },
    "fetch-full": {
        "label": "Minden nyugta újraletöltése",
        "args": ["fetch", "--full", "--no-auto-login"],
    },
    "render": {
        "label": "PDF-ek renderelése",
        "args": ["render"],
    },
    "render-force": {
        "label": "PDF-ek újragenerálása",
        "args": ["render", "--force"],
    },
    "export": {
        "label": "Jegyzék exportálása",
        "args": ["export"],
    },
    "warranty": {
        "label": "Garancia kimutatás",
        "args": ["warranty"],
    },
    "all": {
        "label": "Teljes frissítés",
        "args": ["all", "--no-auto-login"],
    },
}


@dataclass
class Job:
    id: str
    action: str
    label: str
    command: list[str]
    source: str = "manual"
    status: str = "running"
    returncode: int | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    log_path: Path | None = None
    lines: list[str] = field(default_factory=list)
    process: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def started_iso(self) -> str:
        return datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def finished_iso(self) -> str:
        if not self.finished_at:
            return ""
        return datetime.fromtimestamp(self.finished_at).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def output(self) -> str:
        return "\n".join(self.lines)

    @property
    def duration(self) -> str:
        end = self.finished_at or time.time()
        seconds = max(0, int(end - self.started_at))
        if seconds < 60:
            return f"{seconds} s"
        minutes, rest = divmod(seconds, 60)
        return f"{minutes} min {rest:02d} s"

    def to_dict(self, include_output: bool = True) -> dict:
        payload = {
            "id": self.id,
            "action": self.action,
            "label": self.label,
            "source": self.source,
            "status": self.status,
            "returncode": self.returncode,
            "started": self.started_iso,
            "finished": self.finished_iso,
            "duration": self.duration,
            "log_path": self.log_path.name if self.log_path else "",
        }
        if include_output:
            payload["output"] = self.output
        return payload


class JobManager:
    """Egyszerre egy futó feladat, a többit sorba nem teszi."""

    def __init__(
        self,
        data_dir: Path | None = None,
        output_dir: Path | None = None,
        settings_loader=None,
        on_finish=None,
    ):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.output_dir = Path(output_dir or config.OUTPUT_DIR)
        self.logs_dir = self.data_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self.data_dir / "jobs.json"
        self._settings_loader = settings_loader or config.load_settings
        self.on_finish = on_finish
        self._jobs: dict[str, Job] = {}
        self._current: str | None = None
        self._lock = threading.RLock()
        self._load_history()

    # -- nyilvántartás -------------------------------------------------
    def _load_history(self) -> None:
        if not self._history_file.is_file():
            return
        try:
            raw = json.loads(self._history_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                job = Job(
                    id=str(item["id"]),
                    action=str(item.get("action") or ""),
                    label=str(item.get("label") or ""),
                    command=[],
                    source=str(item.get("source") or "manual"),
                    status=str(item.get("status") or "done"),
                    returncode=item.get("returncode"),
                    started_at=float(item.get("started_at") or 0),
                    finished_at=float(item.get("finished_at") or 0) or None,
                )
                log_name = str(item.get("log_name") or "")
                if log_name:
                    job.log_path = self.logs_dir / log_name
                if job.status == "running":
                    # A konténer leállt a futás közben; ne maradjon örökre "Fut".
                    job.status = "stopped"
                self._jobs[job.id] = job
            except (KeyError, TypeError, ValueError):
                continue

    def _save_history(self) -> None:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.started_at, reverse=True)
            payload = [
                {
                    "id": job.id,
                    "action": job.action,
                    "label": job.label,
                    "source": job.source,
                    "status": job.status,
                    "returncode": job.returncode,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "log_name": job.log_path.name if job.log_path else "",
                }
                for job in jobs[:MAX_HISTORY]
            ]
        tmp = self._history_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._history_file)
        except OSError:
            pass

    # -- lekérdezés ----------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def current(self) -> Job | None:
        with self._lock:
            if not self._current:
                return None
            job = self._jobs.get(self._current)
            if job is None or job.status != "running":
                self._current = None
                return None
            return job

    def history(self, limit: int = 25) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.started_at, reverse=True)
        return jobs[:limit]

    def log_text(self, job: Job) -> str:
        if job.log_path and job.log_path.is_file():
            try:
                return job.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return job.output

    # -- indítás / leállítás -------------------------------------------
    def build_command(self, action: str) -> list[str] | None:
        spec = ACTIONS.get(action)
        if not spec:
            return None
        args = list(spec["args"])
        return [sys.executable, "-u", "-m", "lidl", *args]

    def start(self, action: str, source: str = "manual") -> tuple[Job | None, str | None]:
        spec = ACTIONS.get(action)
        if spec is None:
            return None, "Ismeretlen művelet."
        command = self.build_command(action)
        if command is None:
            return None, "Érvénytelen művelet."
        with self._lock:
            running = self.current()
            if running is not None:
                return None, f"Már fut egy feladat: {running.label}."
            job_id = secrets.token_hex(6)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = self.logs_dir / f"job-{stamp}-{job_id}.log"
            job = Job(
                id=job_id,
                action=action,
                label=str(spec["label"]),
                command=command,
                source=source,
                log_path=log_path,
            )
            header = (
                f"=== {job.label} · {datetime.now():%Y-%m-%d %H:%M:%S} "
                f"· {source} ===\n"
            )
            job.lines.append(header.rstrip("\n"))
            try:
                log_path.write_text(header, encoding="utf-8")
            except OSError:
                pass
            self._jobs[job_id] = job
            self._current = job_id
        threading.Thread(
            target=self._run, args=(job, command, source), daemon=True, name=f"job-{job_id}"
        ).start()
        return job, None

    def _run(self, job: Job, command: list[str], source: str) -> None:
        settings = {}
        try:
            settings = self._settings_loader() or {}
        except Exception:
            settings = {}
        env = config.env_for_child(settings)
        env["LIDL_DATA_DIR"] = str(self.data_dir)
        env["LIDL_OUTPUT_DIR"] = str(self.output_dir)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(config.ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as exc:
            with self._lock:
                job.status = "error"
                job.lines.append(f"Nem sikerült elindítani a parancsot: {exc}")
                job.finished_at = time.time()
                if self._current == job.id:
                    self._current = None
            self._append_log(job, f"Nem sikerült elindítani: {exc}")
            self._save_history()
            self._notify(job)
            return

        job.process = process
        if job.status == "stopped":
            try:
                process.terminate()
            except OSError:
                pass
        try:
            if process.stdout is not None:
                with process.stdout:
                    for line in process.stdout:
                        text = line.rstrip("\n")
                        with self._lock:
                            job.lines.append(text)
                            if len(job.lines) > MAX_LINES:
                                del job.lines[: len(job.lines) - MAX_LINES]
                        self._append_log(job, text)
        finally:
            returncode = process.wait()
            with self._lock:
                job.returncode = returncode
                job.finished_at = time.time()
                if job.status != "stopped":
                    job.status = "done" if returncode == 0 else "error"
                if self._current == job.id:
                    self._current = None
            self._append_log(
                job,
                f"=== vége: {job.status} (kilépési kód: {returncode}) ===",
            )
            self._save_history()
            self._notify(job)

    def _append_log(self, job: Job, text: str) -> None:
        if not job.log_path:
            return
        try:
            with job.log_path.open("a", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError:
            pass

    def _notify(self, job: Job) -> None:
        if not self.on_finish:
            return
        try:
            self.on_finish(job)
        except Exception:
            pass

    def stop(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False
            job.status = "stopped"
            if self._current == job_id:
                self._current = None
            process = job.process
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
            threading.Thread(
                target=self._kill_later, args=(process,), daemon=True
            ).start()
        self._append_log(job, "=== leállítás kérve ===")
        return True

    @staticmethod
    def _kill_later(process: subprocess.Popen, delay: float = 5.0) -> None:
        time.sleep(delay)
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
