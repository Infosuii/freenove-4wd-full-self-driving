from enum import Enum


class Mode(str, Enum):
    MANUAL = "MANUAL"
    AUTONOMOUS = "AUTONOMOUS"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class Phase(str, Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    AI_STARTING = "AI_STARTING"
    AI_OBSERVING = "AI_OBSERVING"
    AI_DECIDING = "AI_DECIDING"
    AI_ACTING = "AI_ACTING"
    AI_INSPECTING = "AI_INSPECTING"
    SAFETY_STOP = "SAFETY_STOP"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    AI_ERROR = "AI_ERROR"


INTERRUPTS = {Phase.MANUAL, Phase.SAFETY_STOP, Phase.EMERGENCY_STOP,
              Phase.CONNECTION_ERROR, Phase.AI_ERROR}
NEXT = {
    Phase.IDLE: {Phase.AI_STARTING},
    Phase.MANUAL: {Phase.AI_STARTING},
    Phase.AI_STARTING: {Phase.AI_OBSERVING},
    Phase.AI_OBSERVING: {Phase.AI_DECIDING},
    Phase.AI_DECIDING: {Phase.AI_ACTING, Phase.AI_INSPECTING, Phase.AI_OBSERVING},
    Phase.AI_ACTING: {Phase.AI_OBSERVING},
    Phase.AI_INSPECTING: {Phase.AI_OBSERVING},
    Phase.SAFETY_STOP: {Phase.AI_STARTING},
    Phase.CONNECTION_ERROR: {Phase.AI_STARTING},
    Phase.AI_ERROR: {Phase.AI_STARTING},
    Phase.EMERGENCY_STOP: set(),
}


class StateMachine:
    def __init__(self):
        self.phase = Phase.IDLE

    def transition(self, target, recovery=False):
        if not isinstance(target, Phase):
            raise ValueError("Unknown controller state")
        if self.phase == Phase.EMERGENCY_STOP:
            if target == self.phase:
                return
            if target != Phase.MANUAL or not recovery:
                raise ValueError("Emergency stop requires deliberate recovery")
        elif target != self.phase and target not in NEXT[self.phase] | INTERRUPTS:
            raise ValueError(f"Illegal transition {self.phase} -> {target}")
        self.phase = target


def oscillating(history):
    actions = [h["action"] for h in history][-6:]
    if len(actions) < 6:
        return False
    if len(set(actions)) == 1 and actions[0] != "STOP":
        return True
    return (actions[0] != actions[1] and actions[::2] == [actions[0]] * 3
            and actions[1::2] == [actions[1]] * 3)
