"""
Smart Space Pulse — Display / LED / Buzzer Logic

Controls LCD output, LED bar color, and buzzer chirps on state transitions.
"""


# LED color thresholds (based on score 0–100)
def get_led_color(score: float) -> str:
    """Determine LED bar color from occupancy score.

    Args:
        score: Occupancy suitability score (0–100).

    Returns:
        Color name: "green", "amber", or "red".
    """
    if score >= 65:
        return "green"
    elif score >= 55:
        return "amber"
    return "red"


def format_lcd(state: str, score: float, spl_db: float) -> str:
    """Format the LCD display string.

    Args:
        state: Current occupancy state label.
        score: Suitability score.
        spl_db: Current SPL reading.

    Returns:
        Formatted string for LCD display.
    """
    return f"{state} | {score:.0f}\nSPL: {spl_db:.1f} dB"


def chirp_on_transition(prev_state: str, current_state: str) -> bool:
    """Determine whether buzzer should chirp (state transition only).

    Args:
        prev_state: Previous occupancy state.
        current_state: Current occupancy state.

    Returns:
        True if buzzer should chirp (state changed).
    """
    return prev_state != current_state
