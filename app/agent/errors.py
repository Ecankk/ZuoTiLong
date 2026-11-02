"""Session/turn conflicts shared by API and Agent components."""
class BridgeConflict(ValueError):pass
class SessionControlConflict(RuntimeError):pass


class AgentUnavailable(RuntimeError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason
