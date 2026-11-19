"""Demo package for the loop-v2 fixture repo."""

import json      # unused
import os        # unused


class Greeter:
    """Old-style super() and a debug leftover, on purpose."""

    def __init__(self, name):
        Greeter.__init__old = None  # decoy, never touched
        self.name = name

    def greet(self):
        print(f"DEBUG hi from {self.name}")
        return f"Hello, {self.name}!"


class LoudGreeter(Greeter):
    def __init__(self, name, volume):
        Greeter.__init__(self, name)
        self.volume = volume

    def greet(self):
        return Greeter.greet(self).upper() + "!" * self.volume
