"""Download, configure, start and stop a local single-node OpenSearch.

Two backends are supported:

* ``docker`` (preferred whenever a Docker daemon is reachable): runs the official
  ``opensearchproject/opensearch`` image with a named data volume.
* ``tarball`` (fallback on Linux without Docker, e.g. SageMaker Studio, which
  cannot run containers): downloads the official OpenSearch tarball, which ships
  with its own JDK, so nothing else needs to be installed.

``backend="auto"`` picks Docker if ``docker info`` succeeds, else the tarball.

Two flavors are supported:

* ``min``  (~250 MB download): lexical/BM25 search. Fast to install.
* ``full`` (~1 GB download, once): adds the k-NN plugin for semantic & hybrid
  search. Only the k-NN plugin is extracted to keep startup fast and memory low.

The server outlives the Python process (and notebook kernel restarts); calling
:meth:`LocalServer.start` again simply reconnects to it.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ._progress import make_progress
from ._utils import human_bytes, is_root, osss_home

DEFAULT_VERSION = "3.9.0"
FLAVORS = ("min", "full")
_KEEP_PLUGINS_FULL = {"opensearch-knn"}
_ARTIFACTS = "https://artifacts.opensearch.org/releases"


class ServerError(RuntimeError):
    """Raised when the local OpenSearch cannot be installed or started."""


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    raise ServerError(f"Unsupported CPU architecture: {platform.machine()}")


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _free_port(start: int) -> int:
    for p in range(start, start + 200):
        if not _port_open(p):
            return p
    raise ServerError(f"No free port found in range {start}-{start + 200}")


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Reap if it is our zombie child.
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        pass
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.exists():
        try:
            return b"org.opensearch.bootstrap.OpenSearch" in cmdline.read_bytes()
        except OSError:
            return True
    return True


def _http_get(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    import requests

    try:
        r = requests.get(url, timeout=timeout, proxies={"http": None, "https": None})
        if r.ok:
            return r.json()
    except Exception:
        return None
    return None


def docker_available(timeout: float = 8.0) -> bool:
    """True when the docker CLI exists *and* its daemon answers.

    SageMaker Studio (and many hosted notebooks) ship no Docker daemon, in which
    case osss falls back to the self-contained tarball.
    """
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=timeout)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_user() -> tuple:
    """(uid, gid) of the unprivileged account used when we are root."""
    import pwd

    for name in ("nobody",):
        try:
            pw = pwd.getpwnam(name)
            return pw.pw_uid, pw.pw_gid
        except KeyError:
            continue
    return 65534, 65534


def _ensure_traversable(path: Path) -> None:
    """When root, the unprivileged user must be able to reach ``path``."""
    for parent in [path, *path.parents]:
        try:
            mode = parent.stat().st_mode
        except FileNotFoundError:
            continue
        if not mode & stat.S_IXOTH:
            raise ServerError(
                f"OpenSearch cannot run as root, so osss runs it as 'nobody', but "
                f"'{parent}' is not accessible to other users. Set OSSS_HOME to a "
                f"directory such as /opt/osss (e.g. os.environ['OSSS_HOME']='/opt/osss')."
            )


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, gid)
        for f in files:
            try:
                os.chown(os.path.join(root, f), uid, gid, follow_symlinks=False)
            except FileNotFoundError:
                pass


def _make_world_readable(path: Path) -> None:
    for root, dirs, files in os.walk(path):
        st = os.stat(root)
        os.chmod(root, st.st_mode | stat.S_IROTH | stat.S_IXOTH | stat.S_IRGRP | stat.S_IXGRP)
        for f in files:
            p = os.path.join(root, f)
            if os.path.islink(p):
                continue
            st = os.stat(p)
            mode = st.st_mode | stat.S_IROTH | stat.S_IRGRP
            if st.st_mode & stat.S_IXUSR:
                mode |= stat.S_IXOTH | stat.S_IXGRP
            os.chmod(p, mode)


class LocalServer:
    """A local, single-node OpenSearch managed by osss.

    Example::

        server = LocalServer().start()     # downloads on first use
        print(server.url)                  # http://127.0.0.1:9200
        server.stop()
    """

    def __init__(
        self,
        *,
        version: str = DEFAULT_VERSION,
        flavor: str = "min",
        port: int = 9200,
        heap: str = "1g",
        backend: str = "auto",
        home: Optional[os.PathLike] = None,
        name: str = "default",
    ) -> None:
        if flavor not in FLAVORS:
            raise ValueError(f"flavor must be one of {FLAVORS}, got {flavor!r}")
        self.home = Path(home).expanduser().resolve() if home else osss_home()
        self.name = name
        self.version = version
        self.heap = heap
        self.requested_port = port
        state = self._read_state()
        # Flavors only ever upgrade: an index built with vectors must not be
        # opened by a server without the k-NN plugin.
        if state.get("flavor") == "full" and state.get("version", version) == version:
            flavor = "full"
        self.flavor = flavor
        self._auto_backend = backend == "auto" and not state.get("backend")
        if backend == "auto":
            # Prefer Docker when a daemon is reachable (laptops, SageMaker notebook
            # instances, EC2); otherwise use the tarball (SageMaker Studio, Colab...).
            backend = state.get("backend") or (
                "docker" if docker_available() or platform.system() != "Linux" else "tarball"
            )
        if backend not in ("tarball", "docker"):
            raise ValueError("backend must be 'auto', 'tarball' or 'docker'")
        self.backend = backend
        self.port = int(state.get("port") or port)

    # ------------------------------------------------------------------ paths
    @property
    def dir(self) -> Path:
        return self.home / "servers" / self.name

    @property
    def state_file(self) -> Path:
        return self.dir / "state.json"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def dist_dir(self) -> Path:
        return self.home / "dist" / f"opensearch-{self.version}-{self.flavor}-linux-{_arch()}"

    def _read_state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text())
        except Exception:
            return {}

    def _write_state(self, **kw: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        state = self._read_state()
        state.update(kw)
        self.state_file.write_text(json.dumps(state, indent=2))

    # ------------------------------------------------------------------ status
    def info(self) -> Optional[Dict[str, Any]]:
        """Root endpoint response if the server answers, else ``None``."""
        return _http_get(self.url + "/")

    def is_running(self) -> bool:
        state = self._read_state()
        if self.backend == "docker":
            return self.info() is not None and bool(state.get("container"))
        return _pid_alive(state.get("pid")) and self.info() is not None

    def status(self) -> Dict[str, Any]:
        state = self._read_state()
        info = self.info()
        running = info is not None and (
            self.backend == "docker" or _pid_alive(state.get("pid"))
        )
        out: Dict[str, Any] = {
            "running": running,
            "url": self.url,
            "backend": self.backend,
            "flavor": self.flavor,
            "version": self.version,
            "semantic": self.flavor == "full",
            "home": str(self.home),
            "pid": state.get("pid"),
        }
        if running:
            out["opensearch_version"] = info.get("version", {}).get("number")
            health = _http_get(self.url + "/_cluster/health") or {}
            out["health"] = health.get("status")
            started = state.get("started_at")
            out["uptime_s"] = int(time.time() - started) if started else None
        return out

    def logs(self, lines: int = 80) -> str:
        if self.backend == "docker":
            state = self._read_state()
            cid = state.get("container")
            if not cid:
                return ""
            r = subprocess.run(["docker", "logs", "--tail", str(lines), cid], capture_output=True, text=True)
            return r.stdout + r.stderr
        log = self.dir / "logs" / "stdout.log"
        if not log.exists():
            return ""
        with open(log, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            text = f.read().decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-lines:])

    def client(self, **kwargs: Any):
        from .client import connect

        return connect(self.url, **kwargs)

    # ------------------------------------------------------------------ install
    def tarball_url(self) -> str:
        arch = _arch()
        if self.flavor == "min":
            return f"{_ARTIFACTS}/core/opensearch/{self.version}/opensearch-min-{self.version}-linux-{arch}.tar.gz"
        return f"{_ARTIFACTS}/bundle/opensearch/{self.version}/opensearch-{self.version}-linux-{arch}.tar.gz"

    def is_installed(self) -> bool:
        return (self.dist_dir / "bin" / "opensearch").exists()

    def install(self, progress: bool = True) -> Path:
        """Download and unpack OpenSearch (no-op if already installed)."""
        if self.backend == "docker":
            return self.home
        if platform.system() != "Linux":
            raise ServerError("The tarball backend only works on Linux; use backend='docker'.")
        if self.is_installed():
            return self.dist_dir
        url = self.tarball_url()
        downloads = self.home / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / url.rsplit("/", 1)[-1]
        if not archive.exists():
            self._download(url, archive, progress)
        self._extract(archive, progress)
        return self.dist_dir

    def _download(self, url: str, dest: Path, progress: bool) -> None:
        import requests

        p = make_progress(progress)
        label = "Downloading OpenSearch " + self.version + (" (with k-NN)" if self.flavor == "full" else "")
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                if r.status_code == 404:
                    raise ServerError(f"OpenSearch {self.version} not found at {url}")
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0) or None
                p.start(total, label, unit="B")
                done = 0
                last = 0.0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last > 0.25:
                            p.update(done)
                            last = now
            if total and tmp.stat().st_size != total:
                raise ServerError("Download was truncated; please retry.")
            tmp.replace(dest)
            p.close(human_bytes(done))
        except BaseException as e:
            p.close(str(e) or type(e).__name__, ok=False)
            tmp.unlink(missing_ok=True)
            if isinstance(e, ServerError):
                raise
            if isinstance(e, Exception):
                raise ServerError(
                    f"Could not download OpenSearch from {url}: {e}. If your notebook has no "
                    "internet access, download the file elsewhere and copy it to "
                    f"{dest}, or connect to an existing cluster with osss.connect(url)."
                ) from e
            raise

    def _extract(self, archive: Path, progress: bool) -> None:
        p = make_progress(progress)
        p.start(archive.stat().st_size, "Unpacking OpenSearch", unit="B")
        parent = self.dist_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp = parent / f".extract-{self.dist_dir.name}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        try:
            with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r:gz") as tar:
                last = 0.0
                for m in tar:
                    parts = m.name.split("/")
                    if (
                        self.flavor == "full"
                        and len(parts) >= 3
                        and parts[1] == "plugins"
                        and parts[2]
                        and parts[2] not in _KEEP_PLUGINS_FULL
                    ):
                        continue
                    tar.extract(m, tmp, **kw)
                    now = time.time()
                    if now - last > 0.25:
                        p.update(raw.tell())
                        last = now
            roots = [d for d in tmp.iterdir() if d.is_dir()]
            if len(roots) != 1 or not (roots[0] / "bin" / "opensearch").exists():
                raise ServerError(f"Unexpected archive layout in {archive}")
            if is_root():
                _make_world_readable(roots[0])
            shutil.rmtree(self.dist_dir, ignore_errors=True)
            roots[0].rename(self.dist_dir)
            p.close("done")
        except tarfile.ReadError as e:
            archive.unlink()
            p.close("corrupt download", ok=False)
            raise ServerError(f"Downloaded archive was corrupt ({e}); run start() again to re-download.") from e
        except BaseException as e:
            p.close(str(e), ok=False)
            raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ start / stop
    def start(self, wait: bool = True, timeout: float = 300, progress: bool = True) -> "LocalServer":
        """Start OpenSearch (installing it first if needed). Idempotent."""
        state = self._read_state()
        if self.is_running():
            running_flavor = state.get("flavor", "min")
            if running_flavor == self.flavor or running_flavor == "full":
                self.flavor = running_flavor
                return self
            # Upgrade min -> full (adds k-NN); the data directory is reused.
            self.stop()
        if self.backend == "docker":
            requested_flavor = self.flavor
            try:
                return self._start_docker(wait, timeout, progress)
            except ServerError as e:
                if not (self._auto_backend and platform.system() == "Linux"):
                    raise
                # Docker is there but unusable (registry blocked, rate-limited...):
                # the self-contained tarball still works.
                print(f"osss: Docker backend unavailable ({str(e).splitlines()[0]}); using the tarball instead.")
                self.backend = "tarball"
                self.flavor = requested_flavor
        return self._start_tarball(wait, timeout, progress)

    def _configure(self) -> Dict[str, str]:
        d = self.dir
        for sub in ("data", "logs", "tmp"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        conf = d / "config"
        if conf.exists() and (conf / ".osss-dist").exists() and (conf / ".osss-dist").read_text() != str(self.dist_dir):
            shutil.rmtree(conf)
        if not conf.exists():
            shutil.copytree(self.dist_dir / "config", conf)
            (conf / ".osss-dist").write_text(str(self.dist_dir))
        settings = {
            "cluster.name": "osss",
            "node.name": "osss-node",
            "path.data": str(d / "data"),
            "path.logs": str(d / "logs"),
            "network.host": "127.0.0.1",
            "http.port": str(self.port),
            "discovery.type": "single-node",
            # Notebook disks fill up quickly; don't flip indexes to read-only at 95%.
            "cluster.routing.allocation.disk.threshold_enabled": "false",
        }
        self._fix_jvm_options(conf / "jvm.options")
        (conf / "opensearch.yml").write_text(
            "# Managed by osss - regenerated on every start\n"
            + "".join(f"{k}: {json.dumps(v)}\n" for k, v in settings.items())
        )
        env = {k: v for k, v in os.environ.items() if k not in ("JAVA_HOME", "OPENSEARCH_JAVA_OPTS")}
        env.update(
            OPENSEARCH_JAVA_HOME=str(self.dist_dir / "jdk"),
            OPENSEARCH_PATH_CONF=str(conf),
            OPENSEARCH_JAVA_OPTS=f"-Xms{self.heap} -Xmx{self.heap}",
            OPENSEARCH_TMPDIR=str(d / "tmp"),
        )
        if is_root():
            env["HOME"] = str(d)
        return env

    def _fix_jvm_options(self, path: Path) -> None:
        """Point GC logs / heap dumps at our writable dirs.

        The stock jvm.options uses paths relative to the OpenSearch home, which
        is read-only for the unprivileged user we run as.
        """
        if not path.exists():
            return
        logs, data = self.dir / "logs", self.dir / "data"
        text = path.read_text()
        text = re.sub(r"file=logs/", f"file={logs}/", text)
        text = re.sub(r"ErrorFile=logs/", f"ErrorFile={logs}/", text)
        text = re.sub(r"HeapDumpPath=data\b", f"HeapDumpPath={data}", text)
        path.write_text(text)

    def _start_tarball(self, wait: bool, timeout: float, progress: bool) -> "LocalServer":
        self.install(progress=progress)
        # start() already established that *our* server is not running, so
        # anything listening on the port belongs to someone else.
        port = _free_port(self.port + 1) if _port_open(self.port) else self.port
        self.port = port
        env = self._configure()
        popen_kw: Dict[str, Any] = {}
        if is_root():
            uid, gid = _run_user()
            _ensure_traversable(self.dir)
            _ensure_traversable(self.dist_dir)
            for sub in ("data", "logs", "tmp", "config"):
                _chown_tree(self.dir / sub, uid, gid)
            os.chown(self.dir, uid, gid)
            popen_kw.update(user=uid, group=gid, extra_groups=[])
        log = open(self.dir / "logs" / "stdout.log", "ab")
        log.write(f"\n==== osss starting OpenSearch {self.version} ({self.flavor}) on port {port} ====\n".encode())
        log.flush()
        proc = subprocess.Popen(
            [str(self.dist_dir / "bin" / "opensearch")],
            cwd=str(self.dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            **popen_kw,
        )
        log.close()
        self._write_state(
            backend="tarball", pid=proc.pid, port=port, version=self.version,
            flavor=self.flavor, heap=self.heap, started_at=time.time(),
        )
        if wait:
            self._wait_ready(timeout, progress, proc=proc)
        return self

    def _start_docker(self, wait: bool, timeout: float, progress: bool) -> "LocalServer":
        if shutil.which("docker") is None:
            raise ServerError(
                "Docker is required on this platform but was not found. Install Docker, "
                "or connect to an existing cluster with osss.connect(url)."
            )
        cname = f"osss-{self.name}"
        self.flavor = "full"  # the official image ships every plugin
        state = self._read_state()
        if _port_open(self.port) and self.info() is None:
            self.port = _free_port(self.port + 1)
        exists = subprocess.run(["docker", "inspect", cname], capture_output=True).returncode == 0
        if exists and state.get("version") == self.version and state.get("port") == self.port:
            subprocess.run(["docker", "start", cname], check=True, capture_output=True)
        else:
            if exists:
                subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
            image = self._pull_image(progress)
            cmd = [
                "docker", "run", "-d", "--name", cname,
                "-p", f"127.0.0.1:{self.port}:9200",
                "--ulimit", "nofile=65536:65536",
                "-e", "discovery.type=single-node",
                "-e", "DISABLE_SECURITY_PLUGIN=true",
                "-e", "DISABLE_INSTALL_DEMO_CONFIG=true",
                "-e", "cluster.routing.allocation.disk.threshold_enabled=false",
                "-e", f"OPENSEARCH_JAVA_OPTS=-Xms{self.heap} -Xmx{self.heap}",
                "-v", f"osss-{self.name}-data:/usr/share/opensearch/data",
                image,
            ]
            p = make_progress(progress)
            p.start(None, f"Starting container {cname}")
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                p.close("failed", ok=False)
                raise ServerError(f"docker run failed: {r.stderr.strip()}")
            p.close("container started")
        cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", cname], capture_output=True, text=True).stdout.strip()
        self._write_state(
            backend="docker", container=cid, port=self.port, version=self.version,
            flavor="full", heap=self.heap, started_at=time.time(), pid=None,
        )
        if wait:
            self._wait_ready(timeout, progress)
        return self

    def docker_images(self) -> list:
        """Candidate images, in order. Override with ``OSSS_DOCKER_IMAGE``.

        ECR Public is tried first: it has no anonymous pull rate limits and is
        on the AWS network (fast from SageMaker/EC2). Docker Hub is the fallback.
        """
        env = os.environ.get("OSSS_DOCKER_IMAGE")
        if env:
            return [env if ":" in env.rsplit("/", 1)[-1] else f"{env}:{self.version}"]
        return [
            f"public.ecr.aws/opensearchproject/opensearch:{self.version}",
            f"opensearchproject/opensearch:{self.version}",
        ]

    def _pull_image(self, progress: bool) -> str:
        images = self.docker_images()
        for image in images:
            if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
                return image
        errors = []
        for image in images:
            p = make_progress(progress)
            p.start(None, f"Pulling {image} (first run only)")
            pull = subprocess.Popen(["docker", "pull", image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert pull.stdout is not None
            last = ""
            for line in pull.stdout:
                last = line.strip() or last
                p.note(last)
            if pull.wait() == 0:
                p.close("image ready")
                return image
            p.close("failed, trying next registry" if image != images[-1] else "failed", ok=False)
            errors.append(f"{image}: {last}")
        raise ServerError("Could not pull an OpenSearch image:\n  " + "\n  ".join(errors))

    def _wait_ready(self, timeout: float, progress: bool, proc: Optional[subprocess.Popen] = None) -> None:
        p = make_progress(progress)
        p.start(None, "Starting OpenSearch")
        t0 = time.time()
        while time.time() - t0 < timeout:
            if proc is not None and proc.poll() is not None:
                p.close("failed", ok=False)
                raise ServerError(self._explain_failure())
            health = _http_get(self.url + "/_cluster/health", timeout=1.5)
            if health and health.get("status") in ("green", "yellow"):
                p.close(f"ready at {self.url} in {time.time() - t0:.0f}s")
                return
            p.note(f"waiting for {self.url} … {time.time() - t0:.0f}s")
            time.sleep(1)
        p.close("timed out", ok=False)
        raise ServerError(f"OpenSearch did not become ready within {timeout:.0f}s.\n\n" + self.logs(40))

    def _explain_failure(self) -> str:
        tail = self.logs(60)
        hint = ""
        low = tail.lower()
        if "outofmemory" in low or "could not reserve enough space" in low:
            hint = "Not enough memory: try a smaller heap, e.g. osss.start(heap='512m')."
        elif "bindexception" in low or "address already in use" in low:
            hint = "The port is in use: try osss.start(port=9250)."
        elif "can not run opensearch as root" in low:
            hint = "OpenSearch refused to run as root."
        elif "permission denied" in low or "accessdeniedexception" in low:
            hint = f"Permission problem; try deleting {self.dir} or setting OSSS_HOME."
        return "OpenSearch exited during startup. " + hint + "\n\nLast log lines:\n" + tail

    def stop(self, timeout: float = 30) -> None:
        """Stop the server. Indexes are kept on disk and are back on next start."""
        state = self._read_state()
        if self.backend == "docker":
            if state.get("container"):
                subprocess.run(["docker", "stop", f"osss-{self.name}"], capture_output=True)
            return
        pid = state.get("pid")
        if not _pid_alive(pid):
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        t0 = time.time()
        while time.time() - t0 < timeout and _pid_alive(pid):
            time.sleep(0.3)
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._write_state(pid=None)

    def uninstall(self, keep_data: bool = False) -> None:
        """Stop the server and delete binaries (and data unless ``keep_data``)."""
        self.stop()
        shutil.rmtree(self.home / "dist", ignore_errors=True)
        shutil.rmtree(self.home / "downloads", ignore_errors=True)
        if not keep_data:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------ display
    def __repr__(self) -> str:
        s = self.status()
        return f"<LocalServer {'running' if s['running'] else 'stopped'} {self.url} {self.flavor} v{self.version}>"

    def _repr_html_(self) -> str:
        from .ui.render import server_card

        return server_card(self.status())
