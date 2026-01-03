#!/usr/bin/env python3
# Periodically query an SRCDS server via A2S and restart/start its systemd unit if it's not responding.
# Usage examples:
#  - Direct (user unit): python3 check_srcds_restart.py --server-host 127.0.0.1 --port 27015 --systemd-unit my-server@instance.service --unit-scope user
#  - Direct (system unit): python3 check_srcds_restart.py --server-host 127.0.0.1 --port 27015 --systemd-unit my-server.service --unit-scope system
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


class RestartFailed(Exception):
    """Raised when a restart attempt failed (non-zero exit or execution error)."""


def _have_dbus() -> bool:
    """Return True if python-dbus is available."""
    try:
        import dbus  # type: ignore
    except Exception as e:
        return False
    return True


class Monitor:
    """SRCDS monitor class."""

    def __init__(
        self,
        server_host: str,
        port: int,
        systemd_unit: str,
        interval: float,
        timeout: float,
        failure_threshold: int,
        restart_cooldown: float,
        max_restarts_per_hour: int,
        unit_scope: UnitScope,
    ):
        """Initialise the SRCDS monitor."""
        self.server_host = server_host
        self.port = port
        self.systemd_unit = systemd_unit
        self.interval = interval
        self.timeout = timeout
        self.failure_threshold = failure_threshold
        self.restart_cooldown = restart_cooldown
        self.max_restarts_per_hour = max_restarts_per_hour
        self.unit_scope = unit_scope

        # Validate parameters (prevent negatives / invalid values)
        self._validate_params()

        # per-monitor private state
        self._consecutive_failures = 0
        # monotonic timestamps of restart/start attempts (sorted ascending)
        self._restart_timestamps_monotonic: List[float] = []
        # flag remembering whether the currently started process ever responded
        # this is used to ensure the server isn't still busy starting, for example downloading Workshop content
        self._proc_responded_after_start = False

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
        if not isinstance(self.failure_threshold,
                          int) or self.failure_threshold < 1:
            raise ValueError("failure_threshold must be an integer >= 1")
        if not isinstance(self.restart_cooldown,
                          (int, float)) or self.restart_cooldown < 0:
            raise ValueError(
                "restart_cooldown must be a non-negative number (seconds)")
        if not isinstance(self.max_restarts_per_hour,
                          int) or self.max_restarts_per_hour < 0:
            raise ValueError(
                "max_restarts_per_hour must be an integer >= 0 (0 means unlimited)"
            )
        if not self.systemd_unit:
            raise ValueError("systemd_unit must be provided and non-empty")
        if not isinstance(self.unit_scope, UnitScope):
            raise ValueError("unit_scope must be a UnitScope enum value")

    def _log(self, *parts) -> None:
        """Log with local timezone-aware ISO timestamp prefixed."""
        ts = datetime.now().astimezone().isoformat()
        print(ts, *parts, flush=True)

    # --- D-Bus helpers --- #
    def _get_dbus_bus(self) -> Any:
        """Return the appropriate bus instance based on unit_scope."""
        import dbus
        bus = dbus.SessionBus(
        ) if self.unit_scope == UnitScope.USER else dbus.SystemBus()
        return bus

    def _get_systemd_manager(self) -> Any:
        """Return the appropriate systemd Manager instance based on unit_scope."""
        try:
            import dbus
            bus = self._get_dbus_bus()
            systemd_obj = bus.get_object("org.freedesktop.systemd1",
                                         "/org/freedesktop/systemd1")
            return dbus.Interface(systemd_obj,
                                  "org.freedesktop.systemd1.Manager")
        except Exception as e:
            raise RestartFailed(
                f"Error acquiring systemd Manager via D-Bus: {e}")

    def _get_systemd_unit(self) -> Any:
        """Return the appropriate systemd Unit instance based on unit_scope."""
        try:
            bus = self._get_dbus_bus()
            manager = self._get_systemd_manager()
            unit_path = manager.GetUnit(self.systemd_unit)
            return bus.get_object("org.freedesktop.systemd1", unit_path)
        except Exception as e:
            raise RestartFailed(f"Error acquiring systemd Unit via D-Bus: {e}")

    # --- Unit properties via D-Bus and systemctl --- #
    def _unit_properties_via_dbus(self, properties: List[str]) -> dict:
        """Return a dictionary of properties of the systemd Unit via DBus."""
        if len(properties) == 0:
            # We can fast fail in this case, as this can only happen in case of a serious bug
            print("Error: Program requested an empty list of properties",
                  file=sys.stderr)
            sys.exit(1)
        try:
            import dbus
            unit_obj = self._get_systemd_unit()
            props_iface = dbus.Interface(unit_obj,
                                         "org.freedesktop.DBus.Properties")
            props_values = {}
            for prop in properties:
                props_values[prop] = props_iface.Get(
                    "org.freedesktop.systemd1.Unit", prop)
            return props_values
        except Exception as e:
            raise RestartFailed(f"Error querying properties via D-Bus: {e}")

    def _unit_properties_via_systemctl(self, properties: List[str]) -> dict:
        """Return a dictionary of properties of the systemd Unit via systemctl."""
        if len(properties) == 0:
            # We can fast fail in this case, as this can only happen in case of a serious bug
            print("Error: Program requested an empty list of properties",
                  file=sys.stderr)
            sys.exit(1)
        cmd_base = ["systemctl"]
        if self.unit_scope == UnitScope.USER:
            cmd_base += ["--user"]
        cmd_base += ["show", "-p"]
        props_values = {}
        for prop in properties:
            cmd = cmd_base + [prop, self.systemd_unit]
            proc = subprocess.run(cmd,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            if proc.returncode != 0:
                raise RestartFailed(
                    proc.stderr.strip() or
                    f"Error checking unit state via systemctl: {proc.returncode}"
                )
            props_values[prop] = proc.stdout.strip()
        return props_values

    def get_unit_properties(self, properties: List[str]) -> dict:
        """Retrieve unit properties using D-Bus if possible, otherwise fallback to systemctl."""
        if _have_dbus():
            return self._unit_properties_via_dbus(properties)
        else:
            return self._unit_properties_via_systemctl(properties)

    def get_unit_state(self) -> str:
        """Determine the unit state using D-Bus if possible, otherwise fallback to systemctl."""
        return self.get_unit_properties(["ActiveState"])["ActiveState"]

    # --- Restart via D-Bus and systemctl --- #
    def _restart_unit_via_dbus(self) -> None:
        """Restart unit using D-Bus RestartUnit."""
        try:
            manager = self._get_systemd_manager()
            manager.RestartUnit(self.systemd_unit, "replace")
        except Exception as e:
            raise RestartFailed(f"Error starting unit via D-Bus: {e}")

    def _restart_unit_via_systemctl(self) -> None:
        """Fallback to systemctl start; raise RestartFailed on error."""
        cmd = ["systemctl"]
        if self.unit_scope == UnitScope.USER:
            cmd += ["--user"]
        cmd += ["restart", self.systemd_unit]

        proc = subprocess.run(cmd,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              text=True,
                              check=False,
                              timeout=30)
        if proc.returncode != 0:
            raise RestartFailed(
                proc.stderr.strip()
                or f"Error restarting unit via systemctl: {proc.returncode}")

    def _restart_unit(self) -> None:
        """Start the unit via D-Bus if available, or via systemctl otherwise.

        On success appends a monotonic timestamp and resets consecutive failures.
        """
        # In debug, ensure that this is not called if it wasn't allowed
        assert self.is_restart_allowed()[0]

        if _have_dbus():
            self._restart_unit_via_dbus()
        else:
            self._restart_unit_via_systemctl()

        # Success: record a single timestamp and reset failures
        self._restart_timestamps_monotonic.append(time.monotonic())
        self._consecutive_failures = 0
        self._proc_responded_after_start = False

    def prune_restart_timestamps(self) -> None:
        """Prune timestamps eliminating those not within the last hour for rate limiting."""
        cutoff = time.monotonic() - 3600.0
        idx = bisect.bisect_left(self._restart_timestamps_monotonic, cutoff)
        if idx:
            self._restart_timestamps_monotonic[:] = self._restart_timestamps_monotonic[
                idx:]

    def is_restart_allowed(self) -> Tuple[bool, str]:
        """Return (True, reason) if allowed to restart now, otherwise (False, reason)."""
        self.prune_restart_timestamps()

        # Disallow restarts during the pre-start stage
        active_state = self.get_unit_state()
        match active_state:
            case "failed":
                return False, "restart forbidden as the unit failed"
            case "inactive":
                return False, "unit is listed as inactive"
            case "activating" | "deactivating" | "refreshing" | "reloading":
                return False, f"unit is in a transitional state {active_state}"
            case "maintenance":
                return False, f"unit is in maintenance"
            case "active":
                if not self._proc_responded_after_start:
                    return False, "current unit process has not responded yet; likely in startup"

                if self._restart_timestamps_monotonic:
                    elapsed_since_last = time.monotonic(
                    ) - self._restart_timestamps_monotonic[-1]
                    if elapsed_since_last < self.restart_cooldown:
                        return False, f"cooldown ({int(self.restart_cooldown - elapsed_since_last)}s remaining)"

                # If max_restarts_per_hour is 0, interpret it as "unlimited"
                if self.max_restarts_per_hour > 0 and len(
                        self._restart_timestamps_monotonic
                ) >= self.max_restarts_per_hour:
                    return False, f"rate limit reached ({len(self._restart_timestamps_monotonic)} restarts in last hour)"

                return True, "restart allowed"
            case _:
                raise RuntimeError(f"unit is in unknown state {active_state}")

    def attempt_restart(self) -> bool:
        """Attempt to restart configured systemd unit.
        Returns whether a restart was attempted.
        """
        may_restart_now, skip_reason = self.is_restart_allowed()
        if not may_restart_now:
            self._log("Skipping restart:", skip_reason)
            return False

        # Try D-Bus RestartUnit first, fallback to systemctl restart on failure.
        self._log("Attempting RestartUnit via D-Bus for unit",
                  self.systemd_unit)
        try:
            self._restart_unit()
        except Exception as e:
            self._log("Restart failed after start attempt:", str(e))
            raise e

        self._log("Restart of unit succeeded:", self.systemd_unit)
        return True

    # --- main check loop --- #

    def check_server(self) -> None:
        """Ensure the unit is running and then query the SRCDS server (if unit active)."""
        # If the unit is currently in a transitional state, we wait it out
        active_state = self.get_unit_state()
        time_waited = 0
        while active_state in [
                "activating", "deactivating", "reloading", "refreshing"
        ]:
            if time_waited >= 300:
                raise RuntimeError(
                    f"Unit {self.systemd_unit} has been in state {active_state} over {time_waited}s"
                )
            time.sleep(10)
            time_waited += 10
            active_state = self.get_unit_state()

        # If the unit is not active, reset the failure count to prevent previous failures from causing a chain reset
        if active_state != "active":
            self._consecutive_failures = 0
            self._proc_responded_after_start = False

        match active_state:
            case "maintenance":
                self._log("Unit is in maintenance; refusing restart:",
                          self.systemd_unit)
            case "inactive":
                self._log(
                    "Unit is inactive, but not failed; refusing restart:",
                    self.systemd_unit)
            case "failed":
                self._log("Unit has failed; restart handled by systemd:",
                          self.systemd_unit)
            case "active":
                # Unit is active -> perform A2S query
                try:
                    info = a2s.info((self.server_host, self.port),
                                    timeout=self.timeout)
                    self._log(
                        "OK", f"{self.server_host}:{self.port}",
                        f"players: {info.player_count}/{info.max_players}",
                        f"map: {info.map_name}")
                    self._consecutive_failures = 0
                    self._proc_responded_after_start = True
                except Exception as e:
                    if self._proc_responded_after_start:
                        self._consecutive_failures += 1
                        self._log(
                            "ERROR querying server:",
                            f"{self.server_host}:{self.port}", str(e),
                            f"(consecutive failures={self._consecutive_failures})"
                        )

                        # If we've reached the failure threshold, try to restart the unit.
                        if self._consecutive_failures >= self.failure_threshold:
                            self._log(
                                f"Failure threshold reached ({self._consecutive_failures} >= {self.failure_threshold})"
                            )
                            self.attempt_restart()

    def run(self) -> None:
        """SRCDS monitor main loop."""
        self._log(
            "Starting SRCDS monitor for",
            f"{self.server_host}:{self.port}",
            f"every {self.interval}s; will restart unit {self.systemd_unit} after {self.failure_threshold} failures",
        )
        try:
            while True:
                self.check_server()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self._log("Interrupted by user, exiting")
            sys.exit(0)


def parse_args() -> argparse.Namespace:
    """Initialise the commandline argument parser."""
    p = argparse.ArgumentParser(
        description=
        "SRCDS monitor that restarts/starts a systemd unit when the server is down."
    )
    # rename host -> server-host for clarity; fallback to env SERVER_HOST, otherwise current hostname
    p.add_argument(
        "--server-host",
        help="SRCDS host/IP (or set SERVER_HOST env)",
        default=os.getenv("SERVER_HOST", socket.gethostname())
    )
    p.add_argument("--port",
                   type=int,
                   help="SRCDS query port",
                   default=int(os.getenv("SERVER_PORT", "27015")))
    p.add_argument(
        "--systemd-unit",
        help=
        "systemd unit to control (e.g. my-server@instance.service or my-server.service)",
        default=os.getenv("SERVER_UNIT")
    )
    p.add_argument("--interval",
                   type=float,
                   help="seconds between checks",
                   default=float(os.getenv("INTERVAL", "30")))
    p.add_argument("--timeout",
                   type=float,
                   help="a2s socket timeout (seconds)",
                   default=float(os.getenv("TIMEOUT", "5")))
    p.add_argument("--failure-threshold",
                   type=int,
                   help="consecutive failed queries before restart/start",
                   default=int(os.getenv("FAILURE_THRESHOLD", "3")))
    p.add_argument("--restart-cooldown",
                   type=float,
                   help="seconds to wait between restarts (monotonic)",
                   default=float(os.getenv("RESTART_COOLDOWN", "300")))
    p.add_argument(
        "--max-restarts-per-hour",
        type=int,
        help="max restarts allowed in rolling 1-hour window (0 = unlimited)",
        default=int(os.getenv("MAX_RESTARTS_PER_HOUR", "0")))
    p.add_argument("--unit-scope",
                   choices=("user", "system"),
                   help="control a user or system unit",
                   default=os.getenv("SERVER_UNIT_SCOPE", "user"))
    return p.parse_args()


def main() -> None:
    """Main routine."""
    args = parse_args()

    if not args.server_host:
        print(
            "Error: --server-host must be provided (or set SERVER_HOST env in systemd EnvironmentFile).",
            file=sys.stderr)
        sys.exit(2)
    if not args.systemd_unit:
        print(
            "Error: --systemd-unit must be provided (or set SERVER_UNIT env in systemd EnvironmentFile).",
            file=sys.stderr)
        sys.exit(2)

    try:
        unit_scope_enum = UnitScope(args.unit_scope)
    except ValueError:
        print("Error: --unit-scope must be 'user' or 'system'",
              file=sys.stderr)
        sys.exit(2)

    try:
        monitor = Monitor(server_host=args.server_host,
                          port=args.port,
                          systemd_unit=args.systemd_unit,
                          interval=args.interval,
                          timeout=args.timeout,
                          failure_threshold=args.failure_threshold,
                          restart_cooldown=args.restart_cooldown,
                          max_restarts_per_hour=args.max_restarts_per_hour,
                          unit_scope=unit_scope_enum)
    except ValueError as ve:
        print(f"Configuration error: {ve}", file=sys.stderr)
        sys.exit(2)

    monitor.run()


if __name__ == "__main__":
    main()
