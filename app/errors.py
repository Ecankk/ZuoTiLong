"""Service failures carry a public message and a stable HTTP status."""
class ServiceError(ValueError):
    def __init__(self,message,status=400,*,reason=None):super().__init__(message);self.status=status;self.reason=reason
