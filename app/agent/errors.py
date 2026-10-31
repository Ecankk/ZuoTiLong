"""Session/turn conflicts shared by API and Agent components."""
class BridgeConflict(ValueError):pass
class SessionControlConflict(RuntimeError):pass
