"""Timer implementations for SCL execution.

This module provides implementations of TIA Portal timer blocks:
- TON_TIME: On-delay timer
- TOF_TIME: Off-delay timer
- TP_TIME: Pulse timer

All timers are designed to work with the MockClock for deterministic testing.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plc_code.executor.runtime import MockClock

#: Every SCL spelling of an IEC timer instance type, mapped to the class name here.
#: A TIA export writes a multi-instance either as the IEC type (``TON``) or as its
#: instance data type (``TON_TIME``); both are the same timer.
TIMER_TYPE_NAMES: dict[str, str] = {
    "TON": "TON_TIME",
    "TON_TIME": "TON_TIME",
    "TOF": "TOF_TIME",
    "TOF_TIME": "TOF_TIME",
    "TP": "TP_TIME",
    "TP_TIME": "TP_TIME",
}


def timer_class_name(data_type: str | None) -> str | None:
    """The timer class a declared type names (case-insensitively), or ``None``."""
    if data_type is None:
        return None
    return TIMER_TYPE_NAMES.get(data_type.strip().upper())


@dataclass
class TON_TIME:
    """On-delay timer (TON).

    The output Q turns on after the input IN has been True for the
    preset time PT. When IN goes False, Q immediately turns off.

    Timing diagram:
    ```
    IN:  _____|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|_____
    Q:   _________|‾‾‾‾‾‾‾‾‾‾‾‾‾|_____
              <PT>
    ET:  0----->PT             0
    ```

    Attributes
    ----------
    IN : bool
        Timer input (enable).
    PT : float
        Preset time in seconds.
    Q : bool
        Timer output.
    ET : float
        Elapsed time in seconds.
    """

    IN: bool = False
    PT: float = 0.0
    Q: bool = False
    ET: float = 0.0
    _start_time: float | None = field(default=None, repr=False)
    _was_in: bool = field(default=False, repr=False)

    def __call__(
        self,
        IN: bool,
        PT: float,
        clock: "MockClock",
    ) -> None:
        """Execute the timer logic for one cycle.

        Parameters
        ----------
        IN : bool
            Timer input (enable).
        PT : float
            Preset time in seconds.
        clock : MockClock
            The simulation clock.
        """
        self.IN = IN
        self.PT = PT
        current_time = clock.get_time()

        # Rising edge - start timing
        if IN and not self._was_in:
            self._start_time = current_time

        if IN:
            if self._start_time is not None:
                self.ET = current_time - self._start_time
                self.Q = self.ET >= PT
            else:
                self.ET = 0.0
                self.Q = False
        else:
            # Input is False - reset
            self._start_time = None
            self.ET = 0.0
            self.Q = False

        self._was_in = IN

    def reset(self) -> None:
        """Reset the timer to initial state."""
        self.IN = False
        self.Q = False
        self.ET = 0.0
        self._start_time = None
        self._was_in = False


@dataclass
class TOF_TIME:
    """Off-delay timer (TOF).

    The output Q turns on immediately when IN is True. When IN goes
    False, Q remains on for the preset time PT before turning off.

    Timing diagram:
    ```
    IN:  _____|‾‾‾‾‾‾‾|_______________
    Q:   _____|‾‾‾‾‾‾‾‾‾‾‾‾‾‾|________
                       <PT>
    ET:  0              0---->PT
    ```

    Attributes
    ----------
    IN : bool
        Timer input.
    PT : float
        Preset time in seconds.
    Q : bool
        Timer output.
    ET : float
        Elapsed time in seconds.
    """

    IN: bool = False
    PT: float = 0.0
    Q: bool = False
    ET: float = 0.0
    _fall_time: float | None = field(default=None, repr=False)
    _was_in: bool = field(default=False, repr=False)

    def __call__(
        self,
        IN: bool,
        PT: float,
        clock: "MockClock",
    ) -> None:
        """Execute the timer logic for one cycle.

        Parameters
        ----------
        IN : bool
            Timer input.
        PT : float
            Preset time in seconds.
        clock : MockClock
            The simulation clock.
        """
        self.IN = IN
        self.PT = PT
        current_time = clock.get_time()

        # Falling edge - start off-delay
        if not IN and self._was_in:
            self._fall_time = current_time

        if IN:
            # Input is True - output is True, no delay
            self._fall_time = None
            self.ET = 0.0
            self.Q = True
        elif self._fall_time is not None:
            # Input is False, counting down
            self.ET = current_time - self._fall_time
            if self.ET >= PT:
                self.Q = False
            else:
                self.Q = True
        else:
            # Input was never True
            self.ET = 0.0
            self.Q = False

        self._was_in = IN

    def reset(self) -> None:
        """Reset the timer to initial state."""
        self.IN = False
        self.Q = False
        self.ET = 0.0
        self._fall_time = None
        self._was_in = False


@dataclass
class TP_TIME:
    """Pulse timer (TP).

    Generates a pulse of duration PT on the rising edge of IN.
    Once started, the pulse runs to completion regardless of IN.

    Timing diagram:
    ```
    IN:  _____|‾‾‾|___|‾|_____|‾‾‾‾‾‾‾|___
    Q:   _____|‾‾‾‾‾‾‾‾|_____|‾‾‾‾‾‾‾‾|___
              <---PT-->       <---PT-->
    ET:  0--->PT        0---->PT
    ```

    Attributes
    ----------
    IN : bool
        Timer input (trigger).
    PT : float
        Preset time (pulse duration) in seconds.
    Q : bool
        Timer output (pulse).
    ET : float
        Elapsed time in seconds.
    """

    IN: bool = False
    PT: float = 0.0
    Q: bool = False
    ET: float = 0.0
    _pulse_start: float | None = field(default=None, repr=False)
    _was_in: bool = field(default=False, repr=False)

    def __call__(
        self,
        IN: bool,
        PT: float,
        clock: "MockClock",
    ) -> None:
        """Execute the timer logic for one cycle.

        Parameters
        ----------
        IN : bool
            Timer input (trigger).
        PT : float
            Preset time (pulse duration) in seconds.
        clock : MockClock
            The simulation clock.
        """
        self.IN = IN
        self.PT = PT
        current_time = clock.get_time()

        # Rising edge and not currently pulsing - start pulse
        if IN and not self._was_in and self._pulse_start is None:
            self._pulse_start = current_time

        if self._pulse_start is not None:
            self.ET = current_time - self._pulse_start
            if self.ET >= PT:
                # Pulse complete
                self.Q = False
                self._pulse_start = None
                self.ET = 0.0
            else:
                # Pulse in progress
                self.Q = True
        else:
            self.ET = 0.0
            self.Q = False

        self._was_in = IN

    def reset(self) -> None:
        """Reset the timer to initial state."""
        self.IN = False
        self.Q = False
        self.ET = 0.0
        self._pulse_start = None
        self._was_in = False
