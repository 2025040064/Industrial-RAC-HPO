"""Stable failure codes. The host records the code; details go to stderr."""


class HarnessError(Exception):
    def __init__(self, code, detail=""):
        if not isinstance(code, str) or not code:
            code = "HARNESS_ERROR"
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code
