#!/usr/bin/env python3
# Periodically query an SRCDS server via A2S and restart/start a systemd unit if it's down.
# Usage examples:
#  - Direct (user unit): python3 check_srcds_restart.py --server-host 127.0.0.1 --port 27015 --restart-unit my-server@instance.service --unit-scope user
#  - Direct (system unit): python3 check_srcds_restart.py --server-host 127.0.0.1 --port 27015 --restart-unit my-server.service --unit-scope system
#
# Requirements: pip install a2s
# Optional (recommended for D-Bus control): ensure python-dbus is installed (e.g. python3-dbus package).
# If the dbus Python bindings are not available, the script will fall back to systemctl.

import argparse
import os
import time
import subprocess
import a2s
import sys
import bisect
import socket
from datetime import datetime
from enum import Enum
from typing import List, Tuple, Any


class UnitScope(Enum):
    USER = "user"
    SYSTEM = "system"


class RestartSkipped(Exception):
    """Raised when a restart is skipped due to cooldown or rate limiting."""


class RestartFailed(Exception):
    """Raised when a restart attempt failed (non-zero exit or execution error)."""


class Monitor:
    def __init__(
        self,
        server_host: str,
        port: int,
        restart_unit: str,
        interval: float,
        timeout: float,
        failure_threshold: int,
        restart_cooldown: float,
        max_restarts_per_hour: int,
        unit_scope: UnitScope,
    ):
        self.server_host = server_host
        self.port = port
        self.restart_unit = restart_unit
        self.interval = interval
        self.timeout = timeout
        self.failure_threshold = failure_threshold
        self.restart_cooldown = restart_cooldown
        self.max_restarts_per_hour = max_restarts_per_hour
        self.unit_scope = unit_scope  # UnitScope enum

        # Validate parameters (prevent negatives / invalid values)
        self._validate_params()

        # per-monitor private state (PEP-8 "private" attributes)
        self._consecutive_failures = 0
        # monotonic timestamps of restart/start attempts (sorted ascending)
        self._restart_timestamps_monotonic: List[float] = []

    def _validate_params(self) -> None:
        """Validate configuration parameters and raise ValueError on invalid input."""
        if not self.server_host:
            raise ValueError("server_host must be provided and non-empty")
        if not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ValueError("port must be an integer in range 1..65535")
        if not isinstance(self.interval, (int, float)) or self.interval <= 0:
            raise ValueError("interval must be a positive number (seconds)")
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("timeout must be a positive number (seconds)")
        if not isinstance(self.failure_threshold, int) or self.failure_threshold < 1:
            raise ValueError("failure_threshold must be an integer >= 1")
        if not isinstance(self.restart_cooldown, (int, float)) or self.restart_cooldown < 0:
            raise ValueError("restart_cooldown must be a non-negative number (seconds)")
        if not isinstance(self.max_restarts_per_hour, int) or self.max_restarts_per_hour < 0:
            raise ValueError("max_restarts_per_hour must be an integer >= 0 (0 means unlimited)")
        if not self.restart_unit:
            raise ValueError("restart_unit must be provided and non-empty")
        if not isinstance(self.unit_scope, UnitScope):
            raise ValueError("unit_scope must be a UnitScope enum value")

    def _log(self, *parts) -> None:
        """Log with local timezone-aware ISO timestamp prefixed."""
        ts = datetime.now().astimezone().isoformat()
        print(ts, *parts, flush=True)

    def prune_restart_timestamps(self) -> None:
        """Keep only monotonic timestamps within the last hour for rate limiting.
        Assumes self._restart_timestamps_monotonic is sorted ascending and uses bisect.
        """
        cutoff = time.monotonic() - 3600.0
        idx = bisect.bisect_left(self._restart_timestamps_monotonic, cutoff)
        if idx:
            # mutate in place to preserve references
            self._restart_timestamps_monotonic[:] = self._restart_timestamps_monotonic[idx:]

    def can_restart(self) -> Tuple[bool, str]:
        """Return (True, reason) if allowed to restart now, otherwise (False, reason)."""
        self.prune_restart_timestamps()
        if self._restart_timestamps_monotonic:
            elapsed_since_last = time.monotonic() - self._restart_timestamps_monotonic[-1]
            if elapsed_since_last < self.restart_cooldown:
                return False, f"cooldown ({int(self.restart_cooldown - elapsed_since_last)}s remaining)"

        # If max_restarts_per_hour is 0, interpret as "unlimited"
        if self.max_restarts_per_hour > 0 and len(self._restart_timestamps_monotonic) >= self.max_restarts_per_hour:
            return False, f"rate limit reached ({len(self._restart_timestamps_monotonic)} restarts in last hour)"

        return True, "ok"

    # --- D-Bus helpers: check unit active, start unit, and fallbacks to systemctl --- #

    def _dbus_bus(self) -> Tuple[Any, Any]:
        """Return the appropriate dbus module and bus instance based on unit_scope."""
        try:
            import dbus  # type: ignore
        except Exception as e:
            raise RestartFailed(f"dbus Python bindings not available: {e}")
        bus = dbus.SessionBus() if self.unit_scope == UnitScope.USER else dbus.SystemBus()
        return dbus, bus

    def _is_unit_active_via_dbus(self) -> bool:
        """Return True if unit is active according to systemd over D-Bus."""
        dbus, bus = self._dbus_bus()
        try:
            systemd_obj = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
            manager = dbus.Interface(systemd_obj, "org.freedesktop.systemd1.Manager")
            unit_path = manager.GetUnit(self.restart_unit)
            unit_obj = bus.get_object("org.freedesktop.systemd1", unit_path)
            props_iface = dbus.Interface(unit_obj, "org.freedesktop.DBus.Properties")
            active_state = props_iface.Get("org.freedesktop.systemd1.Unit", "ActiveState")
            return str(active_state) == "active"
        except Exception as e:
            raise RestartFailed(f"Error checking unit state via D-Bus: {e}")

    def _is_unit_active_via_systemctl(self) -> bool:
        """Fallback check using systemctl is-active."""
        cmd = ["systemctl"]
        if self.unit_scope == UnitScope.USER:
            cmd += ["--user"]
        cmd += ["is-active", "--quiet", self.restart_unit]
        rc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        return rc == 0

    def _is_unit_active(self) -> bool:
        """Check unit active state using D-Bus if possible, otherwise systemctl fallback."""
        try:
            return self._is_unit_active_via_dbus()
        except RestartFailed:
            try:
                return self._is_unit_active_via_systemctl()
            except Exception:
                return False

    def _start_unit_via_dbus(self) -> None:
        """Start unit using D-Bus StartUnit; raise RestartFailed on error."""
        dbus, bus = self._dbus_bus()
        try:
            systemd_obj = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
            manager = dbus.Interface(systemd_obj, "org.freedesktop.systemd1.Manager")
            manager.StartUnit(self.restart_unit, "replace")
        except Exception as e:
            raise RestartFailed(f"Error starting unit via D-Bus: {e}")

    def _start_unit_via_systemctl(self) -> None:
        """Fallback to systemctl start; raise RestartFailed on error."""
        cmd = ["systemctl"]
        if self.unit_scope == UnitScope.USER:
            cmd += ["--user"]
        cmd += ["start", self.restart_unit]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=30)
        if proc.returncode != 0:
            raise RestartFailed(proc.stderr.strip() or f"systemctl exit {proc.returncode}")

    def _start_unit(self) -> None:
        """Start the unit (Try D-Bus then fallback systemctl). Raises RestartFailed on failure.

        On success appends a monotonic timestamp and resets consecutive failures.
        """
        try:
            self._start_unit_via_dbus()
        except RestartFailed as dbus_err:
            try:
                self._start_unit_via_systemctl()
            except RestartFailed as sys_err:
                raise RestartFailed(f"D-Bus start error: {dbus_err}; systemctl start error: {sys_err}")

        # Success: record a single timestamp and reset failures
        self._restart_timestamps_monotonic.append(time.monotonic())
        self._consecutive_failures = 0

    # --- restart helpers (RestartUnit) fallback chain --- #

    def _restart_via_dbus(self) -> None:
        """Call systemd RestartUnit via D-Bus. Raises RestartFailed on error."""
        dbus, bus = self._dbus_bus()
        try:
            systemd_obj = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
            manager = dbus.Interface(systemd_obj, "org.freedesktop.systemd1.Manager")
            manager.RestartUnit(self.restart_unit, "replace")
        except Exception as e:
            raise RestartFailed(f"Error restarting unit via D-Bus: {e}")

    def _restart_via_systemctl(self) -> str:
        """Fallback to systemctl if D-Bus restart is not available or fails.
        Returns stdout on success (may be empty). Raises RestartFailed on failure."""
        cmd = ["systemctl"]
        if self.unit_scope == UnitScope.USER:
            cmd += ["--user"]
        cmd += ["restart", self.restart_unit]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=30)
        return_code = proc.returncode
        stdout_text = proc.stdout.strip()
        stderr_text = proc.stderr.strip()
        if return_code == 0:
            return stdout_text
        raise RestartFailed(stderr_text or f"systemctl exit {return_code}")

    def attempt_restart(self) -> str:
        """Attempt to restart configured systemd unit.
        On success returns stdout (may be empty).
        On skip raises RestartSkipped(reason).
        On failure raises RestartFailed(reason).

        Records a single monotonic timestamp for the attempt (even if both D-Bus and systemctl
        were tried and both fail) to avoid inflating the attempt count in the double-failure case.
        Resets consecutive failures on successful restart.
        """
        can_restart_now, skip_reason = self.can_restart()
        if not can_restart_now:
            raise RestartSkipped(skip_reason)

        # Try D-Bus RestartUnit first, fallback to systemctl restart on failure.
        self._log("Attempting RestartUnit via D-Bus for unit", self.restart_unit)
        try:
            self._restart_via_dbus()
        except RestartFailed as dbus_error:
            # D-Bus restart failed; fall back to systemctl restart
            self._log(f"D-Bus RestartUnit failed: {dbus_error=}")
            self._log("Falling back to systemctl restart")
            systemctl_stdout = self._restart_via_systemctl()
            # systemctl succeeded: reset failures
            self._consecutive_failures = 0
            if systemctl_stdout:
                self._log("Restart OK (systemctl stdout):", systemctl_stdout)
            else:
                self._log("Restart OK via systemctl")
            return systemctl_stdout or "ok"
        else:
            # D-Bus RestartUnit succeeded: reset failures
            self._consecutive_failures = 0
            self._log("Restart OK via D-Bus")
            return "ok"
        finally:
            # Always record exactly one attempt timestamp for this overall restart attempt.
            # This prevents double-appending when both D-Bus and systemctl are tried and both fail.
            self._restart_timestamps_monotonic.append(time.monotonic())

    # --- main check loop --- #

    def check_server(self) -> None:
        """Ensure the unit is running and then query the SRCDS server (if unit active)."""
        # 1) Ensure the unit is active. If not, start it and skip the A2S query.
        unit_active = self._is_unit_active()
        if not unit_active:
            self._log("Unit is not active; attempting to start unit:", self.restart_unit)
            try:
                self._start_unit()
            except RestartFailed as start_err:
                self._log("Start unit failed:", str(start_err))
                # As a fallback after a failed start attempt try a restart (RestartUnit).
                try:
                    out = self.attempt_restart()
                except RestartSkipped as rs:
                    self._log("SKIP restart:", str(rs))
                except Exception as e:
                    self._log("Restart failed after start attempt:", str(e))
                else:
                    self._log("Start unit succeeded:", out)
            else:
                self._log("Start unit succeeded:", self.restart_unit)
            return

        # 2) Unit is active -> perform A2S query
        try:
            info = a2s.info((self.server_host, self.port), timeout=self.timeout)
            # Use direct attributes provided by a2s.info
            player_count = info.player_count
            max_players = info.max_players
            map_name = info.map_name
            self._log("OK", f"{self.server_host}:{self.port}", f"players: {player_count}/{max_players}", f"map: {map_name}")
            self._consecutive_failures = 0
            return
        except Exception as e:
            self._consecutive_failures += 1
            self._log("ERROR querying server:", f"{self.server_host}:{self.port}", str(e), f"(consecutive failures={self._consecutive_failures})")

        # If we've reached the failure threshold, try to restart the unit.
        if self._consecutive_failures >= self.failure_threshold:
            self._log(f"Failure threshold reached ({self._consecutive_failures} >= {self.failure_threshold})")
            try:
                _ = self.attempt_restart()
            except RestartSkipped as rs:
                self._log("SKIP restart:", str(rs))
            except Exception as e:
                self._log("Restart failed:", str(e))

    def run(self) -> None:
        self._log(
            "Starting SRCDS monitor for",
            f"{self.server_host}:{self.port}",
            f"every {self.interval}s; will restart unit {self.restart_unit} after {self.failure_threshold} failures",
        )
        try:
            while True:
                self.check_server()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self._log("Interrupted by user, exiting")
            sys.exit(0)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SRCDS monitor that restarts/starts a systemd unit when the server is down.")
    # rename host -> server-host for clarity; fallback to env SERVER_HOST, otherwise current hostname
    p.add_argument(
        "--server-host",
        help="SRCDS host/IP (or set SERVER_HOST env)",
        default=os.getenv("SERVER_HOST", socket.gethostname()),
    )
    p.add_argument("--port", type=int, help="SRCDS query port", default=int(os.getenv("PORT", "27015")))
    p.add_argument(
        "--restart-unit",
        help="systemd unit to control (e.g. my-server@instance.service or my-server.service)",
        default=os.getenv("RESTART_UNIT"),
    )
    p.add_argument("--interval", type=float, help="seconds between checks", default=float(os.getenv("INTERVAL", "10")))
    p.add_argument("--timeout", type=float, help="a2s socket timeout (seconds)", default=float(os.getenv("TIMEOUT", "5")))
    p.add_argument("--failure-threshold", type=int, help="consecutive failed queries before restart/start", default=int(os.getenv("FAILURE_THRESHOLD", "3")))
    p.add_argument("--restart-cooldown", type=float, help="seconds to wait between restarts (monotonic)", default=float(os.getenv("RESTART_COOLDOWN", "300")))
    p.add_argument("--max-restarts-per-hour", type=int, help="max restarts allowed in rolling 1-hour window (0 = unlimited)", default=int(os.getenv("MAX_RESTARTS_PER_HOUR", "0")))
    p.add_argument("--unit-scope", choices=("user", "system"), help="control a user or system unit", default=os.getenv("UNIT_SCOPE", "user"))
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.server_host:
        print("Error: --server-host must be provided (or set SERVER_HOST env in systemd EnvironmentFile).", file=sys.stderr)
        sys.exit(2)
    if not args.restart_unit:
        print("Error: --restart-unit must be provided (or set RESTART_UNIT env in systemd EnvironmentFile).", file=sys.stderr)
        sys.exit(2)

    try:
        unit_scope_enum = UnitScope(args.unit_scope)
    except ValueError:
        print("Error: --unit-scope must be 'user' or 'system'", file=sys.stderr)
        sys.exit(2)

    try:
        monitor = Monitor(
            server_host=args.server_host,
            port=args.port,
            restart_unit=args.restart_unit,
            interval=args.interval,
            timeout=args.timeout,
            failure_threshold=args.failure_threshold,
            restart_cooldown=args.restart_cooldown,
            max_restarts_per_hour=args.max_restarts_per_hour,
            unit_scope=unit_scope_enum,
        )
    except ValueError as ve:
        print(f"Configuration error: {ve}", file=sys.stderr)
        sys.exit(2)

    monitor.run()


if __name__ == "__main__":
    main()